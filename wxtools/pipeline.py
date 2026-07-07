# -*- coding: utf-8 -*-
"""微信数据管线：解密合并 MSG 分库、导出联系人 CSV、从 CSV 导出语音。

合并了原先的 refresh_export_csv.py / merge_msg1_via_api.py / export_voices_from_csv.py。
"""
from __future__ import annotations

import contextlib
import csv
import io
import os
import shutil
from datetime import datetime
from pathlib import Path

from .context import WORK_PATH, Account

# 标准导出 CSV 表头
CSV_HEADER = ["id", "MsgSvrID", "type_name", "is_sender", "talker", "room_name", "msg", "src", "CreateTime"]


# ------------------------- 实时合并（微信开着也能用） ------------------------- #

def merge_realtime(acct: Account) -> tuple[bool, str]:
    """微信开着也能尝试的实时合并，读取运行中微信进程的数据（无需退出）。

    依赖 pywxdump 自带的 realTime.exe，仅支持 64 位 Windows。这是 best-effort
    步骤：工具缺失、非 64 位、权限不足等都会失败，调用方不应因此中断后续的
    常规合并流程（失败时仍应继续走 merge_msg_shards / wait-refresh）。
    """
    try:
        from pywxdump import all_merge_real_time_db
    except ImportError as e:
        return False, f"pywxdump 未提供实时合并功能: {e}"
    ok, ret = all_merge_real_time_db(key=acct.key, wx_path=acct.wx_path, merge_path=acct.merge_path)
    return bool(ok), str(ret)


# ------------------------- 合并 MSG 分库 ------------------------- #

def merge_msg_shards(acct: Account, shards: list[int] | None = None) -> int:
    """解密 PC 端 Msg/Multi/MSG*.db 并增量合并进 merge_all.db。

    :param shards: 指定分库序号列表（如 [1]）；None 表示 0..15 全部尝试。
    :return: 成功合并的分库数量。
    """
    from pywxdump import batch_decrypt, merge_db

    multi = os.path.join(acct.wx_path, "Msg", "Multi")
    dec_base = WORK_PATH / "decrypted_refresh"
    if dec_base.exists():
        shutil.rmtree(dec_base, ignore_errors=True)
    dec_base.mkdir(parents=True, exist_ok=True)

    indices = shards if shards is not None else range(16)
    merged = failed = 0
    try:
        for i in indices:
            enc = os.path.join(multi, f"MSG{i}.db")
            if not os.path.isfile(enc):
                continue
            sub = dec_base / f"MSG{i}"
            sub.mkdir(parents=True, exist_ok=True)
            ok, ret = batch_decrypt(acct.key, enc, str(sub), is_print=False)
            if not ok:
                print(f"[-] 解密失败 MSG{i}（微信是否仍开着？）: {ret}")
                failed += 1
                continue
            de = sub / f"de_MSG{i}.db"
            if not de.is_file():
                print(f"[-] 未找到解密文件: {de}")
                failed += 1
                continue
            merge_db([{"db_path": enc, "de_path": str(de)}], acct.merge_path, is_merge_data=True)
            merged += 1
            print(f"[+] 已合并 MSG{i}.db")
    finally:
        shutil.rmtree(dec_base, ignore_errors=True)

    if failed:
        print(f"[!] {failed} 个分库解密失败，合并结果可能缺少最新消息")
    return merged


# ------------------------- 导出联系人 CSV ------------------------- #

def clean_old_csv(out_dir: Path, peer_wxid: str) -> None:
    """删除分页 CSV 与 users.json，保留手工文件（如 new_history.csv）。"""
    if not out_dir.is_dir():
        return
    for p in out_dir.glob(f"{peer_wxid}_*.csv"):
        p.unlink()
        print(f"[*] 删除旧文件: {p.name}")
    users = out_dir / "users.json"
    if users.is_file():
        users.unlink()
        print("[*] 删除旧 users.json")


def export_contact_csv(acct: Account, peer_wxid: str, clean: bool = True) -> Path:
    """导出指定联系人的聊天记录 CSV，返回输出目录。"""
    from pywxdump.api.export.exportCSV import export_csv

    out_dir = acct.csv_dir(peer_wxid)
    out_dir.mkdir(parents=True, exist_ok=True)
    if clean:
        clean_old_csv(out_dir, peer_wxid)
    ok, ret = export_csv(peer_wxid, str(out_dir), acct.db_config, my_wxid=acct.my_wxid)
    if not ok:
        raise SystemExit(f"[-] CSV 导出失败: {ret}")
    print(f"[+] {ret}")

    # 诊断：本地能读到的最新一条消息时间。读不到手机上刚同步的消息通常不是
    # 本工具的问题，而是微信 PC 客户端自己还没把它从云端/手机同步下来——
    # 把这个时间点亮出来，方便用户自行比对、判断是否需要去 PC 微信里先打开
    # 该对话触发同步。
    msgs = iter_csv_messages(out_dir, peer_wxid)
    if msgs:
        latest = max(msgs, key=lambda m: m["CreateTime"])["CreateTime"]
        print(f"[*] 该会话本地最新消息时间: {latest}")
        print("    若和手机上看到的最新消息对不上：请先在微信 PC 客户端打开该对话，"
              "等待其从手机/云端同步完成，再重新 refresh。")
    else:
        print("[!] 未导出到任何消息，请检查联系人 wxid 是否正确")
    return out_dir


# ------------------------- 从 CSV 导出语音 ------------------------- #

def _parse_row(row: list[str]) -> dict | None:
    if len(row) != len(CSV_HEADER) or row[0].strip() == "id":
        return None
    rec = {k: v for k, v in zip(CSV_HEADER, row)}
    for k in ("id", "MsgSvrID", "type_name", "is_sender", "talker", "room_name", "CreateTime"):
        rec[k] = rec[k].strip()
    return rec


def iter_csv_messages(csv_dir: Path, room_wxid: str) -> list[dict]:
    """读取目录下所有 .csv，筛出该会话（room_name）的行。"""
    rows: list[dict] = []
    for path in sorted(csv_dir.glob("*.csv")):
        if path.name.lower() == "users.json":
            continue
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                for line_no, row in enumerate(csv.reader(f), 1):
                    rec = _parse_row(row)
                    if rec and rec["room_name"] == room_wxid:
                        rows.append({"file": path.name, "line": line_no, **rec})
        except OSError as e:
            print(f"[-] 跳过无法读取的文件 {path}: {e}")
    return rows


def filter_voice_messages(
    messages: list[dict],
    room_wxid: str,
    since: datetime | None,
    speaker: str = "all",
) -> list[dict]:
    """从消息里筛出语音，按发言人与时间过滤，并按 MsgSvrID 去重。

    :param speaker: "all" / "peer"（仅对方）/ "self"（仅自己）
    """
    picked: list[dict] = []
    for m in messages:
        if m["type_name"] != "语音":
            continue
        if speaker == "peer" and (m["is_sender"] != "0" or m["talker"] != room_wxid):
            continue
        if speaker == "self" and m["is_sender"] != "1":
            continue
        try:
            ct = datetime.strptime(m["CreateTime"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            print(f"[!] 跳过非法时间 [{m['file']}:{m['line']}] {m['CreateTime']}")
            continue
        if since is not None and ct < since:
            continue
        picked.append(m)

    seen: set[str] = set()
    unique: list[dict] = []
    for m in sorted(picked, key=lambda x: x["CreateTime"]):
        if m["MsgSvrID"] in seen:
            continue
        seen.add(m["MsgSvrID"])
        unique.append(m)
    return unique


def export_voices(acct: Account, room_wxid: str, voices: list[dict], out_dir: Path) -> tuple[int, int]:
    """从 Media 表把语音导出为 WAV。返回 (成功, 失败) 数量。"""
    from pywxdump.db import DBHandler

    db = DBHandler(acct.db_config, my_wxid=acct.my_wxid)
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = fail = 0
    for m in voices:
        msg_svr_id = m["MsgSvrID"]
        rel = m["src"].replace("/", "\\").strip()
        if not rel:
            stamp = m["CreateTime"].replace(":", "-").replace(" ", "_")
            rel = os.path.join(room_wxid, f"{stamp}_{m['is_sender']}_{msg_svr_id}.wav")
        save_path = os.path.join(str(out_dir), rel)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        if os.path.isfile(save_path) and os.path.getsize(save_path) > 0:
            ok += 1
            continue

        with contextlib.redirect_stdout(io.StringIO()):
            wave_data = db.get_audio(msg_svr_id, is_play=False, is_wave=True, save_path=save_path, rate=24000)
        if wave_data and os.path.isfile(save_path):
            ok += 1
        else:
            fail += 1
            print(f"[-] 导出失败 MsgSvrID={msg_svr_id} ({m['CreateTime']}) — Media 中可能缺失")
    return ok, fail

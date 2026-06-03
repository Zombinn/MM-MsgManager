# -*- coding: utf-8 -*-
"""
从 wxdump 导出的 CSV 中筛选指定联系人的「语音」消息，按时间过滤后从 merge_all.db 的 Media 表导出为 WAV。

用法（在 PyWxDump 目录下）:
  .\\.venv\\Scripts\\python.exe scripts\\export_voices_from_csv.py

默认:
  - 聊天对象 wxid: wxid_ou5dxqdtzfcv12
  - CSV 目录: wxdump_work/export/zyb7809809/csv/wxid_ou5dxqdtzfcv12
  - 起始时间: 默认仅当年 4 月 1 日起；加 --all-time 则该会话 CSV 内全部语音
  - 输出目录: wxdump_work/export/zyb7809809/voices_...

依赖 conf_auto.json 中的 db_config（merge_all.db）与账号 my_wxid。
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent


def setup_env(root: Path) -> None:
    work = root / "wxdump_work"
    conf = work / "conf_auto.json"
    os.environ.setdefault("PYWXDUMP_WORK_PATH", str(work))
    os.environ.setdefault("PYWXDUMP_CONF_FILE", str(conf))
    os.environ.setdefault("PYWXDUMP_AUTO_SETTING", "auto_setting")


def load_account(root: Path) -> tuple[str, dict]:
    conf_path = root / "wxdump_work" / "conf_auto.json"
    with open(conf_path, encoding="utf-8") as f:
        conf = json.load(f)
    auto = conf["auto_setting"]["last"]
    if not auto:
        raise SystemExit("conf_auto.json 中 auto_setting.last 为空，请先初始化 wxdump")
    acct = conf[auto]
    return auto, acct["db_config"]


def parse_row(row: list[str]) -> dict | None:
    """标准导出 CSV: id,MsgSvrID,type_name,is_sender,talker,room_name,msg,src,CreateTime"""
    if len(row) != 9:
        return None
    if row[0].strip() == "id":
        return None
    return {
        "id": row[0].strip(),
        "MsgSvrID": row[1].strip(),
        "type_name": row[2].strip(),
        "is_sender": row[3].strip(),
        "talker": row[4].strip(),
        "room_name": row[5].strip(),
        "msg": row[6],
        "src": row[7],
        "CreateTime": row[8].strip(),
    }


def iter_csv_messages(csv_dir: Path, room_wxid: str) -> list[dict]:
    """读取目录下所有 .csv，筛出该会话（room_name）的行。"""
    rows: list[dict] = []
    for path in sorted(csv_dir.glob("*.csv")):
        if path.name.lower() == "users.json":
            continue
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                for line_no, row in enumerate(reader, 1):
                    rec = parse_row(row)
                    if not rec:
                        continue
                    if rec["room_name"] != room_wxid:
                        continue
                    rows.append({"file": path.name, "line": line_no, **rec})
        except OSError as e:
            print(f"[-] 跳过无法读取的文件 {path}: {e}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="从导出 CSV 筛选语音并导出 WAV")
    default_year = datetime.now().year
    parser.add_argument(
        "--room-wxid",
        default="wxid_ou5dxqdtzfcv12",
        help="会话 room_name（单聊一般为对方 wxid）",
    )
    parser.add_argument(
        "--csv-dir",
        type=Path,
        default=ROOT / "wxdump_work" / "export" / "zyb7809809" / "csv" / "wxid_ou5dxqdtzfcv12",
        help="聊天记录 CSV 所在目录",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="起始日期时间，如 2026-04-01；未指定且未加 --all-time 时默认为本年 4 月 1 日",
    )
    parser.add_argument(
        "--all-time",
        action="store_true",
        help="不限制时间，导出 CSV 中该会话的全部语音",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="输出目录；默认 wxdump_work/export/<账号>/voices_<room_wxid>_apr",
    )
    parser.add_argument(
        "--peer-only",
        action="store_true",
        help="仅导出对方发来的语音（is_sender=0，talker=room_wxid）",
    )
    parser.add_argument(
        "--self-only",
        action="store_true",
        help="仅导出自己发出的语音（is_sender=1）",
    )
    args = parser.parse_args()
    if args.peer_only and args.self_only:
        print("[-] --peer-only 与 --self-only 不能同时使用")
        return 1

    since_dt = None
    if args.all_time:
        if args.since:
            print("[!] 已指定 --all-time，忽略 --since")
    elif args.since:
        s = args.since.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                since_dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        else:
            print(f"[-] 无法解析 --since: {args.since}")
            return 1
    else:
        since_dt = datetime(default_year, 4, 1, 0, 0, 0)

    csv_dir: Path = args.csv_dir
    if not csv_dir.is_dir():
        print(f"[-] CSV 目录不存在: {csv_dir}")
        return 1

    setup_env(ROOT)
    sys.path.insert(0, str(ROOT))
    my_wxid, db_config = load_account(ROOT)
    merge_path = db_config.get("path", "")
    if not merge_path or not os.path.isfile(merge_path):
        print(f"[-] merge 数据库不可用: {merge_path}")
        return 1

    out_dir = args.out_dir
    if out_dir is None:
        safe_peer = "".join(c if c.isalnum() or c in "_-" else "_" for c in args.room_wxid)
        suffix = "all" if args.all_time else f"since_{since_dt.strftime('%Y%m%d')}"
        tag = "peer" if args.peer_only else ("self" if args.self_only else "allspk")
        out_dir = ROOT / "wxdump_work" / "export" / my_wxid / f"voices_{safe_peer}_{tag}_{suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)

    from pywxdump.db import DBHandler

    db = DBHandler(db_config, my_wxid=my_wxid)

    messages = iter_csv_messages(csv_dir, args.room_wxid)
    voice_candidates = []
    skipped_self = 0
    skipped_peer = 0
    for m in messages:
        if m["type_name"] != "语音":
            continue
        is_sender = m["is_sender"].strip()
        talker = m["talker"].strip()
        if args.peer_only:
            # 单聊：对方发来 is_sender=0 且 talker 为对方 wxid
            if is_sender != "0" or talker != args.room_wxid:
                skipped_self += 1
                continue
        elif args.self_only:
            if is_sender != "1":
                skipped_peer += 1
                continue
        try:
            ct = datetime.strptime(m["CreateTime"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            print(f"[!] 跳过非法时间 [{m['file']}:{m['line']}] {m['CreateTime']}")
            continue
        if since_dt is not None and ct < since_dt:
            continue
        voice_candidates.append(m)

    # 按 MsgSvrID 去重（多文件可能有重叠）
    seen: set[str] = set()
    unique = []
    for m in sorted(voice_candidates, key=lambda x: x["CreateTime"]):
        sid = m["MsgSvrID"]
        if sid in seen:
            continue
        seen.add(sid)
        unique.append(m)

    print(f"[*] merge db: {merge_path}")
    print(f"[*] 账号 my_wxid: {my_wxid}")
    print(f"[*] 会话 room_name: {args.room_wxid}")
    if args.peer_only:
        print("[*] 筛选: 仅对方语音 (--peer-only)")
    elif args.self_only:
        print("[*] 筛选: 仅自己语音 (--self-only)")
    else:
        print("[*] 筛选: 会话内全部语音（含自己与对方）")
    if args.peer_only and skipped_self:
        print(f"[*] 已跳过自己/非对方语音: {skipped_self} 条")
    if args.self_only and skipped_peer:
        print(f"[*] 已跳过对方语音: {skipped_peer} 条")
    print(f"[*] 时间范围: {'全部（CSV 内）' if since_dt is None else f'>= {since_dt}'}")
    print(f"[*] 待导出语音条数: {len(unique)}")
    print(f"[*] 输出目录: {out_dir}")

    ok, fail = 0, 0
    for m in unique:
        msg_svr_id = m["MsgSvrID"]
        # 与 /api/rs/audio 一致：按 src 相对路径落盘，便于对照 Web
        rel = m["src"].replace("/", "\\").strip()
        if not rel:
            rel = os.path.join(args.room_wxid, f"{m['CreateTime'].replace(':', '-').replace(' ', '_')}_{m['is_sender']}_{msg_svr_id}.wav")
        save_path = os.path.join(str(out_dir), rel)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        if os.path.isfile(save_path) and os.path.getsize(save_path) > 0:
            ok += 1
            continue

        with contextlib.redirect_stdout(io.StringIO()):
            wave_data = db.get_audio(
                msg_svr_id, is_play=False, is_wave=True, save_path=save_path, rate=24000
            )
        if wave_data and os.path.isfile(save_path):
            ok += 1
        else:
            fail += 1
            print(f"[-] 导出失败 MsgSvrID={msg_svr_id} ({m['CreateTime']}) — Media 中可能缺失")

    print(f"[+] 成功: {ok}, 失败: {fail}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

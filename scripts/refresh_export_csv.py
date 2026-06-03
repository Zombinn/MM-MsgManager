# -*- coding: utf-8 -*-
"""
微信有新消息后：合并 PC 端 MSG 分库到 merge_all.db，并重新导出指定联系人的 CSV。

用法:
  python scripts/refresh_export_csv.py
  python scripts/refresh_export_csv.py --peer-wxid wxid_ou5dxqdtzfcv12
  python scripts/refresh_export_csv.py --merge-only
  python scripts/refresh_export_csv.py --export-only
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK_PATH = ROOT / "wxdump_work"
CONF_PATH = WORK_PATH / "conf_auto.json"


def setup_env() -> None:
    os.environ["PYWXDUMP_WORK_PATH"] = str(WORK_PATH)
    os.environ["PYWXDUMP_CONF_FILE"] = str(CONF_PATH)
    os.environ["PYWXDUMP_AUTO_SETTING"] = "auto_setting"


def load_conf() -> tuple[str, dict]:
    with open(CONF_PATH, encoding="utf-8") as f:
        conf = json.load(f)
    acct_key = conf["auto_setting"]["last"]
    return acct_key, conf[acct_key]


def warn_wal_files(wx_path: str) -> bool:
    """微信运行时新消息常在 *.db-wal，未退出时解密不到最新记录。"""
    multi = os.path.join(wx_path, "Msg", "Multi")
    found = False
    for i in range(16):
        wal = os.path.join(multi, f"MSG{i}.db-wal")
        if os.path.isfile(wal) and os.path.getsize(wal) > 65536:
            print(f"[!] 检测到 {wal} ({os.path.getsize(wal)} 字节)")
            print("    新聊天记录可能还在 WAL 中。请先完全退出微信 PC 版（含托盘），再重新运行本脚本。")
            found = True
    return found


def merge_all_msg_shards(wx_path: str, key: str, merge_path: str) -> int:
    from pywxdump import batch_decrypt, merge_db

    multi = os.path.join(wx_path, "Msg", "Multi")
    dec_base = WORK_PATH / "decrypted_refresh"
    if dec_base.exists():
        shutil.rmtree(dec_base)
    dec_base.mkdir(parents=True, exist_ok=True)

    merged = 0
    failed = 0
    for i in range(16):
        enc = os.path.join(multi, f"MSG{i}.db")
        if not os.path.isfile(enc):
            continue
        sub = dec_base / f"MSG{i}"
        sub.mkdir(parents=True, exist_ok=True)
        ok, ret = batch_decrypt(key, enc, str(sub), is_print=False)
        if not ok:
            print(f"[-] 解密失败 MSG{i}（微信是否仍开着？）: {ret}")
            failed += 1
            continue
        de = sub / f"de_MSG{i}.db"
        if not de.is_file():
            print(f"[-] 未找到解密文件: {de}")
            failed += 1
            continue
        merge_db([{"db_path": enc, "de_path": str(de)}], merge_path, is_merge_data=True)
        merged += 1
        print(f"[+] 已合并 MSG{i}.db")

    if dec_base.exists():
        shutil.rmtree(dec_base, ignore_errors=True)
    if failed:
        print(f"[!] {failed} 个分库解密失败，合并结果可能缺少最新消息")
    return merged


def clean_old_csv(out_dir: Path, peer_wxid: str) -> None:
    """删除分页 CSV 与 users.json，保留 new_history.csv 等手工文件。"""
    if not out_dir.is_dir():
        return
    for p in out_dir.glob(f"{peer_wxid}_*.csv"):
        p.unlink()
        print(f"[*] 删除旧文件: {p.name}")
    users = out_dir / "users.json"
    if users.is_file():
        users.unlink()
        print("[*] 删除旧 users.json")


def export_peer_csv(peer_wxid: str, my_wxid: str, db_config: dict) -> None:
    from pywxdump.api.export.exportCSV import export_csv

    out_dir = WORK_PATH / "export" / my_wxid / "csv" / peer_wxid
    out_dir.mkdir(parents=True, exist_ok=True)
    ok, ret = export_csv(peer_wxid, str(out_dir), db_config, my_wxid=my_wxid)
    if not ok:
        raise SystemExit(f"[-] CSV 导出失败: {ret}")
    print(f"[+] {ret}")


def main() -> int:
    parser = argparse.ArgumentParser(description="合并最新微信库并重新导出 CSV")
    parser.add_argument("--peer-wxid", default="wxid_ou5dxqdtzfcv12", help="要导出的联系人 wxid")
    parser.add_argument("--merge-only", action="store_true", help="只合并数据库，不导出 CSV")
    parser.add_argument("--export-only", action="store_true", help="只导出 CSV（不合并）")
    args = parser.parse_args()

    setup_env()
    sys.path.insert(0, str(ROOT))
    my_wxid, acct = load_conf()
    merge_path = acct["merge_path"]
    wx_path = acct["wx_path"]
    key = acct["key"]
    db_config = acct["db_config"]

    if not os.path.isfile(merge_path):
        print(f"[-] merge_all.db 不存在: {merge_path}")
        return 1

    if not args.export_only:
        if warn_wal_files(wx_path):
            print("[*] 仍将尝试合并；若 CSV 仍缺新消息，请退出微信后重试。")
        print("[*] 正在合并 Msg/Multi/MSG*.db -> merge_all.db ...")
        n = merge_all_msg_shards(wx_path, key, merge_path)
        print(f"[+] 共处理 {n} 个 MSG 分库")

    if not args.merge_only:
        out_dir = WORK_PATH / "export" / my_wxid / "csv" / args.peer_wxid
        clean_old_csv(out_dir, args.peer_wxid)
        print(f"[*] 导出 CSV: {args.peer_wxid}")
        export_peer_csv(args.peer_wxid, my_wxid, db_config)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

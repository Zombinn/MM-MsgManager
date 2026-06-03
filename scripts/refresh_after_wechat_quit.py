# -*- coding: utf-8 -*-
"""
等待 WeChat.exe 退出后，自动合并 MSG 并重新导出 CSV。
（微信开着时新消息在 MSG*.db-wal，解密主库读不到 PC 里能看到的最新聊天）

用法:
  python scripts/refresh_after_wechat_quit.py
  python scripts/refresh_after_wechat_quit.py --peer-wxid wxid_ou5dxqdtzfcv12 --timeout 600
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def wechat_running() -> bool:
    for name in ("WeChat.exe", "Weixin.exe"):
        r = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}"],
            capture_output=True,
            text=True,
            encoding="gbk",
            errors="replace",
        )
        if name.lower() in r.stdout.lower() and "没有运行的任务" not in r.stdout and "No tasks" not in r.stdout:
            if "PID" in r.stdout or "映" in r.stdout:
                lines = [ln for ln in r.stdout.splitlines() if name.lower() in ln.lower()]
                if lines:
                    return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--peer-wxid", default="wxid_ou5dxqdtzfcv12")
    ap.add_argument("--timeout", type=int, default=600, help="最多等待秒数")
    ap.add_argument("--poll", type=float, default=2.0)
    args = ap.parse_args()

    print("[*] 请先完全退出微信（含右下角托盘）。")
    print("[*] 等待 WeChat 进程结束…")
    t0 = time.time()
    while wechat_running():
        if time.time() - t0 > args.timeout:
            print("[-] 超时：微信仍在运行，无法合并 WAL 中的新消息")
            return 1
        time.sleep(args.poll)

    print("[+] 微信已退出，开始刷新 merge + CSV …")
    time.sleep(2)
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "refresh_export_csv.py"),
            "--peer-wxid",
            args.peer_wxid,
        ],
        cwd=str(ROOT),
    )
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())

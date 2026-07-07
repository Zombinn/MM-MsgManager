# -*- coding: utf-8 -*-
"""微信进程/WAL 相关的小工具。"""
from __future__ import annotations

import os
import subprocess
import time

WECHAT_PROCESSES = ("WeChat.exe", "Weixin.exe")


def wechat_running() -> bool:
    """检测微信 PC 版是否仍在运行。"""
    for name in WECHAT_PROCESSES:
        r = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}"],
            capture_output=True,
            text=True,
            encoding="gbk",
            errors="replace",
        )
        out = r.stdout or ""
        if name.lower() in out.lower() and "没有运行的任务" not in out and "No tasks" not in out:
            if any(name.lower() in ln.lower() for ln in out.splitlines()):
                return True
    return False


def wait_for_exit(timeout: int = 600, poll: float = 2.0) -> bool:
    """等待微信退出。返回 True 表示已退出，False 表示超时。"""
    t0 = time.time()
    while wechat_running():
        if time.time() - t0 > timeout:
            return False
        time.sleep(poll)
    return True


def warn_wal_files(wx_path: str) -> bool:
    """微信运行时新消息常滞留在 MSG*.db-wal，此时解密主库读不到最新记录。

    返回 True 表示检测到较大的 WAL 文件（提示用户先退出微信）。
    """
    multi = os.path.join(wx_path, "Msg", "Multi")
    found = False
    for i in range(16):
        wal = os.path.join(multi, f"MSG{i}.db-wal")
        if os.path.isfile(wal) and os.path.getsize(wal) > 65536:
            print(f"[!] 检测到 {wal} ({os.path.getsize(wal)} 字节)")
            print("    新聊天记录可能还在 WAL 中。请先完全退出微信 PC 版（含托盘），再重试。")
            found = True
    return found

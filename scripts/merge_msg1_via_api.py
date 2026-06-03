# -*- coding: utf-8 -*-
"""通过 PyWxDump 本地 API 逻辑：解密 MSG1.db 并合并到 merge_all.db"""
import json
import os
import sys

# 工作目录与 conf（与 wxdump ui 一致）
WORK_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "wxdump_work")
os.environ["PYWXDUMP_WORK_PATH"] = WORK_PATH
os.environ["PYWXDUMP_CONF_FILE"] = os.path.join(WORK_PATH, "conf_auto.json")
os.environ["PYWXDUMP_AUTO_SETTING"] = "auto_setting"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pywxdump import batch_decrypt, merge_db

CONF_PATH = os.environ["PYWXDUMP_CONF_FILE"]
MSG1_ENC = r"C:\Users\Zombin\Documents\WeChat Files\zyb7809809\Msg\Multi\MSG1.db"
DEC_DIR = os.path.join(WORK_PATH, "decrypted_msg1")


def load_conf():
    with open(CONF_PATH, encoding="utf-8") as f:
        return json.load(f)


def main():
    conf = load_conf()
    wxid = conf["auto_setting"]["last"]
    account = conf[wxid]
    key = account["key"]
    merge_path = account["merge_path"]

    if not os.path.isfile(MSG1_ENC):
        print(f"[-] 源库不存在: {MSG1_ENC}")
        return 1
    if not os.path.isfile(merge_path):
        print(f"[-] merge_all.db 不存在: {merge_path}")
        return 1

    os.makedirs(DEC_DIR, exist_ok=True)
    for name in os.listdir(DEC_DIR):
        p = os.path.join(DEC_DIR, name)
        if os.path.isfile(p):
            os.remove(p)

    print("[*] 1/2 解密 MSG1.db ...")
    ok, ret = batch_decrypt(key, MSG1_ENC, DEC_DIR, is_print=True)
    if not ok:
        print(f"[-] 解密失败: {ret}")
        return 1

    de_path = os.path.join(DEC_DIR, "de_MSG1.db")
    if not os.path.isfile(de_path):
        print(f"[-] 未找到解密文件: {de_path}")
        return 1

    print("[*] 2/2 合并到 merge_all.db ...")
    # db_path 用加密库路径，与 sync_log 一致，仅合并新增行
    result = merge_db(
        [{"db_path": MSG1_ENC, "de_path": de_path}],
        merge_path,
        is_merge_data=True,
    )
    print(f"[+] 完成: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

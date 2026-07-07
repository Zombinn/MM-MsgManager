# -*- coding: utf-8 -*-
"""运行上下文与账户解析。

替代原先散落在各脚本里重复的 setup_env / load_conf / load_account，
并把个人默认值（如常用联系人 wxid）从源码挪到可选配置文件
``wxdump_work/wxtools.json``，避免硬编码。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

# 仓库根目录（wxtools 的上一级）
ROOT = Path(__file__).resolve().parent.parent
WORK_PATH = ROOT / "wxdump_work"
CONF_PATH = WORK_PATH / "conf_auto.json"
DEFAULTS_PATH = WORK_PATH / "wxtools.json"
AUTO_SETTING = "auto_setting"


def setup_env() -> None:
    """设置 pywxdump 读取 conf 所需的环境变量。

    必须在 import pywxdump 的 conf 相关逻辑之前调用（幂等）。
    """
    os.environ.setdefault("PYWXDUMP_WORK_PATH", str(WORK_PATH))
    os.environ.setdefault("PYWXDUMP_CONF_FILE", str(CONF_PATH))
    os.environ.setdefault("PYWXDUMP_AUTO_SETTING", AUTO_SETTING)


@dataclass
class Account:
    """当前登录账号在 conf_auto.json 中的关键信息。"""

    my_wxid: str
    key: str
    wx_path: str
    merge_path: str
    db_config: dict

    @property
    def export_dir(self) -> Path:
        return WORK_PATH / "export" / self.my_wxid

    def csv_dir(self, peer_wxid: str) -> Path:
        return self.export_dir / "csv" / peer_wxid


def _read_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_account() -> Account:
    """从 conf_auto.json 读取当前（last）账号信息。"""
    if not CONF_PATH.is_file():
        raise SystemExit(
            f"[-] 未找到 {CONF_PATH}\n    请先运行 `wxdump ui` 完成一次初始化。"
        )
    conf = _read_json(CONF_PATH)
    my_wxid = conf.get(AUTO_SETTING, {}).get("last", "")
    if not my_wxid:
        raise SystemExit("[-] conf_auto.json 中 auto_setting.last 为空，请先初始化 wxdump")
    acct = conf.get(my_wxid, {})
    if not acct:
        raise SystemExit(f"[-] conf_auto.json 中缺少账号 {my_wxid} 的配置")
    return Account(
        my_wxid=my_wxid,
        key=acct.get("key", ""),
        wx_path=acct.get("wx_path", ""),
        merge_path=acct.get("merge_path", ""),
        db_config=acct.get("db_config", {}),
    )


def load_defaults() -> dict:
    """读取个人默认值（可选）。不存在则返回空 dict。"""
    if DEFAULTS_PATH.is_file():
        try:
            return _read_json(DEFAULTS_PATH)
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def resolve_peer(cli_value: str | None) -> str:
    """按优先级解析联系人 wxid：命令行 > 环境变量 > 默认配置文件。"""
    if cli_value:
        return cli_value
    env = os.environ.get("WXTOOLS_PEER")
    if env:
        return env
    default = load_defaults().get("peer_wxid")
    if default:
        return default
    raise SystemExit(
        "[-] 未指定联系人 wxid。请用 --peer-wxid 传入，"
        f"或在 {DEFAULTS_PATH} 写入 {{\"peer_wxid\": \"wxid_xxx\"}}"
    )

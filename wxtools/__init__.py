# -*- coding: utf-8 -*-
"""wxtools —— MM-MsgManager 的个人工作流工具集。

把原先 scripts/ 下 8 个独立脚本收敛为一个包 + 一个统一 CLI：
  - context : 运行上下文与账户解析
  - wechat  : 微信进程 / WAL 检测
  - pipeline: 解密合并、导出 CSV、导出语音
  - audio   : WAV 拼接（纯标准库）
  - media   : 视频取/换音轨、音色对比（惰性依赖 ffmpeg / librosa）
  - cli     : 统一命令行入口
"""
from __future__ import annotations

__all__ = ["context", "wechat", "pipeline", "audio", "media", "cli"]

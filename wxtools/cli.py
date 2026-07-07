# -*- coding: utf-8 -*-
"""wxtools 统一命令行入口。

一条命令覆盖原先 scripts/ 下 8 个脚本的能力：

  python -m wxtools init                首次初始化账号（扫描微信/解密/生成 merge_all.db，无需网页前端）
  python -m wxtools accounts            列出当前登录的微信账号
  python -m wxtools refresh            合并最新 MSG 分库并导出联系人 CSV（默认会先尝试实时合并）
  python -m wxtools wait-refresh       等微信退出后再 refresh（读取 WAL 中的新消息）
  python -m wxtools realtime           微信开着也能合并最新消息（无需退出，读取运行中进程数据）
  python -m wxtools voices             从 CSV 筛语音并导出 WAV
  python -m wxtools concat             按时间拼接 WAV 为一条长音频
  python -m wxtools video-extract      从视频提取音轨（ffmpeg）
  python -m wxtools video-replace      替换视频音轨（ffmpeg）
  python -m wxtools timbre             对比两段音频的音色并出图（librosa）
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

from . import audio, context, media, pipeline, wechat


# ------------------------- 首次初始化 ------------------------- #

def _cmd_accounts(args) -> int:
    accounts = pipeline.list_wx_accounts()
    if not accounts:
        print("[-] 未扫描到可用的微信账号（微信是否已登录？当前版本是否受支持？）")
        return 1
    for i, a in enumerate(accounts):
        print(f"[{i}] {a.get('nickname') or '(未知昵称)'} / {a['wxid']}  wx_dir={a['wx_dir']}")
    return 0


def _cmd_init(args) -> int:
    pipeline.init_account(index=args.index)
    return 0


# ------------------------- 微信数据管线 ------------------------- #

def _cmd_refresh(args) -> int:
    context.setup_env()
    acct = context.load_account()
    # merge-only 不涉及具体联系人，避免强制要求配置默认 peer_wxid
    peer = None if args.merge_only else context.resolve_peer(args.peer_wxid)
    if not os.path.isfile(acct.merge_path):
        print(f"[-] merge_all.db 不存在: {acct.merge_path}")
        return 1

    if not args.export_only:
        if not args.no_realtime:
            print("[*] 尝试实时合并（微信开着也可以，读取运行中进程数据）...")
            ok, msg = pipeline.merge_realtime(acct)
            print(f"[+] 实时合并成功: {msg}" if ok else
                  f"[!] 实时合并跳过/失败（不影响后续常规合并）: {msg}")
        if wechat.warn_wal_files(acct.wx_path):
            print("[*] 仍将尝试合并；若 CSV 仍缺新消息，请退出微信后重试（wxtools wait-refresh）。")
        shards = args.shards
        print("[*] 正在合并 Msg/Multi/MSG*.db -> merge_all.db ...")
        n = pipeline.merge_msg_shards(acct, shards)
        print(f"[+] 共处理 {n} 个 MSG 分库")

    if not args.merge_only:
        print(f"[*] 导出 CSV: {peer}")
        pipeline.export_contact_csv(acct, peer)
    return 0


def _cmd_realtime(args) -> int:
    context.setup_env()
    acct = context.load_account()
    print("[*] 实时合并中（微信可以继续开着）...")
    ok, msg = pipeline.merge_realtime(acct)
    if ok:
        print(f"[+] 实时合并成功: {msg}")
        return 0
    print(f"[-] 实时合并失败: {msg}")
    return 1


def _cmd_wait_refresh(args) -> int:
    print("[*] 请先完全退出微信（含右下角托盘），等待 WeChat 进程结束…")
    if not wechat.wait_for_exit(timeout=args.timeout, poll=args.poll):
        print("[-] 超时：微信仍在运行，无法合并 WAL 中的新消息")
        return 1
    print("[+] 微信已退出，开始刷新 merge + CSV …")
    return _cmd_refresh(args)


def _parse_since(args) -> datetime | None:
    if args.all_time:
        if args.since:
            print("[!] 已指定 --all-time，忽略 --since")
        return None
    if args.since:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(args.since.strip(), fmt)
            except ValueError:
                continue
        raise SystemExit(f"[-] 无法解析 --since: {args.since}")
    return datetime(datetime.now().year, 4, 1)  # 默认本年 4 月 1 日起


def _cmd_voices(args) -> int:
    context.setup_env()
    acct = context.load_account()
    peer = context.resolve_peer(args.peer_wxid)
    since = _parse_since(args)

    csv_dir = args.csv_dir or acct.csv_dir(peer)
    if not csv_dir.is_dir():
        print(f"[-] CSV 目录不存在: {csv_dir}")
        return 1
    merge_path = acct.db_config.get("path", "")
    if not merge_path or not os.path.isfile(merge_path):
        print(f"[-] merge 数据库不可用: {merge_path}")
        return 1

    out_dir = args.out_dir
    if out_dir is None:
        safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in peer)
        suffix = "all" if since is None else f"since_{since.strftime('%Y%m%d')}"
        out_dir = acct.export_dir / f"voices_{safe}_{args.speaker}_{suffix}"

    messages = pipeline.iter_csv_messages(csv_dir, peer)
    voices = pipeline.filter_voice_messages(messages, peer, since, args.speaker)

    print(f"[*] merge db: {merge_path}")
    print(f"[*] 账号: {acct.my_wxid} | 会话: {peer} | 发言人: {args.speaker}")
    print(f"[*] 时间范围: {'全部（CSV 内）' if since is None else f'>= {since}'}")
    print(f"[*] 待导出语音条数: {len(voices)}")
    print(f"[*] 输出目录: {out_dir}")

    ok, fail = pipeline.export_voices(acct, peer, voices, out_dir)
    print(f"[+] 成功: {ok}, 失败: {fail}")
    return 0 if fail == 0 else 2


# ------------------------- 音视频工具 ------------------------- #

def _cmd_concat(args) -> int:
    if not args.input.is_dir():
        print(f"[-] 目录不存在: {args.input}")
        return 1
    try:
        n, dur = audio.concat_wavs(args.input, args.output, args.gap_ms)
    except (FileNotFoundError, ValueError) as e:
        print(f"[-] {e}")
        return 1
    print(f"[+] 共 {n} 条 WAV，时长约 {dur:.1f} 秒 -> {args.output.resolve()}")
    return 0


def _cmd_video_extract(args) -> int:
    videos: list[Path] = args.video
    ext = "m4a" if args.format in ("m4a", "aac") else "wav"
    if len(videos) > 1 and args.output:
        print("[!] 批量模式忽略 -o，每个视频单独输出到同目录 *_audio.*")
    for v in videos:
        out = args.output if len(videos) == 1 and args.output else v.with_name(f"{v.stem}_audio.{ext}")
        media.extract_video_audio(v, out, args.format)
        print(f"[+] {v.name} -> {out}")
    return 0


def _cmd_video_replace(args) -> int:
    out = args.output or args.video.with_name(f"{args.video.stem}_newaudio{args.video.suffix}")
    media.replace_video_audio(args.video, args.audio, out, args.mode, args.audio_bitrate)
    print(f"[+] 已写入: {out.resolve()}")
    return 0


def _cmd_ui(args) -> int:
    from . import webui
    webui.start(port=args.port, open_browser=not args.no_browser)
    return 0


def _cmd_timbre(args) -> int:
    media.compare_timbre(
        Path(args.audio1).expanduser().resolve(),
        Path(args.audio2).expanduser().resolve(),
        Path(args.output).expanduser().resolve(),
        Path(args.json_out).expanduser().resolve() if args.json_out else None,
        sr=args.sr, n_mfcc=args.n_mfcc, max_seconds=args.max_seconds,
    )
    print(f"[+] 对比图已生成: {args.output}")
    return 0


# ------------------------- 参数解析 ------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wxtools", description="微信聊天数据 / 音视频工作流工具集")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser("accounts", help="列出当前登录的微信账号")
    p.set_defaults(func=_cmd_accounts)

    p = sub.add_parser("init", help="首次初始化账号（扫描/解密/生成 merge_all.db）")
    p.add_argument("--index", type=int, default=None, help="多账号同时登录时选择第几个（0-based）")
    p.set_defaults(func=_cmd_init)

    def add_refresh_args(p):
        p.add_argument("--peer-wxid", default=None, help="联系人 wxid（默认取 wxtools.json / 环境变量）")
        p.add_argument("--no-realtime", action="store_true", help="跳过实时合并的 best-effort 尝试")

    p = sub.add_parser("refresh", help="合并最新 MSG 分库并导出联系人 CSV")
    add_refresh_args(p)
    p.add_argument("--merge-only", action="store_true", help="只合并数据库，不导出 CSV")
    p.add_argument("--export-only", action="store_true", help="只导出 CSV（不合并）")
    p.add_argument("--shards", type=int, nargs="*", default=None, help="仅合并指定分库序号，如 --shards 1")
    p.set_defaults(func=_cmd_refresh)

    p = sub.add_parser("wait-refresh", help="等微信退出后再 refresh")
    add_refresh_args(p)
    p.add_argument("--merge-only", action="store_true")
    p.add_argument("--export-only", action="store_true")
    p.add_argument("--shards", type=int, nargs="*", default=None)
    p.add_argument("--timeout", type=int, default=600, help="最多等待秒数")
    p.add_argument("--poll", type=float, default=2.0)
    p.set_defaults(func=_cmd_wait_refresh)

    p = sub.add_parser("realtime", help="微信开着也能合并最新消息（无需退出微信）")
    p.set_defaults(func=_cmd_realtime)

    p = sub.add_parser("voices", help="从 CSV 筛语音并导出 WAV")
    add_refresh_args(p)
    p.add_argument("--csv-dir", type=Path, default=None, help="CSV 目录（默认按账号/联系人推导）")
    p.add_argument("--since", default=None, help="起始日期，如 2026-04-01；默认本年 4 月 1 日")
    p.add_argument("--all-time", action="store_true", help="不限制时间")
    p.add_argument("--speaker", choices=("all", "peer", "self"), default="all", help="导出哪一方的语音")
    p.add_argument("--out-dir", type=Path, default=None, help="输出目录")
    p.set_defaults(func=_cmd_voices)

    p = sub.add_parser("ui", help="启动简易本地控制台（Web 界面）")
    p.add_argument("-p", "--port", type=int, default=5001, help="端口，默认 5001")
    p.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    p.set_defaults(func=_cmd_ui)

    p = sub.add_parser("concat", help="按时间拼接 WAV 为一条")
    p.add_argument("-i", "--input", type=Path, required=True, help="语音 WAV 根目录")
    p.add_argument("-o", "--output", type=Path, required=True, help="合并后的 .wav 路径")
    p.add_argument("--gap-ms", type=int, default=0, help="每条之间静音毫秒数")
    p.set_defaults(func=_cmd_concat)

    p = sub.add_parser("video-extract", help="从视频提取音轨（ffmpeg）")
    p.add_argument("-v", "--video", type=Path, action="append", required=True, help="输入视频，可重复")
    p.add_argument("-o", "--output", type=Path, default=None, help="单文件时指定输出")
    p.add_argument("--format", choices=("wav", "m4a", "aac"), default="wav")
    p.set_defaults(func=_cmd_video_extract)

    p = sub.add_parser("video-replace", help="替换视频音轨（ffmpeg）")
    p.add_argument("-v", "--video", type=Path, required=True)
    p.add_argument("-a", "--audio", type=Path, required=True)
    p.add_argument("-o", "--output", type=Path, default=None)
    p.add_argument("--mode", choices=("video", "shortest"), default="video")
    p.add_argument("--audio-bitrate", default="192k")
    p.set_defaults(func=_cmd_video_replace)

    p = sub.add_parser("timbre", help="对比两段音频音色并出图（librosa）")
    p.add_argument("-a1", "--audio1", required=True)
    p.add_argument("-a2", "--audio2", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--json-out", default="")
    p.add_argument("--sr", type=int, default=22050)
    p.add_argument("--n-mfcc", type=int, default=13)
    p.add_argument("--max-seconds", type=float, default=60.0)
    p.set_defaults(func=_cmd_timbre)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

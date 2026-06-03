#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将视频的音轨替换为指定的音频文件（依赖系统 PATH 中的 ffmpeg / ffprobe）。

默认行为：输出时长与视频一致；音频长于视频则截断，短于视频则末尾补静音。

示例:
  python scripts/replace_video_audio.py -v input.mp4 -a narration.wav -o output.mp4
  python scripts/replace_video_audio.py -v clip.mp4 -a bgm.mp3 -o clip_new.mp4 --mode shortest

模式:
  video   （默认）按视频时长处理音频（截断 / 末尾静音补齐）
  shortest 取视频与音频中较短的一方作为输出时长（不传 whole_dur 的简单拼接）

若未指定 -o，则在视频同目录生成 <原名>_newaudio.<扩展名>
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit("[-] 请先安装 FFmpeg，并确保 ffmpeg、ffprobe 已在 PATH 中。")


def probe_duration_seconds(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit(f"[-] ffprobe 失败: {path}\n{r.stderr}")
    try:
        dur = float(json.loads(r.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError) as e:
        sys.exit(f"[-] 无法解析时长: {path} ({e})")
    return dur


def replace_audio(
    video: Path,
    audio: Path,
    output: Path,
    mode: str,
    audio_bitrate: str,
) -> None:
    video = video.resolve()
    audio = audio.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    if mode == "shortest":
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-shortest",
            str(output),
        ]
    else:
        vd = probe_duration_seconds(video)
        # 截断过长音频，过短则末尾补静音至视频时长；复用原视频码流
        filt = f"[1:a]atrim=end={vd},asetpts=PTS-STARTPTS,apad=whole_dur={vd}[outa]"
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-filter_complex",
            filt,
            "-map",
            "0:v:0",
            "-map",
            "[outa]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-t",
            str(vd),
            str(output),
        ]

    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.stderr.write(r.stderr or r.stdout or "")
        sys.exit(f"[-] ffmpeg 失败 (exit {r.returncode})")


def main() -> int:
    parser = argparse.ArgumentParser(description="用外部音频替换视频的音轨（需 FFmpeg）")
    parser.add_argument("-v", "--video", type=Path, required=True, help="输入视频路径")
    parser.add_argument("-a", "--audio", type=Path, required=True, help="输入音频路径（wav/mp3/aac 等）")
    parser.add_argument("-o", "--output", type=Path, default=None, help="输出视频路径（默认与视频同目录 *_newaudio）")
    parser.add_argument(
        "--mode",
        choices=("video", "shortest"),
        default="video",
        help="video=输出与视频等长；shortest=较短流决定时长",
    )
    parser.add_argument("--audio-bitrate", default="192k", help="AAC 码率，默认 192k")

    args = parser.parse_args()
    require_ffmpeg()

    video, audio = args.video, args.audio
    if not video.is_file():
        sys.exit(f"[-] 视频不存在: {video}")
    if not audio.is_file():
        sys.exit(f"[-] 音频不存在: {audio}")

    out = args.output
    if out is None:
        out = video.with_name(f"{video.stem}_newaudio{video.suffix}")

    replace_audio(video, audio, out, args.mode, args.audio_bitrate)
    print(f"[+] 已写入: {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

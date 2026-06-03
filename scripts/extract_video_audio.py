#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从视频中分离/提取音轨（依赖 ffmpeg / ffprobe）。

示例:
  python scripts/extract_video_audio.py -v input.mp4
  python scripts/extract_video_audio.py -v a.mp4 -v b.mp4 -o out.wav
  python scripts/extract_video_audio.py -v a.mp4 --format m4a

未指定 -o 时，输出为与视频同目录的 <原名>_audio.<扩展名>
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def require_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        sys.exit("[-] 请先安装 FFmpeg，并确保 ffmpeg 在 PATH 中。")


def default_output(video: Path, fmt: str) -> Path:
    return video.with_name(f"{video.stem}_audio.{fmt}")


def extract_one(video: Path, output: Path, fmt: str) -> None:
    video = video.resolve()
    output = output.resolve()
    if not video.is_file():
        sys.exit(f"[-] 视频不存在: {video}")
    output.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "wav":
        cmd = [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(video),
            "-vn",
            "-acodec", "pcm_s16le",
            str(output),
        ]
    elif fmt in ("m4a", "aac"):
        cmd = [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(video),
            "-vn",
            "-acodec", "copy",
            str(output),
        ]
    else:
        sys.exit(f"[-] 不支持的格式: {fmt}，请用 wav 或 m4a")

    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.stderr.write(r.stderr or r.stdout or "")
        sys.exit(f"[-] ffmpeg 失败: {video} (exit {r.returncode})")


def main() -> int:
    parser = argparse.ArgumentParser(description="从视频提取音轨")
    parser.add_argument("-v", "--video", type=Path, action="append", required=True, help="输入视频，可重复")
    parser.add_argument("-o", "--output", type=Path, default=None, help="单文件时指定输出；多文件时忽略")
    parser.add_argument("--format", choices=("wav", "m4a", "aac"), default="wav", help="输出格式，默认 wav")
    args = parser.parse_args()
    require_ffmpeg()

    videos = args.video
    ext = "m4a" if args.format in ("m4a", "aac") else "wav"

    if len(videos) > 1 and args.output:
        print("[!] 批量模式忽略 -o，每个视频单独输出到同目录 *_audio.*")

    for video in videos:
        out = args.output if len(videos) == 1 and args.output else default_output(video, ext)
        extract_one(video, out, args.format)
        print(f"[+] {video.name} -> {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

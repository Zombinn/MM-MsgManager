# -*- coding: utf-8 -*-
"""
将目录下（递归）的微信导出 WAV 按聊天时间顺序拼接成一条长音频。

导出格式为 mono / 16-bit PCM / 24000 Hz（与 PyWxDump silk 解码一致）。

用法:
  cd PyWxDump
  .\\.venv\\Scripts\\python.exe scripts\\concat_voice_wavs.py ^
    --input wxdump_work/export/zyb7809809/voices_wxid_ou5dxqdtzfcv12_since_20260401 ^
    --output wxdump_work/export/zyb7809809/all_voices_merged.wav

可选 --gap-ms 在每条语音之间插入静音。
"""
from __future__ import annotations

import argparse
import re
import wave
from pathlib import Path


def wav_sort_key(p: Path) -> tuple:
    """文件名中含 YYYY-MM-DD_HH-MM-SS 则按时间排序。"""
    m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})", p.name)
    if m:
        return (m.group(1), m.group(2), p.name)
    return ("9999", "99-99-99", str(p))


def collect_wavs(root: Path) -> list[Path]:
    files = [p for p in root.rglob("*.wav") if p.is_file()]
    return sorted(files, key=wav_sort_key)


def main() -> int:
    ap = argparse.ArgumentParser(description="递归合并目录下所有 WAV 为一条")
    ap.add_argument("--input", "-i", type=Path, required=True, help="语音 WAV 根目录")
    ap.add_argument("--output", "-o", type=Path, required=True, help="合并后的 .wav 路径")
    ap.add_argument("--gap-ms", type=int, default=0, help="每条之间静音毫秒数，默认 0")
    args = ap.parse_args()

    root: Path = args.input
    if not root.is_dir():
        print(f"[-] 目录不存在: {root}")
        return 1

    wavs = collect_wavs(root)
    if not wavs:
        print(f"[-] 未找到 wav: {root}")
        return 1

    merge_path: Path = args.output
    merge_path.parent.mkdir(parents=True, exist_ok=True)

    chunks: list[bytes] = []
    ch = sw = fr = 0
    comptype = compname = ""

    for i, path in enumerate(wavs):
        with wave.open(str(path), "rb") as wf:
            p = wf.getparams()
            if i == 0:
                ch, sw, fr, _, comptype, compname = (
                    p.nchannels,
                    p.sampwidth,
                    p.framerate,
                    p.nframes,
                    p.comptype,
                    p.compname,
                )
            else:
                if (p.nchannels, p.sampwidth, p.framerate, p.comptype) != (ch, sw, fr, comptype):
                    print(f"[-] 参数不一致，跳过合并: {path}")
                    print(f"    第一条: ch={ch}, width={sw}, rate={fr}")
                    print(f"    当前: ch={p.nchannels}, width={p.sampwidth}, rate={p.framerate}")
                    return 1
            data = wf.readframes(p.nframes)

        if args.gap_ms > 0 and i > 0:
            nbytes = int(fr * (args.gap_ms / 1000.0)) * ch * sw
            chunks.append(b"\x00" * nbytes)
        chunks.append(data)

    merged = b"".join(chunks)

    out_p = wave.open(str(merge_path), "wb")
    try:
        out_p.setnchannels(ch)
        out_p.setsampwidth(sw)
        out_p.setframerate(fr)
        out_p.setcomptype(comptype, compname)
        out_p.writeframes(merged)
    finally:
        out_p.close()

    dur_s = len(merged) / (fr * ch * sw)
    print(f"[+] 共 {len(wavs)} 条 WAV")
    print(f"[+] 时长约 {dur_s:.1f} 秒")
    print(f"[+] 已写入 {merge_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

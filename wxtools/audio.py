# -*- coding: utf-8 -*-
"""纯标准库的音频处理：按时间顺序拼接微信导出的 WAV。"""
from __future__ import annotations

import re
import wave
from pathlib import Path


def _sort_key(p: Path) -> tuple:
    """文件名含 YYYY-MM-DD_HH-MM-SS 则按时间排序，否则排到末尾。"""
    m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})", p.name)
    if m:
        return (m.group(1), m.group(2), p.name)
    return ("9999", "99-99-99", str(p))


def collect_wavs(root: Path) -> list[Path]:
    return sorted((p for p in root.rglob("*.wav") if p.is_file()), key=_sort_key)


def concat_wavs(input_dir: Path, output: Path, gap_ms: int = 0) -> tuple[int, float]:
    """递归拼接目录下所有 WAV 为一条（要求参数一致）。

    :return: (条数, 时长秒)。参数不一致时抛出 ValueError。
    """
    wavs = collect_wavs(input_dir)
    if not wavs:
        raise FileNotFoundError(f"未找到 wav: {input_dir}")

    output.parent.mkdir(parents=True, exist_ok=True)
    chunks: list[bytes] = []
    ch = sw = fr = 0
    comptype = compname = ""

    for i, path in enumerate(wavs):
        with wave.open(str(path), "rb") as wf:
            p = wf.getparams()
            if i == 0:
                ch, sw, fr, comptype, compname = p.nchannels, p.sampwidth, p.framerate, p.comptype, p.compname
            elif (p.nchannels, p.sampwidth, p.framerate, p.comptype) != (ch, sw, fr, comptype):
                raise ValueError(
                    f"参数不一致，无法合并: {path}\n"
                    f"    首条 ch={ch} width={sw} rate={fr}; 当前 ch={p.nchannels} width={p.sampwidth} rate={p.framerate}"
                )
            data = wf.readframes(p.nframes)
        if gap_ms > 0 and i > 0:
            chunks.append(b"\x00" * (int(fr * gap_ms / 1000.0) * ch * sw))
        chunks.append(data)

    merged = b"".join(chunks)
    with wave.open(str(output), "wb") as out:
        out.setnchannels(ch)
        out.setsampwidth(sw)
        out.setframerate(fr)
        out.setcomptype(comptype, compname)
        out.writeframes(merged)

    dur_s = len(merged) / (fr * ch * sw) if fr and ch and sw else 0.0
    return len(wavs), dur_s

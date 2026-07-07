# -*- coding: utf-8 -*-
"""音视频工具：视频取音轨、替换音轨（依赖 ffmpeg），音色对比（依赖 librosa）。

重依赖均为惰性 import，未用到相关功能时不会强制安装。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def _require(*tools: str) -> None:
    missing = [t for t in tools if not shutil.which(t)]
    if missing:
        sys.exit(f"[-] 缺少 {', '.join(missing)}，请安装 FFmpeg 并确保其在 PATH 中。")


def _run_ffmpeg(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.stderr.write(r.stderr or r.stdout or "")
        sys.exit(f"[-] ffmpeg 失败 (exit {r.returncode})")


# ------------------------- 提取音轨 ------------------------- #

def extract_video_audio(video: Path, output: Path, fmt: str = "wav") -> None:
    _require("ffmpeg")
    video, output = video.resolve(), output.resolve()
    if not video.is_file():
        sys.exit(f"[-] 视频不存在: {video}")
    output.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "wav":
        codec = ["-acodec", "pcm_s16le"]
    elif fmt in ("m4a", "aac"):
        codec = ["-acodec", "copy"]
    else:
        sys.exit(f"[-] 不支持的格式: {fmt}，请用 wav 或 m4a")
    _run_ffmpeg(["ffmpeg", "-hide_banner", "-y", "-i", str(video), "-vn", *codec, str(output)])


# ------------------------- 替换音轨 ------------------------- #

def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        sys.exit(f"[-] ffprobe 失败: {path}\n{r.stderr}")
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError) as e:
        sys.exit(f"[-] 无法解析时长: {path} ({e})")


def replace_video_audio(
    video: Path, audio: Path, output: Path, mode: str = "video", audio_bitrate: str = "192k"
) -> None:
    _require("ffmpeg", "ffprobe")
    video, audio = video.resolve(), audio.resolve()
    if not video.is_file():
        sys.exit(f"[-] 视频不存在: {video}")
    if not audio.is_file():
        sys.exit(f"[-] 音频不存在: {audio}")
    output.parent.mkdir(parents=True, exist_ok=True)

    base = ["ffmpeg", "-hide_banner", "-y", "-i", str(video), "-i", str(audio)]
    if mode == "shortest":
        cmd = base + [
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", audio_bitrate, "-shortest", str(output),
        ]
    else:
        vd = _probe_duration(video)
        filt = f"[1:a]atrim=end={vd},asetpts=PTS-STARTPTS,apad=whole_dur={vd}[outa]"
        cmd = base + [
            "-filter_complex", filt, "-map", "0:v:0", "-map", "[outa]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", audio_bitrate, "-t", str(vd), str(output),
        ]
    _run_ffmpeg(cmd)


# ------------------------- 音色对比 ------------------------- #

def _safe_mean(arr) -> float:
    return float(arr.mean()) if arr.size else 0.0


def _extract_features(y, sr: int, n_mfcc: int) -> dict:
    import numpy as np
    import librosa

    y = np.asarray(y, dtype=np.float32)
    if y.size == 0:
        raise ValueError("音频为空，无法分析")
    summary = {
        "zero_crossing_rate": _safe_mean(librosa.feature.zero_crossing_rate(y=y)),
        "rms": _safe_mean(librosa.feature.rms(y=y)),
        "spectral_centroid_hz": _safe_mean(librosa.feature.spectral_centroid(y=y, sr=sr)),
        "spectral_bandwidth_hz": _safe_mean(librosa.feature.spectral_bandwidth(y=y, sr=sr)),
        "spectral_rolloff_hz": _safe_mean(librosa.feature.spectral_rolloff(y=y, sr=sr)),
        "spectral_flatness": _safe_mean(librosa.feature.spectral_flatness(y=y)),
        "spectral_contrast": _safe_mean(librosa.feature.spectral_contrast(y=y, sr=sr)),
        "chroma_mean": _safe_mean(librosa.feature.chroma_stft(y=y, sr=sr)),
    }
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc)
    summary["mfcc_mean_abs"] = float(np.mean(np.abs(mfcc)))
    summary["mfcc_std_mean"] = float(np.mean(np.std(mfcc, axis=1)))
    return {"summary": summary, "sr": sr}


def _draw_report(name1, name2, feat1, feat2, y1, y2, sr, output: Path) -> None:
    import numpy as np
    import librosa
    import librosa.display
    import matplotlib.pyplot as plt

    mel1 = librosa.power_to_db(librosa.feature.melspectrogram(y=y1, sr=sr, n_mels=128), ref=np.max)
    mel2 = librosa.power_to_db(librosa.feature.melspectrogram(y=y2, sr=sr, n_mels=128), ref=np.max)

    keys = ["spectral_centroid_hz", "spectral_bandwidth_hz", "spectral_rolloff_hz", "spectral_flatness",
            "spectral_contrast", "mfcc_mean_abs", "rms", "zero_crossing_rate"]
    labels = ["Centroid", "Bandwidth", "Rolloff", "Flatness", "Contrast", "MFCC|abs|", "RMS", "ZCR"]

    s1, s2 = feat1["summary"], feat2["summary"]
    radar1, radar2, deltas = [], [], []
    for k in keys:
        m = max(abs(s1[k]), abs(s2[k]), 1e-12)
        radar1.append(float(np.clip(s1[k] / m, -1.0, 1.0)))
        radar2.append(float(np.clip(s2[k] / m, -1.0, 1.0)))
        deltas.append(s2[k] - s1[k])

    angles = np.linspace(0, 2 * np.pi, len(keys), endpoint=False)
    ac = np.concatenate([angles, [angles[0]]])
    r1c = np.concatenate([np.array(radar1), [radar1[0]]])
    r2c = np.concatenate([np.array(radar2), [radar2[0]]])

    fig = plt.figure(figsize=(16, 10))
    gs = fig.add_gridspec(2, 3, height_ratios=[1, 1.05])

    ax1 = fig.add_subplot(gs[0, 0])
    librosa.display.specshow(mel1, sr=sr, x_axis="time", y_axis="mel", ax=ax1)
    ax1.set_title(f"Mel Spectrogram - A1: {name1}", fontsize=10)
    ax2 = fig.add_subplot(gs[0, 1])
    librosa.display.specshow(mel2, sr=sr, x_axis="time", y_axis="mel", ax=ax2)
    ax2.set_title(f"Mel Spectrogram - A2: {name2}", fontsize=10)

    ax3 = fig.add_subplot(gs[0, 2], projection="polar")
    ax3.plot(ac, r1c, linewidth=2, label="A1")
    ax3.fill(ac, r1c, alpha=0.15)
    ax3.plot(ac, r2c, linewidth=2, label="A2")
    ax3.fill(ac, r2c, alpha=0.15)
    ax3.set_xticks(angles)
    ax3.set_xticklabels(labels, fontsize=8)
    ax3.set_yticklabels([])
    ax3.set_title("Timbre Profile (normalized)", fontsize=10)
    ax3.legend(loc="upper right", bbox_to_anchor=(1.2, 1.2), fontsize=8)

    ax4 = fig.add_subplot(gs[1, :2])
    x = np.arange(len(labels))
    ax4.bar(x, deltas, color=["#d62728" if d > 0 else "#1f77b4" for d in deltas], alpha=0.85)
    ax4.axhline(0, color="black", linewidth=1)
    ax4.set_xticks(x)
    ax4.set_xticklabels(labels, rotation=20, ha="right")
    ax4.set_title("A2 - A1 Feature Delta", fontsize=11)
    ax4.grid(axis="y", linestyle="--", alpha=0.25)

    ax5 = fig.add_subplot(gs[1, 2])
    ax5.axis("off")
    ax5.text(0.0, 1.0, (
        "Key Summary\n"
        f"A1 centroid: {s1['spectral_centroid_hz']:.1f} Hz\n"
        f"A2 centroid: {s2['spectral_centroid_hz']:.1f} Hz\n"
        f"A1 rolloff : {s1['spectral_rolloff_hz']:.1f} Hz\n"
        f"A2 rolloff : {s2['spectral_rolloff_hz']:.1f} Hz\n"
        f"A1 flatness: {s1['spectral_flatness']:.4f}\n"
        f"A2 flatness: {s2['spectral_flatness']:.4f}\n"
        f"A1 MFCC abs: {s1['mfcc_mean_abs']:.3f}\n"
        f"A2 MFCC abs: {s2['mfcc_mean_abs']:.3f}\n"
        "\nInterpretation\n"
        "- Centroid/Rolloff 越高，音色通常越亮。\n"
        "- Flatness 越高，通常噪声感更强。\n"
        "- MFCC 统计差异大，说明整体音色纹理差别更明显。"
    ), va="top", fontsize=9)

    fig.suptitle("Audio Timbre Comparison Report", fontsize=14, fontweight="bold")
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def compare_timbre(
    audio1: Path, audio2: Path, output: Path, json_out: Path | None = None,
    sr: int = 22050, n_mfcc: int = 13, max_seconds: float = 60.0,
) -> None:
    try:
        import librosa
    except Exception as e:
        raise SystemExit(
            "缺少依赖，请先安装: pip install numpy librosa matplotlib soundfile\n"
            f"详细错误: {e}"
        )
    for p, flag in ((audio1, "--audio1"), (audio2, "--audio2")):
        if not p.is_file():
            raise SystemExit(f"[-] {flag} 文件不存在: {p}")

    y1, _ = librosa.load(str(audio1), sr=sr, mono=True)
    y2, _ = librosa.load(str(audio2), sr=sr, mono=True)
    if max_seconds > 0:
        max_len = int(max_seconds * sr)
        y1, y2 = y1[:max_len], y2[:max_len]
    min_len = min(len(y1), len(y2))
    if min_len <= 0:
        raise SystemExit("音频长度为 0，无法比较")
    y1, y2 = y1[:min_len], y2[:min_len]

    feat1 = _extract_features(y1, sr, n_mfcc)
    feat2 = _extract_features(y2, sr, n_mfcc)
    _draw_report(audio1.name, audio2.name, feat1, feat2, y1, y2, sr, output)

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump({
                "audio1": str(audio1), "audio2": str(audio2), "sample_rate": sr,
                "compare_duration_seconds": min_len / float(sr),
                "summary": {"audio1": feat1["summary"], "audio2": feat2["summary"]},
            }, f, ensure_ascii=False, indent=2)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对比两段音频的音色特征，并输出可视化图片。

示例:
  python scripts/compare_audio_timbre.py \
    -a1 "E:\\path\\audio1.wav" \
    -a2 "E:\\path\\audio2.wav" \
    -o  "E:\\path\\timbre_compare.png"

可选输出 JSON:
  python scripts/compare_audio_timbre.py ... --json-out "E:\\path\\timbre_compare.json"

依赖:
  pip install numpy librosa matplotlib soundfile
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="分析两段音频音色差异并生成图片")
    parser.add_argument("-a1", "--audio1", required=True, help="第一段音频路径")
    parser.add_argument("-a2", "--audio2", required=True, help="第二段音频路径")
    parser.add_argument("-o", "--output", required=True, help="输出图片路径（PNG）")
    parser.add_argument("--json-out", default="", help="可选：输出特征 JSON 路径")
    parser.add_argument("--sr", type=int, default=22050, help="重采样率，默认 22050")
    parser.add_argument("--n-mfcc", type=int, default=13, help="MFCC 维度，默认 13")
    parser.add_argument("--max-seconds", type=float, default=60.0, help="最多分析前多少秒，默认 60")
    return parser


def ensure_file(path_str: str, flag_name: str) -> Path:
    p = Path(path_str).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"{flag_name} 文件不存在: {p}")
    return p


def _safe_mean(arr):
    return float(arr.mean()) if arr.size else 0.0


def extract_features(y, sr, n_mfcc):
    import numpy as np
    import librosa

    y = np.asarray(y, dtype=np.float32)
    if y.size == 0:
        raise ValueError("音频为空，无法分析")

    zcr = librosa.feature.zero_crossing_rate(y=y)
    rms = librosa.feature.rms(y=y)
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr)
    bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr)
    rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)
    flatness = librosa.feature.spectral_flatness(y=y)
    contrast = librosa.feature.spectral_contrast(y=y, sr=sr)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc)
    chroma = librosa.feature.chroma_stft(y=y, sr=sr)

    summary = {
        "zero_crossing_rate": _safe_mean(zcr),
        "rms": _safe_mean(rms),
        "spectral_centroid_hz": _safe_mean(centroid),
        "spectral_bandwidth_hz": _safe_mean(bandwidth),
        "spectral_rolloff_hz": _safe_mean(rolloff),
        "spectral_flatness": _safe_mean(flatness),
        "spectral_contrast": _safe_mean(contrast),
        "chroma_mean": _safe_mean(chroma),
        "mfcc_mean_abs": float(np.mean(np.abs(mfcc))),
        "mfcc_std_mean": float(np.mean(np.std(mfcc, axis=1))),
    }

    return {
        "summary": summary,
        "mfcc": mfcc,
        "sr": sr,
    }


def normalize_pair(v1: float, v2: float):
    import numpy as np

    m = max(abs(v1), abs(v2), 1e-12)
    return float(np.clip(v1 / m, -1.0, 1.0)), float(np.clip(v2 / m, -1.0, 1.0))


def draw_report(audio1_name, audio2_name, feat1, feat2, y1, y2, sr, output_path: Path):
    import numpy as np
    import librosa
    import librosa.display
    import matplotlib.pyplot as plt

    # 计算梅尔频谱用于直观展示音色分布
    melspec1 = librosa.power_to_db(
        librosa.feature.melspectrogram(y=y1, sr=sr, n_mels=128),
        ref=np.max,
    )
    melspec2 = librosa.power_to_db(
        librosa.feature.melspectrogram(y=y2, sr=sr, n_mels=128),
        ref=np.max,
    )

    keys = [
        "spectral_centroid_hz",
        "spectral_bandwidth_hz",
        "spectral_rolloff_hz",
        "spectral_flatness",
        "spectral_contrast",
        "mfcc_mean_abs",
        "rms",
        "zero_crossing_rate",
    ]
    labels = [
        "Centroid",
        "Bandwidth",
        "Rolloff",
        "Flatness",
        "Contrast",
        "MFCC|abs|",
        "RMS",
        "ZCR",
    ]

    s1 = feat1["summary"]
    s2 = feat2["summary"]
    radar1 = []
    radar2 = []
    deltas = []
    for k in keys:
        n1, n2 = normalize_pair(s1[k], s2[k])
        radar1.append(n1)
        radar2.append(n2)
        deltas.append(s2[k] - s1[k])

    angles = np.linspace(0, 2 * np.pi, len(keys), endpoint=False)
    angles_closed = np.concatenate([angles, [angles[0]]])
    radar1_closed = np.concatenate([np.array(radar1), [radar1[0]]])
    radar2_closed = np.concatenate([np.array(radar2), [radar2[0]]])

    fig = plt.figure(figsize=(16, 10))
    gs = fig.add_gridspec(2, 3, height_ratios=[1, 1.05])

    ax1 = fig.add_subplot(gs[0, 0])
    librosa.display.specshow(melspec1, sr=sr, x_axis="time", y_axis="mel", ax=ax1)
    ax1.set_title(f"Mel Spectrogram - A1: {audio1_name}", fontsize=10)

    ax2 = fig.add_subplot(gs[0, 1])
    librosa.display.specshow(melspec2, sr=sr, x_axis="time", y_axis="mel", ax=ax2)
    ax2.set_title(f"Mel Spectrogram - A2: {audio2_name}", fontsize=10)

    ax3 = fig.add_subplot(gs[0, 2], projection="polar")
    ax3.plot(angles_closed, radar1_closed, linewidth=2, label="A1")
    ax3.fill(angles_closed, radar1_closed, alpha=0.15)
    ax3.plot(angles_closed, radar2_closed, linewidth=2, label="A2")
    ax3.fill(angles_closed, radar2_closed, alpha=0.15)
    ax3.set_xticks(angles)
    ax3.set_xticklabels(labels, fontsize=8)
    ax3.set_yticklabels([])
    ax3.set_title("Timbre Profile (normalized)", fontsize=10)
    ax3.legend(loc="upper right", bbox_to_anchor=(1.2, 1.2), fontsize=8)

    ax4 = fig.add_subplot(gs[1, :2])
    x = np.arange(len(labels))
    colors = ["#d62728" if d > 0 else "#1f77b4" for d in deltas]
    ax4.bar(x, deltas, color=colors, alpha=0.85)
    ax4.axhline(0, color="black", linewidth=1)
    ax4.set_xticks(x)
    ax4.set_xticklabels(labels, rotation=20, ha="right")
    ax4.set_title("A2 - A1 Feature Delta", fontsize=11)
    ax4.grid(axis="y", linestyle="--", alpha=0.25)

    ax5 = fig.add_subplot(gs[1, 2])
    ax5.axis("off")
    txt = (
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
    )
    ax5.text(0.0, 1.0, txt, va="top", fontsize=9)

    fig.suptitle("Audio Timbre Comparison Report", fontsize=14, fontweight="bold")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def main():
    parser = build_parser()
    args = parser.parse_args()

    audio1 = ensure_file(args.audio1, "--audio1")
    audio2 = ensure_file(args.audio2, "--audio2")
    output = Path(args.output).expanduser().resolve()
    json_out = Path(args.json_out).expanduser().resolve() if args.json_out else None

    try:
        import librosa
        import numpy as np
    except Exception as e:
        raise SystemExit(
            "缺少依赖，请先安装: pip install numpy librosa matplotlib soundfile\n"
            f"详细错误: {e}"
        )

    y1, sr1 = librosa.load(str(audio1), sr=args.sr, mono=True)
    y2, sr2 = librosa.load(str(audio2), sr=args.sr, mono=True)

    if args.max_seconds > 0:
        max_len = int(args.max_seconds * args.sr)
        y1 = y1[:max_len]
        y2 = y2[:max_len]

    # 长度对齐用于公平比较（按较短长度）
    min_len = min(len(y1), len(y2))
    if min_len <= 0:
        raise SystemExit("音频长度为 0，无法比较")
    y1 = y1[:min_len]
    y2 = y2[:min_len]

    feat1 = extract_features(y1, args.sr, args.n_mfcc)
    feat2 = extract_features(y2, args.sr, args.n_mfcc)

    draw_report(
        audio1_name=audio1.name,
        audio2_name=audio2.name,
        feat1=feat1,
        feat2=feat2,
        y1=y1,
        y2=y2,
        sr=args.sr,
        output_path=output,
    )

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "audio1": str(audio1),
            "audio2": str(audio2),
            "sample_rate": args.sr,
            "compare_duration_seconds": min_len / float(args.sr),
            "summary": {
                "audio1": feat1["summary"],
                "audio2": feat2["summary"],
            },
        }
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"[+] 对比图已生成: {output}")
    if json_out:
        print(f"[+] 特征JSON已输出: {json_out}")


if __name__ == "__main__":
    main()


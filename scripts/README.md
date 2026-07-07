# scripts —— 已整合进 `wxtools`

原先这里的 8 个独立脚本已合并为一个包 [`wxtools`](../wxtools) + 一个统一命令行。
功能保持不变，只是入口从「一个脚本一件事」变成「一条命令一个子命令」。

## 用法

```bash
# 安装后（pip install -e .）可直接用 wxtools 命令；否则用 python -m wxtools
python -m wxtools <子命令> [参数]
```

联系人 wxid 不再硬编码在源码里，按以下优先级解析：
`--peer-wxid` 参数 > 环境变量 `WXTOOLS_PEER` > `wxdump_work/wxtools.json` 里的 `{"peer_wxid": "wxid_xxx"}`。

## 旧脚本 → 新命令对照

| 旧脚本 | 新命令 |
|---|---|
| `refresh_export_csv.py --peer-wxid X` | `wxtools refresh --peer-wxid X` |
| `refresh_export_csv.py --merge-only` | `wxtools refresh --merge-only` |
| `refresh_export_csv.py --export-only` | `wxtools refresh --export-only` |
| `refresh_after_wechat_quit.py --peer-wxid X --timeout 600` | `wxtools wait-refresh --peer-wxid X --timeout 600` |
| `merge_msg1_via_api.py`（仅合并 MSG1） | `wxtools refresh --shards 1 --merge-only` |
| `export_voices_from_csv.py --room-wxid X --since D` | `wxtools voices --peer-wxid X --since D` |
| `export_voices_from_csv.py --peer-only` | `wxtools voices --speaker peer` |
| `export_voices_from_csv.py --self-only` | `wxtools voices --speaker self` |
| `export_voices_from_csv.py --all-time` | `wxtools voices --all-time` |
| `concat_voice_wavs.py -i DIR -o OUT` | `wxtools concat -i DIR -o OUT` |
| `extract_video_audio.py -v V.mp4` | `wxtools video-extract -v V.mp4` |
| `replace_video_audio.py -v V -a A -o O` | `wxtools video-replace -v V -a A -o O` |
| `compare_audio_timbre.py -a1 A -a2 B -o P` | `wxtools timbre -a1 A -a2 B -o P` |

## 新增能力（原脚本没有）

- `wxtools realtime` —— 微信开着也能合并最新消息，无需退出微信（读取运行中进程数据，仅 64 位 Windows）。
  `refresh` 默认会先尝试这一步（失败不影响后续常规合并），可用 `--no-realtime` 跳过。
- `refresh`/`wxtools ui` 导出 CSV 后会打印该会话本地最新消息时间，方便和手机上看到的对比，
  判断是否需要先在 PC 微信里打开对话触发同步。

各子命令的完整参数见 `python -m wxtools <子命令> --help`。

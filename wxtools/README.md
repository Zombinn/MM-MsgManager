# wxtools 使用指南

`wxtools` 是这个仓库自带的个人工作流工具集：把原来散落的 8 个脚本收敛成一条统一命令行
+ 一个开箱即用的本地网页控制台，专门覆盖"合并最新聊天记录 → 导出 CSV → 筛语音 →
拼接/处理音视频"这条链路。

> 微信账号信息的**首次采集**（扫描微信、拿到解密密钥、生成 `merge_all.db`）不属于
> `wxtools`，仍然用上游 `pywxdump` 自带的 `wxdump` 命令完成，见下文「① 首次初始化」。

---

## 0. 安装

推荐用项目自带的虚拟环境，避免污染系统 Python（`pywxdump` 的依赖里有个别包会锁定
较老的 `protobuf` 版本，和 TensorFlow/onnx 等现代 ML 工具在同一个全局环境会冲突）。

```powershell
cd D:\Code\WeChatTool\MM-MsgManager
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

装完后 `wxdump` / `wxtools` 两个命令都会出现在 `.venv\Scripts\` 下。激活虚拟环境后可
以直接敲命令名；不激活的话就用完整路径 `.\.venv\Scripts\wxtools.exe ...`。

不想装的话，也可以用 `python -m` 等价调用：
```powershell
python -m pywxdump.cli ui
python -m wxtools ui
```

---

## 1. 首次初始化（一次性，仍用 `wxdump`）

```powershell
wxdump ui
```

浏览器打开 `http://127.0.0.1:5000/`，按提示走完初始化（选中当前登录的微信账号 →
自动获取密钥 → 解密并生成 `merge_all.db`）。完成后账号信息会写进
`wxdump_work/conf_auto.json`，后续所有 `wxtools` 命令都从这个文件读取账号。

> 这一步会打开原版 PyWxDump 的网页聊天查看器界面（`/s/index.html`）。如果这个仓库
> 没有单独构建过前端静态文件，打开会显示 404——这是正常的，不影响初始化流程本身
> （初始化走的是后端 API，不依赖那个前端页面）。日常查看和操作请用下面的
> `wxtools ui`。

---

## 2. 日常使用：两种方式二选一

### 方式一：网页控制台（推荐）

```powershell
wxtools ui
```

默认打开 `http://127.0.0.1:5001/`，界面上三块：

1. **刷新聊天记录** —— 合并最新消息 + 导出指定联系人的 CSV
2. **导出语音** —— 从 CSV 里筛语音消息，导出成 WAV
3. **拼接语音** —— 把一个目录下的 WAV 按时间顺序拼成一条长音频

操作全部在后台线程跑，界面不会卡住，下方日志框实时滚动。只监听 `127.0.0.1`，仅供
本机使用。

### 方式二：命令行

```powershell
python -m wxtools <子命令> [参数]
# 或激活 venv 后直接：
wxtools <子命令> [参数]
```

---

## 3. 子命令详解

### `refresh` —— 合并最新 MSG 分库并导出联系人 CSV（最常用）

```powershell
wxtools refresh --peer-wxid wxid_xxx
```

默认行为（按顺序）：
1. 尝试**实时合并**（微信开着也能拉到刚同步的消息，见下文「4. 消息拿不到怎么办」）
2. 解密并合并 `Msg/Multi/MSG*.db` 分库到 `merge_all.db`
3. 导出该联系人的聊天记录 CSV 到 `wxdump_work/export/<my_wxid>/csv/<peer_wxid>/`
4. 打印这个会话本地能读到的**最新一条消息时间**，方便你和手机上看到的对一下

常用参数：

| 参数 | 作用 |
|---|---|
| `--peer-wxid wxid_xxx` | 指定联系人（不传则按 3. 的优先级解析） |
| `--merge-only` | 只合并数据库，不导出 CSV（不需要指定联系人） |
| `--export-only` | 只导出 CSV，不合并（假设数据库已经是最新的） |
| `--shards 1 3` | 只合并指定序号的分库（如只处理 MSG1、MSG3） |
| `--no-realtime` | 跳过实时合并这一步，直接走常规合并 |

### `wait-refresh` —— 等你退出微信后再合并（最彻底、最可靠）

```powershell
wxtools wait-refresh --peer-wxid wxid_xxx --timeout 600
```

先等 `WeChat.exe`/`Weixin.exe` 进程退出（最多等 `--timeout` 秒，默认 600），退出后
自动执行一次完整 `refresh`。参数和 `refresh` 完全一样，多了 `--timeout`/`--poll`
（轮询间隔，默认 2 秒）。

### `realtime` —— 微信开着也能合并最新消息（无需退出）

```powershell
wxtools realtime
```

单独触发一次"实时合并"，不涉及导出 CSV。依赖 pywxdump 自带的 `realTime.exe`
读取运行中微信进程的数据，**仅支持 64 位 Windows**。这是 best-effort 操作：失败也
不影响你后续正常使用 `refresh`/`wait-refresh`。

### `voices` —— 从 CSV 筛语音并导出 WAV

```powershell
wxtools voices --peer-wxid wxid_xxx --since 2026-04-01 --speaker all
```

| 参数 | 作用 |
|---|---|
| `--peer-wxid` | 联系人（同上优先级解析） |
| `--since 2026-04-01` | 起始日期，默认本年 4 月 1 日 |
| `--all-time` | 不限制时间，导出 CSV 里全部语音 |
| `--speaker all\|peer\|self` | 导出哪一方的语音（全部/仅对方/仅自己） |
| `--csv-dir DIR` | 手动指定 CSV 目录（默认按账号/联系人自动推导） |
| `--out-dir DIR` | 手动指定输出目录 |

导出目录默认是 `wxdump_work/export/<my_wxid>/voices_<peer>_<speaker>_<since>/`。

### `concat` —— 按时间拼接 WAV 为一条长音频

```powershell
wxtools concat -i wxdump_work/export/.../voices_xxx -o merged.wav --gap-ms 300
```

`--gap-ms` 是每条语音之间插入的静音毫秒数，默认 0（无缝拼接）。

### `video-extract` / `video-replace` —— 视频音轨提取/替换（依赖 ffmpeg）

```powershell
wxtools video-extract -v input.mp4                      # 输出 input_audio.wav
wxtools video-extract -v a.mp4 -v b.mp4 --format m4a     # 批量，输出 m4a
wxtools video-replace -v input.mp4 -a narration.wav -o output.mp4
```

`video-replace` 的 `--mode video`（默认，按视频时长截断/补静音）或
`--mode shortest`（取两者较短的时长）。需要系统 `PATH` 里有 `ffmpeg`/`ffprobe`。

### `timbre` —— 对比两段音频的音色并出图（依赖 librosa）

```powershell
wxtools timbre -a1 A.wav -a2 B.wav -o compare.png --json-out compare.json
```

---

## 4. 联系人 wxid 怎么配置

不用再把 wxid 写死在脚本里了。按以下优先级解析：

1. 命令行 `--peer-wxid wxid_xxx`
2. 环境变量 `WXTOOLS_PEER`
3. `wxdump_work/wxtools.json` 里的 `{"peer_wxid": "wxid_xxx"}`（写一次，以后不用每次都传）

---

## 5. 手机上刚发的消息拿不到，怎么办

这个现象有两种完全不同的成因，处理方式不一样：

**情况一：微信 PC 客户端开着，新消息卡在 WAL 里还没落盘。**
→ 直接 `wxtools refresh`（默认会先试一次 `realtime`，大概率不用退出微信就能拿到）；
如果还是拿不到，用 `wxtools wait-refresh` 等退出后再合并，这个最可靠。

**情况二：消息还没从手机/云端同步到这台电脑。**
→ 这个没法靠工具"修复"，本地磁盘上没有的数据任何工具都读不出来。
先在 **微信 PC 客户端里手动打开那个对话**，等它自己同步完，再重新跑一次
`wxtools refresh`。跑完看日志里打印的"该会话本地最新消息时间"，和手机上看到的
最新消息对一下，就知道是不是已经同步过来了。

---

## 6. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `conf_auto.json` 找不到 | 还没做过「① 首次初始化」，先跑 `wxdump ui` |
| `refresh --merge-only` 报错要联系人 | 已修复：合并操作本身不需要联系人，只有导出才需要 |
| `wxtools ui` 网页打不开 / 端口占用 | `wxtools ui -p 5002` 换个端口 |
| `wxdump ui` 里 `/s/index.html` 显示 404 | 正常现象，原版网页前端没有打包进这个仓库；初始化本身不受影响，日常用 `wxtools ui` 即可 |
| 装依赖后 TensorFlow/onnx 报 protobuf 冲突 | 说明装进了系统全局 Python；改用本仓库的 `.venv` 隔离安装（见「0. 安装」） |
| `realtime` 一直失败 | 仅支持 64 位 Windows；失败不影响 `refresh` 后续正常合并，可用 `--no-realtime` 跳过 |

各子命令的完整参数：`wxtools <子命令> --help`。

旧脚本 → 新命令的一一对照见 [scripts/README.md](../scripts/README.md)。

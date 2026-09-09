---
name: downloading-bilibili-videos
description: Use when downloading a bilibili video, saving a B站/BV号 video locally, archiving 哔哩哔哩 videos, grabbing a video's cover image or metadata, or when a downloaded mp4 turns out corrupt, truncated, silent, or fails with "moov atom not found"
---

# 下载 B 站视频

拿 BV 号换回三样东西：正片 mp4、封面 jpg、元信息 info.json。

```bash
python3 scripts/download.py BV1xxx --out ./out
```

先跑一次 `python3 scripts/doctor.py`，它会告诉你缺什么、怎么装。

## 什么时候用这个 skill

- 要把某个 B 站视频存到本地
- 要视频封面或播放量/点赞数等元信息
- 下下来的 mp4 打不开、没声音、播到一半就断

**不适用**：整个 UP 主空间的批量增量抓取（这个 skill 只做单期/少量 BV）；下载后想出字幕、脑图、大纲 PDF 的，用同仓的 `digesting-bilibili-videos`。

## 快速参考

| 想干的事 | 命令 |
|---|---|
| 下一期 | `download.py BV1xxx --out ./out` |
| 下几期 | `download.py BV1xxx BV2yyy --out ./out` |
| 直接粘链接（**记得加引号**，`?`/`&` 会被 shell 吃掉） | `download.py "https://www.bilibili.com/video/BV1xxx?p=1" --out ./out` |
| 不限体积 | `--max-mb 0` |
| 只要封面和元信息，不下正片 | `--no-video` |
| 文件名带日期和标题 | `--stem-title` |
| 挂代理 | `--proxy socks5://127.0.0.1:1080` |
| 选项可以随便叠 | `download.py BV1xxx --out /tmp/x --no-video --stem-title` |

重跑是幂等的：已存在且校验通过的产物会跳过，坏的会被删掉重下。

## 为什么用 BBDown 而不是 yt-dlp

两个都能下，yt-dlp 也是合理选择。这里用 BBDown 的实际理由：

- **登录态是共用的**。BBDown 扫码登录后写下的 `BBDown.data`，同仓的字幕 skill 也要用它去调字幕接口。用 BBDown 就只需要登录一次。
- 未登录时 B 站会给 412 风控和低清晰度流；BBDown 自己管这套登录态。

如果你已经在用 yt-dlp 并且跑得好，不必换——但下面「怎么判断文件是完整的」那节的结论对两者同样成立。

## 怎么判断下下来的文件是完整的

**这是最容易做错的一件事。坏文件的体积看着是正常的，光判「文件存在」必然漏。**

具体地，**只比时长是不够的**：faststart 的 mp4 把 moov 放在文件头，被截断之后 ffprobe 报的时长**依然是满的**。实测把一个 3685 秒的文件截到 60%：

| 判据 | 截断到 60% 的文件 | 结论 |
|---|---|---|
| 文件存在 | ✅ 通过 | 没用 |
| 体积合理（115MB） | ✅ 通过 | 没用 |
| `ffprobe` 时长 | ✅ 报 3685s | **没用** |
| `ffmpeg -c copy -f null -` demux | ✅ rc=0，无输出 | **没用** |
| **最后一个视频包的 pts** | ❌ 只到 1958s | **只有这个管用** |

所以 `verify_mp4()` 查三样：容器能解析、音视频轨都在（缺音轨 = 合流被打断）、**最后一个视频包的 pts 覆盖到了片尾**。pts 全量扫描实测 0.27 秒 / 184MB，不必优化成区间读。

## 别直接下到目标盘

BBDown 分块下载后按通配合并分片。macOS 在 exFAT / 部分网络盘上会给每个分片配一个 `._` 伴生文件，`.` 在字典序里排在数字前面，**会被一起并进去** —— 合出来的文件开头是 AppleDouble 魔数而不是 `ftyp`，ffmpeg 报 `moov atom not found`。

实测同一个视频：下到 APFS 是 709MB 可播放，下到 exFAT 是 630MB 的废文件。

`download.py` 一律先下到 `$TMPDIR`（内置盘）再 `shutil.move` 过去，绕开这件事。**如果你自己写下载逻辑，这一步不能省。**

同理，挑产物时要滤掉 `._` 开头的文件，并且检查同目录有没有残留的 `.m4a`（有就说明没合流完）。

## 限流是静默的

B 站限流时接口**返回空结果，不报错**——列表是空的、view 查不到。所以「查不到这个视频」的可能原因至少有四种：BV 号写错、视频被删、需要代理、正在被限流。`doctor.py` 的报错里列了这四种，别看到空结果就断定视频不存在。

放慢节奏能缓解。这个 skill 面向少量 BV，没做退避重试；真要批量跑，在两期之间加随机间隔。

## 代理

`--proxy` 把地址写进进程级的 6 个代理环境变量，BBDown 和 curl 都会自动继承。

**BBDown 认 `socks5://`，不认 `socks5h://`** —— 传 socks5h 它会当没设代理直接直连。脚本会自动改写并提示。

## 依赖

| 要什么 | 干嘛用 | 怎么装 |
|---|---|---|
| BBDown | 下正片 | https://github.com/nilaoda/BBDown/releases 放进 PATH，然后 `BBDown login` 扫码 |
| ffmpeg / ffprobe | 校验完整性 | `brew install ffmpeg` |
| curl | 调接口、下封面 | 系统自带 |

**零 pip 依赖**，纯标准库。

`BBDown.data` 等价于你的 B 站登录态。**别提交进任何仓库、别分享**。

## 产物

```
out/
├── BV1xxx.mp4         正片（--no-video 或超体积上限时没有）
├── BV1xxx.jpg         封面
└── BV1xxx.info.json   bvid/aid/cid/标题/时长/播放/点赞/评论/UP主/简介/链接
```

`--stem-title` 时文件名变成 `20260323-标题-BV1xxx.*`。标题里的 `/\:*?"<>|` 会被换成 `_`。

## 常见问题

| 现象 | 原因 |
|---|---|
| `moov atom not found` | 下到了 exFAT/网络盘，分片合并被 `._` 文件污染。见上面那节 |
| 下下来没有声音 | 音视频没合流完。`verify_mp4` 会拦住并删掉 |
| 播到一半就断 | 截断的文件。只有 pts 覆盖判据看得出来 |
| 「查不到视频信息」 | BV 写错 / 视频被删 / 要代理 / **被限流**（限流是静默的） |
| 清晰度很低 | 没登录。`BBDown login` |
| 探不到体积 | BBDown 输出格式变了，正则失配。脚本会退化成不限体积照常下载，不会静默跳过 |

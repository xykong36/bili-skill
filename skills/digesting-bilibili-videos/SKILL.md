---
name: digesting-bilibili-videos
description: Downloads bilibili videos and turns their official AI subtitles into readable transcripts, OPML mindmaps, outlines and searchable Chinese PDFs. Use when downloading, saving or archiving a B站/BV号/哔哩哔哩 video locally, grabbing its cover image or metadata, getting a video's subtitles or transcript, turning an episode into a readable article, mindmap, outline or PDF, when a downloaded mp4 turns out corrupt, truncated, silent or fails with "moov atom not found", or when B站 subtitle requests come back empty or return the wrong video's text
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py *)
---

# B 站视频：存下来，或者嚼成能读的东西

先跑一次自检，它会告诉你缺什么、装什么命令：

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py doctor
```

## 走哪条工作流

两条工作流**并列**，不是流水线。字幕直接走接口拿、全程不碰 mp4，
所以**想要文字不必先下视频**。

| 用户想要 | 走 | 命令 |
|---|---|---|
| 本地存一份视频 / 封面 / 播放量 | 下载 | `python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py download BV1xxx --out ./out` |
| 字幕、逐字稿、文章、脑图、大纲、PDF | 嚼 | `python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py digest BV1xxx --out ./out --name 合集名` |
| 两个都要 | 一条命令 | `python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py digest BV1xxx --out ./out --with-video` |

上面的命令是完整形式，**照抄，别简写成 `bili.py ...` 或 `scripts/bili.py ...`**。
两个理由：Bash 工具的工作目录是用户的项目目录、不是 skill 目录，相对路径会找不到文件；
而 frontmatter 里 `allowed-tools` 的规则匹配的正是这个完整形式，简写会多一次权限弹窗。

## 不适用

整个 UP 主空间的批量增量抓取（只做单期/少量 BV）；没有官方 AI 字幕的视频——**这个 skill 不做语音转录**，遇到就明确报告跳过。

---

# 工作流 A：下载

拿 BV 号换回三样东西：正片 mp4、封面 jpg、元信息 info.json。

| 想干的事 | 命令 |
|---|---|
| 下一期 | `python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py download BV1xxx --out ./out` |
| 下几期 | `python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py download BV1xxx BV2yyy --out ./out` |
| 直接粘链接（**记得加引号**，`?`/`&` 会被 shell 吃掉） | `python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py download "https://www.bilibili.com/video/BV1xxx?p=1" --out ./out` |
| 不限体积（默认上限 800MB，超了只出封面+info） | `--max-mb 0` |
| 只要封面和元信息，不下正片 | `--no-video` |
| 文件名带日期和标题 | `--stem-title` |
| 选项可以随便叠 | `python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py download BV1xxx --out /tmp/x --no-video --stem-title` |

重跑是幂等的：已存在且校验通过的产物会跳过，坏的会被删掉重下。

## 怎么判断下下来的文件是完整的

**这是最容易做错的一件事。坏文件的体积看着是正常的，光判「文件存在」必然漏。**

| 判据 | 截断到 60% 的文件 | 结论 |
|---|---|---|
| 文件存在 / 体积合理 | ✅ 通过 | 没用 |
| `ffprobe` 时长 | ✅ 报满时长 | **没用** |
| `ffmpeg -c copy -f null -` demux | ✅ rc=0 | **没用** |
| **最后一个视频包的 pts** | ❌ 只到 53% | **只有这个管用** |

`verify_mp4()` 查三样：容器能解析、音视频轨都在（缺音轨 = 合流被打断）、**最后一个视频包的 pts 覆盖到了片尾**。实测数据和 exFAT 那个坑见 **[references/mp4-integrity.md](references/mp4-integrity.md)**——改下载相关代码前必读。

## 别直接下到目标盘

macOS 在 exFAT / 网络盘上会给分片配 `._` 伴生文件，合并时被一起并进去，产出 `moov atom not found` 的废文件。下载这条一律先下到 `$TMPDIR` 再 `shutil.move` 过去。**自己写下载逻辑的话这步不能省**，细节见上面那个 reference。

## 限流是静默的

B 站限流时接口**返回空结果，不报错**。所以「查不到这个视频」至少有三种原因：BV 号写错、视频被删、正在被限流。**别看到空结果就断定视频不存在。**

放慢节奏能缓解。这个 skill 面向少量 BV，没做退避重试；真要批量跑，在两期之间加随机间隔。

---

# 工作流 B：嚼

拿 BV 号换回五样东西：字幕 srt、阅读版 md、脑图 opml、大纲 md、以及两本可搜索的中文 PDF。

每步都幂等，产物在就跳过，可以随时中断续跑。

| 步 | 产出 | 要什么 |
|---|---|---|
| 1. 抓官方 AI 字幕 | `<stem>.srt` | 登录 cookie |
| 2. 合并成自然段 | `<stem>-阅读版.md` | 纯标准库 |
| 3. LLM 整理成脑图 | `<stem>.opml` + `.source.txt` | `DEEPSEEK_API_KEY` |
| 4. 渲染大纲 | `<stem>-大纲.md` | 纯本地，秒级 |
| 5. 出两本 PDF | `<名>-mindmap.pdf` / `<名>-outline.pdf` | `fpdf2` `fonttools` |

**步骤 4 和 5 都以第 3 步的 opml 为输入**，所以第 3 步跳过或失败时，大纲和 PDF 一并没有——这是正常的降级，不是漏做。1、2 两步不受影响，`--skip-mindmap` 仍然能拿到字幕和阅读版。

| 想干的事 | 命令 |
|---|---|
| 几期打成一本 | `python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py digest BV1 BV2 BV3 --out ./out --name 合集名` |
| 只要字幕和阅读版，不花钱 | `--skip-mindmap` |
| 不要 PDF | `--skip-pdf` |
| 已经有 srt 了（给了 `--srt` 就**忽略** BV 号，两者不叠加） | `python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py digest --srt a.srt --title 标题 --out ./out` |

## 抓字幕：只能走 `wbi/v2`

**老接口 `x/player/v2` 返回的是别的视频的字幕——不是截断，是串号。BBDown 走的正是老接口，所以 `BBDown --sub-only` 不可信。**

实测：同一个 397 秒的视频，连查老接口三次，拿到三份**内容完全不相干**的字幕；同一时刻查 `wbi/v2` 四次，结果完全一致且与视频对得上。完整实测表见 **[references/subtitle-api.md](references/subtitle-api.md)**——改字幕相关代码前必读。

不需要做 wbi 签名，带 Cookie + Referer + 常规 UA 就行。

**字幕来源看 URL 的 host，比 `lan` 字段可靠**：`aisubtitle.hdslb.com` 是官方 AI 生成的，`s1.hdslb.com` 是 UP 主自己投稿的人工字幕。两种都能用，值得在日志里区分。

## 空字幕列表有三种含义，别猜

不带 cookie 时接口返回 `code=0` 但 `subtitles` 是**空数组**——静默的空，不是报错。所以拿到空列表可能是：

1. 这个视频确实没有官方 AI 字幕
2. **没登录 / cookie 过期**
3. 被限流

**别直接报告「这个视频没有字幕」。** `python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py doctor` 会**自动**拿一个内置的、已知有官方字幕的 canary 视频探一次，以此区分（换一个用 `--canary BV...` 或 `BILI_CANARY` 环境变量）：canary 也拿不到 = 是你的登录态或限流问题，不是视频的问题。

脚本这边：抓不到字幕的那一期算失败、**跳过后面四步**，但**不中断整批**——
剩下的 BV 照常处理，结尾的「完成 N/M 期」会把它计进去。所以一批里少了几期
是正常可见的，不会静默吞掉。

## 两道字幕质量闸门

| 判定 | 阈值 | 处理 |
|---|---|---|
| 字幕比视频长 | > 1.05 倍 | 判串号，**丢弃** |
| 字幕没覆盖完 | < 0.90 | 保留但告警 |

上限那道逮出过 6 期串号字幕，是唯一能自动发现「拿错字幕」的手段。下限不设 1.00 是因为片尾常有无语音段；也别调到 0.7，那会放过漏掉 30% 内容的字幕。

## 脑图那步（LLM）

`reasoning_effort="none"` 是必须的，`--duration` 也必须传。踩坑细节见 **[references/llm-mindmap.md](references/llm-mindmap.md)**。

脑图节点的文本契约是 `<层级编号> [时间戳] 【类型】正文`，六种类型标签 `【观点】【数据】【案例】【金句】【做法】【交锋】` 是下游大纲排版和 PDF 配色的依据，**改 prompt 时别动它们**。

## PDF：中文必须可搜索

用 `fpdf2` 纯 Python 矢量出书，不启动 Chrome、不用 markmap、不用 LaTeX，跨平台结果一致。

**字体不能随便换**，也别用系统字体——很多中文字体会把常用字映射到康熙部首区，PDF 内搜索和复制就失效了。**肉眼看「中文显示正常」不等于没问题**：字形渲染对了，文本层照样可能是坏的。

`BILI_SKILLS_FONT` 可以换字体，但**换完必须按 [references/pdf-fonts.md](references/pdf-fonts.md) 里那条命令验一遍**（抽一页文本，确认康熙部首区字符数为 0）。

---

# 登录（两条工作流共用）

抓官方字幕、拿高清晰度流都要 B 站登录态：

```bash
pip install segno                                  # 一次性，纯 Python 零依赖
python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py login       # --force 换账号 / 刷新过期登录态
```

它给你**一个二维码 PNG 的绝对路径**和**一块文本二维码**，用手机 B 站 App 扫，扫完自动写出 `BBDown.data`（和 BBDown 自己写的格式完全一样，两边通用）。默认等 180 秒（正好是二维码有效期），超时就重跑。`--qr png` 只要图片，`--qr-out` 指定 PNG 落点。

**agent 请注意：不要去调 `BBDown login`。** 它没有任何选项能关掉终端里那一大块 ASCII 二维码，而且跑起来就阻塞轮询到扫码为止、不会返回——工具调用会被挂死。更阴的是 **`BBDown login --help` 不打印帮助，它直接开始真实登录流程**，所以它也不能拿来做探测。

登录 cookie 有两种下发方式，脚本**两种都收**：响应头的 `Set-Cookie`（B 站现在走这条），以及 `data.url` 的 query string（老端点、BBDown 走的那条）。只认一种的实现会在对方改版时静默失败——「扫码明明成功了却说没有 SESSDATA」就是这么来的。真出问题时加 `--debug`，它**只打字段名、不打任何值**。

`BBDown.data` 按这个顺序找：`BILI_COOKIE_FILE` 环境变量（设了就是权威的，
指到哪用哪）→ BBDown 可执行文件旁边 → `~/BBDown.data`。写的时候挑第一个
可写的目录。

`BBDown.data` 等价于你的 B 站账号登录态。**别提交进任何仓库、别分享。**
登录脚本会把它权限设成 0600，覆盖前先备份成 `.bak`。

---

# 依赖

| 要什么 | 哪条工作流用 | 怎么装 |
|---|---|---|
| curl | 两条都要 | 系统自带 |
| `BBDown.data` 登录态 | 两条都要（下载没它只能拿低清流；字幕没它只返回空列表） | `pip install segno` 后跑 `python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py login` 扫码 |
| BBDown | 下载 | https://github.com/nilaoda/BBDown/releases 放进 PATH |
| ffmpeg / ffprobe | 下载（完整性校验） | `brew install ffmpeg` |
| `DEEPSEEK_API_KEY` | 嚼第 3 步 | `echo 'DEEPSEEK_API_KEY=sk-...' >> .env.local`（`--skip-mindmap` 可绕过） |
| `fpdf2` `fonttools` | 嚼第 5 步 | `pip install fpdf2 fonttools`（`--skip-pdf` 可绕过） |
| `pypdf` | **只在换字体后自检时** | `pip install pypdf`，见 references/pdf-fonts.md |

下载、抓字幕、阅读版这几步都是**纯标准库**的。

**Python 3.9+**（已在 3.9 和 3.12 上实测跑通全链路）。注意：**agent 沙箱里的 `python3` 可能跟你交互式终端里的不是同一个**（pyenv/conda 的 shims 靠 shell 启动脚本注入 PATH，沙箱常起裸 shell）。依赖要装在**跑脚本的那个 python** 里；不确定就先跑 `python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py doctor`，它报什么缺什么就是那个 python 的实情。

# 产物

**两条工作流的文件名规则不一样**，这不是笔误：

| 工作流 | 默认 stem | 长格式 |
|---|---|---|
| 下载 | 光秃秃的 `BV1xxx` | 加 `--stem-title` 才变成 `20260323-标题-BV1xxx` |
| 嚼 | **一律** `20260323-标题-BV1xxx`，没有开关 | 同左 |

所以只跑下载时是 `BV1xxx.mp4`；只跑嚼时是 `20260323-标题-BV1xxx.srt`。
`--with-video` 会**强制**下载侧也用长格式，好让一期的所有产物同名，
否则同一个目录里看着像两个不相干的东西。

```
out/
├── BV1xxx.mp4                      下载：正片（--no-video 或超体积上限时没有）
├── BV1xxx.jpg                      下载：封面
├── BV1xxx.info.json                下载：bvid/aid/cid/标题/时长/播放/点赞/评论/UP主/简介/链接
├── 20260323-标题-BV1xxx.srt         嚼 1：官方 AI 字幕
├── 20260323-标题-BV1xxx-阅读版.md    嚼 2：合并成自然段
├── 20260323-标题-BV1xxx.opml        嚼 3：脑图
├── 20260323-标题-BV1xxx.source.txt  嚼 3：喂给 LLM 的原文
├── 20260323-标题-BV1xxx-大纲.md      嚼 4
├── <--name>-mindmap.pdf            嚼 5：整本，一批共一本
└── <--name>-outline.pdf            嚼 5：整本，一批共一本
```

标题里的 `/\:*?"<>|` 会被换成 `_`，整个 stem 截到 180 字符。

`--name` 只被第 5 步的两本 PDF 用（默认 `B站合集`）。加了 `--skip-pdf`
或 `--skip-mindmap` 时它没有任何作用，可以不给。

**但 PDF 这层不幂等，会覆盖。** srt / 阅读版 / opml / 大纲的文件名都带 BV，
重跑安全；两本 PDF 的文件名只由 `--name` 决定，内容是**这一次**给的那批 BV。
所以往同一个 `--out` 里再嚼一期而不换 `--name`，上一本会被悄悄覆盖掉，
里面只剩新的这期。**要么一次把所有 BV 都给全，要么每本换一个 `--name`。**

# 常见问题

| 现象 | 原因 |
|---|---|
| `moov atom not found` | 下到了 exFAT/网络盘，分片合并被 `._` 文件污染 |
| 下下来没有声音 | 音视频没合流完。`verify_mp4` 会拦住并删掉 |
| 播到一半就断 | 截断的文件。只有 pts 覆盖判据看得出来 |
| 「查不到视频信息」 | BV 写错 / 视频被删 / **被限流**（限流是静默的） |
| 清晰度很低 | 没登录。跑 `python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py login` |
| 探不到体积 | BBDown 输出格式变了，正则失配。会退化成不限体积照常下载，不会静默跳过 |
| 字幕列表为空 | 见「三种含义」，先跑 `python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py doctor` |
| 字幕内容跟视频完全不相干 | 走到老接口了。只能用 `wbi/v2` |
| 报「判定串号，已丢弃」 | 上限校验生效，字幕不是这个视频的 |
| 没设 `DEEPSEEK_API_KEY` 又没加 `--skip-mindmap` | **开跑前就退出**并告诉你两个选项，不会跑到一半才炸、也不会静默降级 |
| 脑图那步 402 Insufficient Balance | DeepSeek 账户没余额了。加 `--skip-mindmap` 仍可得 srt + 阅读版 |
| 脑图正文为空 | `reasoning_effort` 没关，token 被思考吃光 |
| PDF 里中文搜不到 | 字体把字映射到康熙部首区了，换回 Noto Sans SC |
| PDF 生成抛 TypeError | 标题里有 emoji 且没走 `pdftext.safe()` |
| 分 P 视频被跳过 | 嚼这条只处理单 P |

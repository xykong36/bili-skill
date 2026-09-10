# bili-skills

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code Plugin](https://img.shields.io/badge/Claude%20Code-Plugin-8A63D2)](https://docs.claude.com/en/docs/claude-code/plugins)
[![Agent Skill](https://img.shields.io/badge/Agent%20Skill-digesting--bilibili--videos-0A9EDC)](skills/digesting-bilibili-videos/SKILL.md)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB)](#先决条件)

**中文** | [English](README.en.md)

> 一个 BV 号进去，一份能读、能搜、能存的东西出来。

一个 Claude Code skill，把 B 站视频变成能存能读的东西。两条并列的工作流：

- **下载** — BV 号 → 正片 mp4 + 封面 + 元信息，带一套真能发现坏文件的完整性校验。
- **嚼** — BV 号 → 官方 AI 字幕 → 阅读版 → 思维导图 OPML → 内容大纲 → 两本可搜索的中文 PDF。

两条工作流**并列，不是流水线**：字幕直接走接口拿、全程不碰 mp4，想要文字不必先下视频。
它们共享同一份 B 站接口封装和同一个 BBDown 登录态，登录一次两边都通。

> 0.4.0 起 `downloading-bilibili-videos` 和 `digesting-bilibili-videos` 合并成后者一个 skill。
> 之前按名字引用前者的地方要改。

## 效果示例

拿到手的是官方 AI 字幕，两秒一断、没有标点、读不了：

```srt
1
00:00:00,040 --> 00:00:02,320
我最近刷到有博主说没背景

2
00:00:02,320 --> 00:00:03,680
没资源的普通人
```

嚼完出来的是「阅读版」，碎句合并成自然段，每段留一个可定位的时间戳：

```markdown
# 赚钱信息差，不会出现在网上

> 全文时长约 15:12 · 共 38 段 · 时间戳为该段起始位置

---

**`[00:00]`** 我最近刷到有博主说没背景没资源的普通人想赚到钱就要提高获取信息差的能力

**`[00:10]`** 知识星球平台还有一些资讯账号等等的渠道那我作为一个创过业并且有多年副业和搞钱经验的人首先这些确实是获取信息差的渠道…
```

同一期 15 分钟的视频：29 KB 的碎字幕 → 14 KB、38 段的读物。
再往下还有 OPML 脑图、内容大纲，以及整批打成的两本可搜索中文 PDF。

走下载那条线，元信息长这样（数字是抓取当时的快照）：

```json
{
  "bvid": "BV1xxxxxxxxxx",
  "aid": 115089587902032,
  "cid": 31937398244,
  "title": "赚钱信息差，不会出现在网上",
  "pubdate": 1756127858,
  "duration": 913,
  "view": 508251,
  "like": 17981,
  "comment_count": 1080,
  "owner": "边大娘FM",
  "owner_mid": 1900638792,
  "desc": "",
  "url": "https://www.bilibili.com/video/BV1xxxxxxxxxx"
}
```

## 安装

```
/plugin marketplace add xykong36/bili-skills
/plugin install bili-skills
```

装完在 Claude Code 里直接说「帮我把这个 B 站视频下下来」或「把这期整理成脑图」就会自动用上。

也可以手动：把 `skills/digesting-bilibili-videos/` 拷进 `~/.claude/skills/`，再把仓库根的 `lib/` 里的文件拷进**这个 skill 自己的 `lib/`**（文件名不冲突）。
注意不是拷到 `~/.claude/skills/lib/` —— 那样 `_paths.py` 找不到 `bili_api.py` 会直接退出。

## 它产出什么

```
out/
├── BV1xxx.mp4                      下载：正片（--no-video 或超体积上限时没有）
├── BV1xxx.jpg                      下载：封面
├── BV1xxx.info.json                下载：bvid/aid/cid/标题/时长/播放/点赞/评论/UP主/简介/链接
├── 20250825-标题-BV1xxx.srt         嚼 1：官方 AI 字幕
├── 20250825-标题-BV1xxx-阅读版.md    嚼 2：合并成自然段
├── 20250825-标题-BV1xxx.opml        嚼 3：脑图
├── 20250825-标题-BV1xxx.source.txt  嚼 3：大纲原文。API 出的或你写的，都在这
├── 20250825-标题-BV1xxx-大纲.md      嚼 4
├── <--name>-mindmap.pdf            嚼 5：整批共一本
└── <--name>-outline.pdf            嚼 5：整批共一本
```

下载那条线默认用光秃秃的 BV 号做文件名，`--stem-title` 换成「日期-标题-BV」；
嚼那条线**一律**用长文件名。

两本 PDF 的名字**只由 `--name` 决定**（默认 `B站合集`），内容**只含本次调用给的那几个 BV**。
所以同一个 `--out` 里用同一个 `--name` 再跑一次，会把上一本静默覆盖掉。

## 工作原理

先自检，缺什么它直接告诉你装什么命令：

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py doctor
```

然后按想要的东西分流：

| 你想要 | 走 | 命令 |
|---|---|---|
| 本地存一份视频 / 封面 / 播放量 | 下载 | `bili.py download BV1xxx --out ./out` |
| 字幕、逐字稿、文章、脑图、大纲、PDF | 嚼 | `bili.py digest BV1xxx --out ./out --name 合集名` |
| 两个都要 | 一条命令 | `bili.py digest BV1xxx --out ./out --with-video` |

（表里为了好读省成了 `bili.py`，实际得写全 `python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py ...`——
`allowed-tools` 那条规则匹配的就是这个完整形式，写短了会多弹一次权限窗。）

嚼分五步，每步都幂等，重跑不会白干：

| 步 | 产出 | 要什么 |
|---|---|---|
| 1. 抓官方 AI 字幕 | `<stem>.srt` | 登录 cookie |
| 2. 合并成自然段 | `<stem>-阅读版.md` | 纯标准库 |
| 3. 整理成脑图 | `<stem>.opml` + `.source.txt` | **agent 自己写**，或一个 API key |
| 4. 渲染大纲 | `<stem>-大纲.md` | 纯本地，秒级 |
| 5. 出两本 PDF | `<名>-mindmap.pdf` / `<名>-outline.pdf` | `fpdf2` `fonttools` |

第 4、5 步吃的都是第 3 步的 opml，所以第 3 步跳过或失败，3/4/5 一起没有——
这是设计内的降级，1、2 步照常出东西。只想要字幕和阅读版就加 `--skip-mindmap`。

### 没有 API key 时的三段式交接

1.0.0 起脑图那步默认**不调 API**，而是交给正在跑这个 skill 的 agent：

```
① bili.py digest BV1 BV2 --out ./out --name 合集名
     出字幕和阅读版，然后打印一份带绝对路径的清单：每期读哪个、写到哪
② agent 自己干：读 assets/mindmap-outline-prompt.md，按它把每期的「阅读版」
     整理成缩进式大纲，写进清单给的 <stem>.source.txt        （这步不跑脚本）
③ bili.py digest BV1 BV2 --out ./out --name 合集名 --build
     读 .source.txt → 脑图 → 大纲 → 两本 PDF
```

退出码：`0` 全成 / `1` 有东西坏了 / `2` 什么都没坏、有几期在等你写大纲。

脑图那步走哪条，脚本在动任何文件之前会先把这张表打出来：

| 环境 | 走哪条 | 谁干活 |
|---|---|---|
| 配了 `DEEPSEEK_API_KEY` / `BILI_LLM_API_KEY` | HTTP | 脚本自己，一条命令跑完 |
| **什么都没配（默认）** | **交接** | **正在跑这个 skill 的 agent** |
| `--mindmap-backend agent` | 交接 | agent（即使配了 key 也不用它） |
| `--skip-mindmap` | 不做 | 没人，3/4/5 步一并没有 |

`OPENAI_API_KEY` **不会**被自动采用——那个变量太多东西在用，得显式 `--mindmap-backend api`。

## 先决条件

| 要什么 | 谁需要 | 怎么装 |
|---|---|---|
| [BBDown](https://github.com/nilaoda/BBDown/releases) | 下载 | 放进 PATH |
| `segno` | 扫码登录（一次性） | `pip install segno`，然后跑 `python3 skills/digesting-bilibili-videos/scripts/bili.py login` 扫码 |
| ffmpeg / ffprobe | 下载（完整性校验） | `brew install ffmpeg` |
| `fpdf2` `fonttools` | 出 PDF 时 | `pip install fpdf2 fonttools` |
| `pypdf` | 只在换字体后自检时 | `pip install pypdf` |
| 一个 OpenAI 兼容 API key | **可选**，生成脑图时 | 不配也能用——脑图那步会交给正在跑 skill 的 agent（Claude Code / Codex / 随便哪个）自己写。想无人值守：`echo 'DEEPSEEK_API_KEY=sk-...' >> .env.local` |

抓字幕、出阅读版、以及整条交接模式的嚼，全程**只用 Python 标准库**。

skill 自带 `scripts/bili.py doctor`，缺什么它会直接告诉你装什么命令。

**Python 3.9+**（已在 3.9 和 3.12 上实测跑通全链路）。

注意一个坑：**agent 沙箱里的 `python3` 可能跟你交互式终端里的不是同一个**。
pyenv / conda 的 shims 靠 shell 启动脚本注入 PATH，而沙箱常常起的是不加载
这些脚本的裸 shell —— 那时 `python3` 会落到系统自带的那个。所以依赖要装在
**跑脚本的那个 python** 里。不确定就先跑 `python3 skills/digesting-bilibili-videos/scripts/bili.py doctor`，
它报什么缺什么就是那个 python 的实情。

## 少弹几次权限窗（可选）

SKILL.md 的 frontmatter 里有一条：

```yaml
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py *), Read
```

它让这个 skill 自己的命令免确认地跑。但这个授权**只在触发 skill 的那一轮有效，
你下一条消息发出去就清空了**（见[官方文档](https://docs.claude.com/en/docs/claude-code/skills#pre-approve-tools-for-a-skill)）。
嚼一期视频要抓字幕、写大纲、出 PDF，通常跨好几轮对话，所以第二轮起会反复弹窗。

想按会话放行，把同一条规则写进 `~/.claude/settings.json`。
注意 `${CLAUDE_SKILL_DIR}` **只在 SKILL.md 正文和 `allowed-tools` 里会被展开**，
settings 里不会，所以这里得填绝对路径。先把它打出来：

```bash
# 装成插件的
ls -d ~/.claude/plugins/cache/bili-skills/bili-skills/*/skills/digesting-bilibili-videos/scripts/bili.py
# 手动拷进 ~/.claude/skills/ 的
ls -d ~/.claude/skills/digesting-bilibili-videos/scripts/bili.py
```

然后：

```json
{
  "permissions": {
    "allow": [
      "Bash(python3 /Users/你/.claude/plugins/cache/bili-skills/bili-skills/1.0.0/skills/digesting-bilibili-videos/scripts/bili.py *)"
    ]
  }
}
```

**别用 `*` 代替版本号。** Bash 规则里出现在子命令（这里就是脚本路径）之前的 `*`
会让规则比你想的宽得多，Claude Code 启动时也会就此警告。代价是插件升级之后
这条要跟着改一次。

## 为什么值得用它，而不是自己写一个

这两条工作流的价值不在代码量，在于代码里那些**只有踩过才知道的判断**：

- B 站的老字幕接口 `x/player/v2` 会**返回别的视频的字幕**（不是截断，是串号），而 `BBDown --sub-only` 走的正是它。实测数据在 [references/subtitle-api.md](skills/digesting-bilibili-videos/references/subtitle-api.md)。
- 判断一个 mp4 完不完整，**比时长是没用的**：faststart 的 mp4 被截断后 ffprobe 报的时长依然是满的，连 `ffmpeg -c copy -f null` 都 rc=0。只有比对最后一个视频包的 pts 才看得出来。
- 下载**不能直接下到 exFAT / 网络盘**：分片合并会把 macOS 的 `._` 伴生文件并进去，产出 `moov atom not found` 的废文件。
- 字幕列表返回空数组有三种含义（没字幕 / 没登录 / 被限流），接口不会告诉你是哪种。
- PDF 里的中文要可搜索，字体不能随便换——很多中文字体会把常用字映射到康熙部首区。

## 为什么用 BBDown 而不是 yt-dlp

两个都能下，yt-dlp 也是合理选择。这里用 BBDown 的实际理由：

- **登录态是共用的**。`scripts/bili.py login` 写下的 `BBDown.data` 就是 BBDown 自己认的那个文件，抓字幕那条工作流也用它去调字幕接口——登录一次两边都通。
- 未登录时 B 站会给 412 风控和低清晰度流；BBDown 自己管这套登录态。

如果你已经在用 yt-dlp 并且跑得好，不必换——但 [references/mp4-integrity.md](skills/digesting-bilibili-videos/references/mp4-integrity.md) 里「怎么判断文件是完整的」那节的结论对两者同样成立。

## 仓库结构

```
bili-skills/
├── .claude-plugin/          插件与 marketplace 清单
├── lib/                     插件级共享库，两条工作流都用
│   ├── bili_api.py          B 站接口薄封装：元信息 + 字幕列表，只用标准库和 curl
│   └── bili_login.py        扫码登录 → 写出 BBDown 认的 BBDown.data
├── evals/                   六份场景，改 SKILL.md 之后拿来验行为没退化
├── tools/check-no-secrets.sh  发布前的凭据体检，命中任何一条即 exit 1
└── skills/digesting-bilibili-videos/
    ├── SKILL.md             skill 本体：路由表、两条工作流、交接协议、产物、FAQ
    ├── scripts/
    │   ├── bili.py          唯一入口：doctor / login / download / digest
    │   ├── download.py      工作流 A：mp4 + jpg + info.json，含 verify_mp4()
    │   ├── digest.py        工作流 B：字幕 → 阅读版 → opml → 大纲 → PDF
    │   ├── doctor.py        依赖自检；canary 探针区分「没字幕」和「没登录/被限流」
    │   └── _common.py       两条工作流共用的原语：BV 正则、safe_title、stem_for
    ├── lib/                 skill 自己的库：srt_to_md / gen_mindmap / pdfbook / pdftext …
    ├── assets/
    │   ├── fonts/           内置 NotoSansSC.ttf（+ OFL.txt），保证 PDF 中文可搜索
    │   └── mindmap-outline-prompt.md  agent 写大纲时照着的那份 prompt
    └── references/          「改这块之前先读」的深入文档
        ├── subtitle-api.md    只有 x/player/wbi/v2 能用，老接口串号的实测数据
        ├── mp4-integrity.md   为什么只有 pts 判据抓得住截断
        ├── pdf-fonts.md       康熙部首区陷阱，换字体后的验证命令
        └── llm-mindmap.md     大纲谁来写、时间戳与正文的格式契约
```

## 改之前先看 evals

`evals/` 里有**六份**场景，用来确认改完 SKILL.md 或脚本之后 agent 的行为没退化：

| 场景 | 防的是 |
|---|---|
| `01-routing-download` | 合并后下载请求还能不能路由到位 |
| `02-routing-digest` | 「download 是 digest 的前置」这个误解；以及产物叫「阅读版」不是「可读版」 |
| `03-empty-subtitles` | 空字幕列表三种含义，别直接说「这个视频没字幕」 |
| `04-mp4-integrity` | 四个直觉判据里三个会放过截断的文件 |
| `05-mindmap-handoff` | 没 API key 时的交接协议：别劝用户买 key、别手搓 opml、收尾要带全 BV |
| `06-source-txt-resume` | 已有 `.source.txt` 时别重新生成一份把它盖掉（那份可能是人手工调过的） |

没有自动 runner。跑法是：开一个干净上下文的 agent，只让它读 `SKILL.md`，
把 `query` 原样丢过去，再对着 `expected_behavior` 逐条比对。
建议至少换两个模型各跑一遍。详见 [evals/README.md](evals/README.md)。

## 隐私

- **`BBDown.data` 等价于你的 B 站登录态**，`.env.local` 里是你的 API key（如果配了）。两个都在 `.gitignore` 里，别提交、别分享。`doctor` 不回显 key 的任何片段。
- 这个 skill 只跟 B 站接口通信；脑图那步默认由**手边的 agent**完成，不额外联网。只有你自己配了 API key 时才会去连那个端点。

## 许可

代码 MIT（见 [LICENSE](LICENSE)）。

内置的 `NotoSansSC.ttf` 按 SIL Open Font License 1.1 分发，许可证副本在字体旁边的 `OFL.txt`。

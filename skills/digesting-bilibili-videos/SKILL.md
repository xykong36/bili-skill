---
name: digesting-bilibili-videos
description: Use when getting a bilibili video's subtitles or transcript, turning a B站/BV号 video into a readable article, mindmap, OPML, outline or PDF, summarizing 哔哩哔哩 video content, or when B站 subtitle requests come back empty or return the wrong video's text
---

# 把 B 站视频嚼成可读的东西

拿 BV 号换回五样东西：字幕 srt、可读版 md、脑图 opml、大纲 md、以及两本可搜索的中文 PDF。

```bash
python3 scripts/doctor.py                      # 先自检
python3 scripts/digest.py BV1xxx --out ./out --name 我的合集
```

## 什么时候用这个 skill

- 要某个 B 站视频的**字幕 / 逐字稿**
- 想把一期视频变成能读的文章、思维导图、内容大纲
- 想把几期打包成一本 PDF 通读
- 抓字幕拿到空结果，或者拿到的字幕内容跟视频对不上

**不适用**：视频本身的下载（用同仓的 `downloading-bilibili-videos`）；没有官方 AI 字幕的视频——**这个 skill 不做语音转录**，遇到就明确报告跳过。

## 五步流水线

每步都幂等，产物在就跳过，可以随时中断续跑。

| 步 | 产出 | 要什么 |
|---|---|---|
| 1. 抓官方 AI 字幕 | `<stem>.srt` | 登录 cookie |
| 2. 合并成自然段 | `<stem>-阅读版.md` | 纯标准库 |
| 3. LLM 整理成脑图 | `<stem>.opml` + `.source.txt` | `DEEPSEEK_API_KEY` |
| 4. 渲染大纲 | `<stem>-大纲.md` | 纯本地，秒级 |
| 5. 出两本 PDF | `<名>-mindmap.pdf` / `<名>-outline.pdf` | `fpdf2` `fonttools` |

**步骤 4 和 5 都以第 3 步的 opml 为输入**，所以第 3 步跳过或失败时，大纲和 PDF 一并没有——这是正常的降级，不是漏做。1、2 两步不受影响，`--skip-mindmap` 仍然能拿到字幕和可读版。

| 想干的事 | 命令 |
|---|---|
| 几期打成一本 | `digest.py BV1 BV2 BV3 --out ./out --name 合集名` |
| 只要字幕和可读版，不花钱 | `--skip-mindmap` |
| 不要 PDF | `--skip-pdf` |
| 已经有 srt 了 | `digest.py --srt a.srt --title 标题 --out ./out` |

## 抓字幕：只能走 `wbi/v2`

**老接口 `x/player/v2` 返回的是别的视频的字幕——不是截断，是串号。BBDown 走的正是老接口，所以 `BBDown --sub-only` 不可信。**

实测：同一个 397 秒的视频，连查老接口三次，拿到 461 条 / 86 条 / 614 条三份**内容完全不相干**的字幕（讲的是英雄联盟和蔡徐坤）；同一时刻查 `wbi/v2` 四次，id、条数、内容完全一致且与视频对得上。完整实测表见 **[references/subtitle-api.md](references/subtitle-api.md)**——改字幕相关代码前必读。

不需要做 wbi 签名，带 Cookie + Referer + 常规 UA 就行（很多实现会去实现那套 md5 签名，实测不必）。

**字幕来源看 URL 的 host，比 `lan` 字段可靠**：`aisubtitle.hdslb.com` 是官方 AI 生成的，`s1.hdslb.com` 是 UP 主自己投稿的人工字幕。两种都能用，但人工字幕不会有 AI 的识别错误，值得在日志里区分出来。

## 空字幕列表有三种含义，别猜

不带 cookie 时接口返回 `code=0` 但 `subtitles` 是**空数组**——静默的空，不是报错。所以拿到空列表可能是：

1. 这个视频确实没有官方 AI 字幕
2. **没登录 / cookie 过期**
3. 被限流

**别直接报告「这个视频没有字幕」。** `doctor.py` 拿一个已知有字幕的 canary 视频探一次就能区分：canary 也拿不到 = 是你的登录态或限流问题，不是视频的问题。

## 两道字幕质量闸门

| 判定 | 阈值 | 处理 |
|---|---|---|
| 字幕比视频长 | > 1.05 倍 | 判串号，**丢弃** |
| 字幕没覆盖完 | < 0.90 | 保留但告警 |

上限那道逮出过 6 期串号字幕，是唯一能自动发现「拿错字幕」的手段。下限不设 1.00 是因为片尾常有无语音段；也别调到 0.7，那会放过漏掉 30% 内容的字幕。

## LLM 那步的代理要按后端裁剪，别一刀切

`gen_mindmap.py` 走 `urllib`，而 **urllib 不支持 socks5**。代理变量是进程级的、子进程默认继承，带着 `socks5://` 就会连不上。

但**别把代理一刀切全剥掉**：在只能靠代理出网的机器上，剥光了反而更糟。实测把代理全剥后用 `--backend claude`，claude CLI 直接拿到 `403 Request not allowed`——它是个普通 HTTPS 客户端，需要那个代理。

所以 `skill_config.env_for_backend()` 是这么分的：deepseek 只剥 `socks*` 开头的代理、保留 http/https 代理；其它后端原样透传。

同类的坑：`reasoning_effort="none"` 是必须的——deepseek-v4-flash 默认开思考会把 `max_tokens` 吃光，返回 `finish_reason=length` 且正文为空。

`--duration` 也必须传：没有它就无法判断「补出来的小时位有没有超出视频长度」，漏写小时位的时间戳修不了，章节顺序会乱。

脑图节点的文本契约是 `<层级编号> [时间戳] 【类型】正文`，六种类型标签 `【观点】【数据】【案例】【金句】【做法】【交锋】` 是下游大纲排版和 PDF 配色的依据，改 prompt 时别动它们。

## PDF：中文必须可搜索

用 `fpdf2` 纯 Python 矢量出书，**不启动 Chrome、不用 markmap、不用 LaTeX**，跨平台结果一致。

- **字体不能随便换**。很多中文字体能正常显示，但会把常用字映射到**康熙部首区**（U+2F00–2FDF），PDF 内搜索和复制就失效了。选定 Noto Sans SC 就是为这个。
- **别用系统字体**。macOS 的 `PingFang.ttc` 和 `Hiragino Sans GB.ttc` 是 PostScript(CFF) 轮廓，很多 PDF 库直接解析不了；`.ttc` 还得指定 subfontIndex。依赖系统字体的话，三个平台出来的 PDF 长得都不一样。所以字体随 skill 自带。
- **肉眼看「中文显示正常」不等于没问题**。字形渲染对了，文本层照样可能是坏的——必须按下面那条抽文本验。
- **换字体后必须验**：抽一页文本，确认该区字符数为 **0**。
  ```bash
  python3 -c "from pypdf import PdfReader; t=''.join(p.extract_text() or '' for p in PdfReader('out/xxx-outline.pdf').pages); print('康熙部首:', sum(0x2F00<=ord(c)<=0x2FDF for c in t))"
  ```
- **变量字体要先定格成静态 TTF**（fpdf2 吃静态最稳）。`pdftext.instance()` 用 fontTools 定格到 400/700 两个字重，缓存在 `~/.cache/bili-skills/fonts/`，只算一次。
- **缺一个字形就能毁掉整本**：fpdf2 遇到字体没有的码位（多半是标题里的 emoji）会在 `encode_text` 抛 `TypeError`。`pdftext.safe()` 按 cmap 静默摘掉未覆盖的字符，测宽和落笔共用同一条路径。

`BILI_SKILLS_FONT` 可以换字体，但换完请按上面那条验一遍。

## 依赖

| 要什么 | 哪步用 | 怎么装 |
|---|---|---|
| curl | 全部 B 站请求 | 系统自带 |
| `BBDown.data` 登录态 | 抓字幕 | 装 BBDown 后 `BBDown login` 扫码 |
| `DEEPSEEK_API_KEY` | 脑图 | `echo 'DEEPSEEK_API_KEY=sk-...' >> .env.local`（`--skip-mindmap` 可绕过） |
| `fpdf2` `fonttools` | PDF | `pip install fpdf2 fonttools`（`--skip-pdf` 可绕过） |

字幕、可读版两步是**纯标准库**的。

`BBDown.data` 等价于你的 B 站登录态，`.env.local` 里是你的 API key。**两个都别提交进任何仓库。**

## 常见问题

| 现象 | 原因 |
|---|---|
| 字幕列表为空 | 见上面「三种含义」，先跑 `doctor.py` |
| 字幕内容跟视频完全不相干 | 走到老接口了。只能用 `wbi/v2` |
| 报「判定串号，已丢弃」 | 上限校验生效，字幕不是这个视频的 |
| 脑图那步 402 Insufficient Balance | DeepSeek 账户没余额了。加 `--skip-mindmap` 仍可得 srt + 可读版 |
| 脑图那步连不上（deepseek） | socks5 代理没剥掉。urllib 不支持 socks5 |
| 脑图那步 403（claude 后端） | 代理被剥过头了。它需要代理才能出网 |
| 脑图正文为空 | `reasoning_effort` 没关，token 被思考吃光 |
| PDF 里中文搜不到 | 字体把字映射到康熙部首区了，换回 Noto Sans SC |
| PDF 生成抛 TypeError | 标题里有 emoji 且没走 `pdftext.safe()` |
| 分 P 视频被跳过 | 本 skill 只处理单 P |

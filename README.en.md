# bili-skill

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-open%20protocol-0A9EDC)](https://docs.claude.com/en/docs/claude-code/skills)
[![Runtimes](https://img.shields.io/badge/runtimes-50%2B-8A63D2)](#install)
[![Skill](https://img.shields.io/badge/skill-digesting--bilibili--videos-555)](SKILL.md)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB)](#what-you-need)

[中文](README.md) | **English**

## Turn bilibili videos into something you can read, search and keep

That row of "watch later" in your favorites — we both know you won't.
And the ones you did watch leave nothing behind: quoting a single line means scrubbing
the timeline three times, and the screenshots you grabbed aren't searchable at all.
**Video is the densest medium of our time, and the least retrievable.**

This is an Agent Skill. Install it into Claude Code (or Cursor / Codex / Gemini CLI —
50+ compatible tools), then just talk to it. No commands to memorize.

<img src="examples/previews/outline-page.png" width="620" alt="outline PDF">

That's what a 14-minute video turns into: 13 sections, 143 points, color-coded by six labels —
`观点` (claim) `数据` (data) `案例` (case) `金句` (quote) `做法` (how-to) `交锋` (clash).
Every timestamp is live — click one and you're back at that second of the video.

> The sample video and all example artifacts are in Chinese, as are the deep-dive documents
> under `references/`. The skill itself works the same way
> whatever language you speak to it in.

---

## One video in, this whole chain out

Sample: [《苹果新CEO凭啥是他？》](https://www.bilibili.com/video/BV1oC5q6BESu)
("Why him as Apple's new CEO?") · by 林亦LYi · 14:09 · 1.05M views
(every file below is in [`examples/`](examples/) — open them right now, nothing to install)

### ① Official AI subtitles → ② a readable article

What bilibili hands you is cue-timing for a player: chopped every two seconds, no punctuation.

```srt
1
00:00:00,240 --> 00:00:01,760
苹果刚过完50岁生日

2
00:00:01,760 --> 00:00:02,720
库克就下车了
```

What you get back:

```markdown
# 苹果新CEO凭啥是他？

> 全文时长约 13:59 · 共 43 段 · 时间戳为该段起始位置

---

**`[00:00]`** 苹果刚过完50岁生日库克就下车了新上任的苹果CEO呢名字叫john turner约翰特努斯
他还是马斯克的宾大同届校友说到宾大呢哇那他的优秀毕业生可就太多了…

**`[00:20]`** 咱们对特努斯的印象大多停留在发布会上这次呢为了深入了解这哥们我又温习了一下
苹果三大名著检索关键词turn他的名字都没出现过…
```

**29 KB of subtitle shards → a 15 KB, 43-paragraph read.** Fourteen minutes, skimmed in two.

Each paragraph keeps one timestamp so you can go back and check: spot a line worth quoting,
jump to `[00:20]` and hear it in the speaker's own words.

### ③ Article → a labeled outline

Not a summary — the speaker's claims pulled apart from the evidence that holds them up:

```markdown
## 2. `[00:43]` 宾大四年：规规矩矩的优等生

- **数据** 1993 年入宾大，主修机械工程与应用力学，辅修心理学
  - *案例* 校游泳队骨干，连续 4 年拿奖
- **数据** 宾大日报搜 Ternus 只有两条结果
  - *案例* 第一条是 94 年游泳夺冠，报道不到两行
  - *案例* 第二条就是官宣接班苹果 CEO 那天
  - **数据** 反观同校马斯克，随手一搜一大长串
- *案例* 绰号 crash：大四差点干废全校唯一一台数控机床
- **交锋** 没有辍学搞发明，也没有车库创业，规规矩矩
  - > "有些人生来便注定撼动世界"
```

Six labels, each chosen by what the line **actually is**:

| `观点` claim | `数据` data | `案例` case | `金句` quote | `做法` how-to | `交锋` clash |
|---|---|---|---|---|---|
| assertion, judgment, conclusion | numbers, ratios, scale | story, first-hand experience | a line worth quoting verbatim | steps, advice, method | question and answer, disagreement |

**One glance tells you which line is the conclusion and which lines hold it up.**
This 14-minute episode came apart into 143 points.

### ④ Outline → mindmap + PDF

<img src="examples/previews/mindmap-full.png" width="420" alt="mindmap PDF, full view">

The whole episode on one page — the page size adapts to the content, so nothing is split or cramped.
Zoomed in:

<img src="examples/previews/mindmap-detail.png" width="720" alt="mindmap PDF, zoomed in">

Vector typesetting, sharp at any zoom, and the Chinese inside the PDF is **searchable and copyable**.
The mindmap also comes as an `.opml` you can drag straight into XMind, MindNode, 幕布 or Freeplane.
Run several episodes together and they share one mindmap book and one outline book.

---

## You say / you get

| You say | You get |
|---|---|
| "download this bilibili video" | mp4 + cover + views, likes and the rest |
| "turn it into something readable" | Markdown with timestamps |
| "make these into mindmaps and a PDF" | outline + OPML + two searchable PDFs |
| "grab the video too while you're at it" | both of the above |
| "check my setup" | what's missing and the exact command to install it |

**You don't have to download a video to get its text** — subtitles come straight off the API
in seconds and cost you no disk. Pass several links at once for a batch; finished work is
recognized and skipped, so an interrupted run just picks up where it stopped.

### What the files look like

```
科技合集/
├── BV1oC5q6BESu.mp4                                       the video
├── BV1oC5q6BESu.jpg                                       cover image
├── BV1oC5q6BESu.info.json                                 title/duration/views/likes/uploader
├── 20260515-苹果新CEO凭啥是他？-BV1oC5q6BESu.srt            raw subtitles
├── 20260515-苹果新CEO凭啥是他？-BV1oC5q6BESu-阅读版.md       the readable article
├── 20260515-苹果新CEO凭啥是他？-BV1oC5q6BESu-大纲.md         the labeled outline
├── 20260515-苹果新CEO凭啥是他？-BV1oC5q6BESu.opml            the mindmap
├── 科技合集-mindmap.pdf                                    one book per batch
└── 科技合集-outline.pdf                                    one book per batch
```

`-阅读版` means "reading edition" and `-大纲` means "outline" — those Chinese suffixes are the
real filenames, so don't translate them when you go looking for the files. Names carry the date
and title, so a folder still makes sense three months later.

The real `info.json`:

```json
{
  "bvid": "BV1oC5q6BESu",
  "title": "苹果新CEO凭啥是他？",
  "owner": "林亦LYi",
  "duration": 849,
  "view": 1050422,
  "like": 26260,
  "desc": "特努斯是谁？他会带苹果走向何方？",
  "url": "https://www.bilibili.com/video/BV1oC5q6BESu"
}
```

The day the video goes down, the title and the numbers from the day you saved it are still yours.

---

## Install

Send your AI this line —

> Install https://github.com/xykong36/bili-skill as a skill for me

Nothing to configure. Just talk to it.

---

## What you need

| What you want to do | What to install |
|---|---|
| Text / articles / outlines / mindmaps | **nothing at all** |
| Download videos | [BBDown](https://github.com/nilaoda/BBDown/releases) + ffmpeg (`brew install ffmpeg`) |
| Emit PDFs | `pip install fpdf2 fonttools` |
| Fetch subtitles the first time | `pip install segno`, then scan the QR code to log into bilibili (once) |

Python 3.9+. Not sure what's missing? Say "check my setup" and it names the exact install command.

---

## Does it cost money? Does it touch my account?

**No money.** Writing the outline is done by the AI you're already talking to — no extra API call.
The subscription you already pay for is enough. (If you want unattended batch runs you *can*
configure an API key, but it's optional.)

**Read-only on your account.** The QR login exists only to fetch subtitles — logged out, bilibili
pretends the video has none. Your login stays on your own machine and is excluded from version
control. The skill talks to bilibili and nowhere else, and never likes, comments or tips on your behalf.

---

## What it can't do

- **No official AI subtitles, no article.** It does not transcribe audio — it tells you plainly which episodes it skipped rather than inventing a transcript.
- **It won't crawl an uploader's entire channel.** It's built for one episode or a handful, not for scraping.
- **Bilibili only.**
- **It doesn't fix wording.** The source is bilibili's own AI subtitle track, recognition errors included ("john turner" up there is one). The skill merges and formats; the timestamps are there so you can check.

---

Want to change it, or read the full behavior spec: [SKILL.md](SKILL.md)
and [references/](references/) (Chinese).

The text artifacts in `examples/` are opening excerpts only. Copyright belongs to the original
creator, [林亦LYi](https://space.bilibili.com/4401694) — watch the full thing
[on bilibili](https://www.bilibili.com/video/BV1oC5q6BESu) and leave a like.

## License

Code is MIT (see [LICENSE](LICENSE)).
The bundled `NotoSansSC.ttf` is distributed under the SIL Open Font License 1.1; a copy sits next to the font as `OFL.txt`.

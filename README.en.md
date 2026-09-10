# bili-skills

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code Plugin](https://img.shields.io/badge/Claude%20Code-Plugin-8A63D2)](https://docs.claude.com/en/docs/claude-code/plugins)
[![Agent Skill](https://img.shields.io/badge/Agent%20Skill-digesting--bilibili--videos-0A9EDC)](skills/digesting-bilibili-videos/SKILL.md)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB)](#prerequisites)

[中文](README.md) | **English**

> One BV id in, something you can read, search and keep out.

A Claude Code skill that turns bilibili videos into things worth keeping. Two parallel workflows:

- **Download** — BV id → the video mp4 + cover image + metadata, with an integrity check that actually catches broken files.
- **Digest** — BV id → official AI subtitles → a readable transcript → an OPML mindmap → a content outline → two searchable Chinese PDFs.

The two workflows are **parallel, not a pipeline**: subtitles come straight off the API and never touch the mp4, so you don't have to download a video to get its text.
They share one bilibili API wrapper and one BBDown login state — log in once, both sides work.

> Since 0.4.0, `downloading-bilibili-videos` and `digesting-bilibili-videos` are merged into the latter.
> Anything that referenced the former by name needs updating.

> Note: the deep-dive documents under `skills/digesting-bilibili-videos/references/` are written in Chinese. The findings they back are summarized in English below.

## What it looks like

What bilibili hands you is the official AI subtitle track — chopped every two seconds, no punctuation, unreadable:

```srt
1
00:00:00,040 --> 00:00:02,320
我最近刷到有博主说没背景

2
00:00:02,320 --> 00:00:03,680
没资源的普通人
```

What comes out is the 阅读版 ("reading edition") — fragments merged into real paragraphs, each keeping one seekable timestamp:

```markdown
# 赚钱信息差，不会出现在网上

> 全文时长约 15:12 · 共 38 段 · 时间戳为该段起始位置

---

**`[00:00]`** 我最近刷到有博主说没背景没资源的普通人想赚到钱就要提高获取信息差的能力

**`[00:10]`** 知识星球平台还有一些资讯账号等等的渠道那我作为一个创过业并且有多年副业和搞钱经验的人首先这些确实是获取信息差的渠道…
```

Same 15-minute episode: 29 KB of subtitle shards → a 14 KB, 38-paragraph read.
Downstream of that you also get an OPML mindmap, a content outline, and two searchable Chinese PDFs covering the whole batch.

On the download side, the metadata looks like this (the counts are a snapshot from when it was fetched):

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

## Install

```
/plugin marketplace add xykong36/bili-skills
/plugin install bili-skills
```

After that, just say "download this bilibili video" or "turn this episode into a mindmap" in Claude Code and the skill kicks in.

Manual install works too: copy `skills/digesting-bilibili-videos/` into `~/.claude/skills/`, then copy the files from this repo's root `lib/` into **that skill's own `lib/`** (no filename collisions).
Not into `~/.claude/skills/lib/` — from there `_paths.py` won't find `bili_api.py` and will exit immediately.

## What it produces

```
out/
├── BV1xxx.mp4                      download: the video (absent with --no-video or over the size cap)
├── BV1xxx.jpg                      download: cover image
├── BV1xxx.info.json                download: bvid/aid/cid/title/duration/views/likes/comments/uploader/desc/url
├── 20250825-title-BV1xxx.srt         digest 1: official AI subtitles
├── 20250825-title-BV1xxx-阅读版.md    digest 2: merged into paragraphs (reading edition)
├── 20250825-title-BV1xxx.opml        digest 3: mindmap
├── 20250825-title-BV1xxx.source.txt  digest 3: the outline text — API-written or agent-written, it lands here
├── 20250825-title-BV1xxx-大纲.md      digest 4: outline
├── <--name>-mindmap.pdf            digest 5: one book per batch
└── <--name>-outline.pdf            digest 5: one book per batch
```

The Chinese suffixes are the real filenames: `-阅读版.md` is the reading edition, `-大纲.md` the outline. Don't translate them when you go looking for the files.

Download names files by bare BV id; `--stem-title` switches to `date-title-BV`. Digest **always** uses the long form.

The two PDFs are named **only** from `--name` (default `B站合集`), and contain **only the BV ids passed in that one invocation**.
Run it again into the same `--out` with the same `--name` and the previous book is silently overwritten.

## How it works

Self-check first — it tells you exactly which install command you're missing:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py doctor
```

Then route by what you actually want:

| You want | Workflow | Command |
|---|---|---|
| A local copy of the video / cover / view count | download | `bili.py download BV1xxx --out ./out` |
| Subtitles, transcript, article, mindmap, outline, PDF | digest | `bili.py digest BV1xxx --out ./out --name BookName` |
| Both | one command | `bili.py digest BV1xxx --out ./out --with-video` |

(The table shortens it to `bili.py` for readability; in practice type the full `python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py ...` — that exact form is what the `allowed-tools` rule matches, and a shorter one costs you an extra permission prompt.)

Digest is five steps, each idempotent, so a re-run never redoes finished work:

| Step | Output | Needs |
|---|---|---|
| 1. Fetch official AI subtitles | `<stem>.srt` | login cookie |
| 2. Merge into paragraphs | `<stem>-阅读版.md` | stdlib only |
| 3. Build the mindmap | `<stem>.opml` + `.source.txt` | **the agent writes it**, or an API key |
| 4. Render the outline | `<stem>-大纲.md` | local, sub-second |
| 5. Emit two PDFs | `<name>-mindmap.pdf` / `<name>-outline.pdf` | `fpdf2` `fonttools` |

Steps 4 and 5 both consume step 3's opml, so if step 3 is skipped or fails, 3/4/5 all drop — that's designed degradation, steps 1 and 2 still deliver. Want only subtitles and the reading edition? `--skip-mindmap`.

### The three-phase handoff when there's no API key

Since 1.0.0 the mindmap step **doesn't call an API by default** — it hands off to whichever agent is running the skill:

```
① bili.py digest BV1 BV2 --out ./out --name BookName
     emits subtitles and reading editions, then prints a worklist of absolute paths:
     which file to read for each episode, and where to write
② the agent does it: read assets/mindmap-outline-prompt.md, follow it to turn each
     reading edition into an indented outline, write it to the <stem>.source.txt
     the worklist named                                    (no script runs here)
③ bili.py digest BV1 BV2 --out ./out --name BookName --build
     reads .source.txt → mindmap → outline → two PDFs
```

Exit codes: `0` all done / `1` something broke / `2` nothing broke, some episodes are waiting on you to write their outline.

Before touching any file, the script prints which backend it picked:

| Environment | Path | Who does the work |
|---|---|---|
| `DEEPSEEK_API_KEY` / `BILI_LLM_API_KEY` set | HTTP | the script itself, one command end to end |
| **nothing set (default)** | **handoff** | **the agent running this skill** |
| `--mindmap-backend agent` | handoff | the agent (even if a key is set) |
| `--skip-mindmap` | skipped | nobody; steps 3/4/5 all drop |

`OPENAI_API_KEY` is **not** picked up automatically — too many other things use that variable, so it takes an explicit `--mindmap-backend api`.

## Prerequisites

| What | Who needs it | How |
|---|---|---|
| [BBDown](https://github.com/nilaoda/BBDown/releases) | download | put it on PATH |
| `segno` | QR login (one-time) | `pip install segno`, then run `python3 skills/digesting-bilibili-videos/scripts/bili.py login` and scan |
| ffmpeg / ffprobe | download (integrity check) | `brew install ffmpeg` |
| `fpdf2` `fonttools` | when emitting PDFs | `pip install fpdf2 fonttools` |
| `pypdf` | only for the self-check after swapping fonts | `pip install pypdf` |
| An OpenAI-compatible API key | **optional**, for the mindmap step | Works without one — the mindmap step hands off to whatever agent is running the skill (Claude Code / Codex / anything). For unattended runs: `echo 'DEEPSEEK_API_KEY=sk-...' >> .env.local` |

Fetching subtitles, producing the reading edition, and the entire digest chain in handoff mode use **nothing but the Python standard library**.

The skill ships `scripts/bili.py doctor`, which names the exact install command for whatever is missing.

**Python 3.9+** (the full chain has been run on both 3.9 and 3.12).

One trap worth knowing: **the `python3` inside an agent sandbox may not be the one in your interactive terminal.**
pyenv / conda shims get onto PATH through shell startup scripts, and sandboxes often launch a bare shell that doesn't load them — at which point `python3` falls back to the system one. So install dependencies into **the python that actually runs the script**. When in doubt run `python3 skills/digesting-bilibili-videos/scripts/bili.py doctor` first; whatever it reports missing is the truth for that python.

## Fewer permission prompts (optional)

SKILL.md's frontmatter carries this line:

```yaml
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py *), Read
```

It lets the skill's own commands run without confirmation. But that grant **only holds for the turn that triggered the skill — your next message clears it** (see the [official docs](https://docs.claude.com/en/docs/claude-code/skills#pre-approve-tools-for-a-skill)).
Digesting an episode means fetching subtitles, writing an outline, emitting PDFs — usually several turns — so from the second turn on you get prompted again and again.

To grant it for the whole session, put the same rule in `~/.claude/settings.json`.
Careful: `${CLAUDE_SKILL_DIR}` **is only expanded inside SKILL.md's body and its `allowed-tools`**, never in settings, so you need the absolute path here. Print it first:

```bash
# installed as a plugin
ls -d ~/.claude/plugins/cache/bili-skills/bili-skills/*/skills/digesting-bilibili-videos/scripts/bili.py
# manually copied into ~/.claude/skills/
ls -d ~/.claude/skills/digesting-bilibili-videos/scripts/bili.py
```

Then:

```json
{
  "permissions": {
    "allow": [
      "Bash(python3 /Users/you/.claude/plugins/cache/bili-skills/bili-skills/1.0.0/skills/digesting-bilibili-videos/scripts/bili.py *)"
    ]
  }
}
```

**Don't put `*` where the version number goes.** In a Bash rule, a `*` appearing before the subcommand (here, the script path) makes the rule far broader than you intended, and Claude Code warns about it at startup. The price is that you re-edit this line once after every plugin upgrade.

## Why use this instead of writing your own

The value of these two workflows isn't the line count — it's the **judgment calls you only learn by getting burned**:

- Bilibili's old subtitle endpoint `x/player/v2` **returns another video's subtitles** (not truncated — wrong video entirely), and `BBDown --sub-only` goes through exactly that endpoint. Measurements in [references/subtitle-api.md](skills/digesting-bilibili-videos/references/subtitle-api.md) (Chinese).
- **Comparing durations tells you nothing** about whether an mp4 is complete: truncate a faststart mp4 and ffprobe still reports the full duration, and even `ffmpeg -c copy -f null` exits 0. Only comparing the last video packet's pts catches it.
- **Never download straight onto exFAT or a network share**: the fragment merge sucks macOS `._` sidecar files into the output and you get a dead file that fails with `moov atom not found`.
- An empty subtitle list means one of three things (no subtitles / not logged in / rate-limited), and the API won't tell you which.
- For Chinese text in a PDF to stay searchable you can't just swap in any font — plenty of Chinese fonts map common characters into the Kangxi Radicals block.

## Why BBDown instead of yt-dlp

Both work, and yt-dlp is a reasonable choice. The practical reasons for BBDown here:

- **The login state is shared.** The `BBDown.data` written by `scripts/bili.py login` is the very file BBDown itself reads, and the subtitle workflow uses it to call the subtitle API — log in once, both sides work.
- Logged out, bilibili serves 412 risk-control responses and low-quality streams; BBDown manages that login state itself.

If you're already on yt-dlp and happy, don't switch — but the "how to tell a file is complete" conclusions in [references/mp4-integrity.md](skills/digesting-bilibili-videos/references/mp4-integrity.md) (Chinese) hold for both.

## Repository layout

```
bili-skills/
├── .claude-plugin/          plugin + marketplace manifests
├── lib/                     plugin-level shared library, used by both workflows
│   ├── bili_api.py          thin bilibili API wrapper: metadata + subtitle list; stdlib and curl only
│   └── bili_login.py        QR login → writes the BBDown.data that BBDown itself accepts
├── evals/                   six scenarios for checking behavior hasn't regressed after a SKILL.md change
├── tools/check-no-secrets.sh  pre-release credential sweep; any hit exits 1
└── skills/digesting-bilibili-videos/
    ├── SKILL.md             the skill itself: routing table, both workflows, handoff protocol, artifacts, FAQ
    ├── scripts/
    │   ├── bili.py          the single entry point: doctor / login / download / digest
    │   ├── download.py      workflow A: mp4 + jpg + info.json, including verify_mp4()
    │   ├── digest.py        workflow B: subtitles → reading edition → opml → outline → PDFs
    │   ├── doctor.py        dependency self-check; a canary probe separates "no subtitles" from "not logged in / rate-limited"
    │   └── _common.py       primitives shared by both workflows: BV regex, safe_title, stem_for
    ├── lib/                 the skill's own libraries: srt_to_md / gen_mindmap / pdfbook / pdftext …
    ├── assets/
    │   ├── fonts/           bundled NotoSansSC.ttf (+ OFL.txt), keeps PDF Chinese searchable
    │   └── mindmap-outline-prompt.md  the prompt the agent follows when writing an outline
    └── references/          "read this before changing that" deep dives (Chinese)
        ├── subtitle-api.md    only x/player/wbi/v2 works; measurements of the old endpoint's wrong-video bug
        ├── mp4-integrity.md   why only the pts criterion catches truncation
        ├── pdf-fonts.md       the Kangxi Radicals trap, and the check to run after swapping fonts
        └── llm-mindmap.md     who writes the outline, and the timestamp/text format contract
```

## Read the evals before you change anything

`evals/` holds **six** scenarios for confirming the agent's behavior hasn't regressed after a change to SKILL.md or the scripts:

| Scenario | Guards against |
|---|---|
| `01-routing-download` | download requests still routing correctly after the merge |
| `02-routing-digest` | the "download is a prerequisite for digest" misreading; and the artifact being 阅读版, not 可读版 |
| `03-empty-subtitles` | the three meanings of an empty subtitle list — don't just say "this video has no subtitles" |
| `04-mp4-integrity` | three of the four intuitive criteria let a truncated file through |
| `05-mindmap-handoff` | the no-API-key handoff protocol: don't push the user to buy a key, don't hand-roll opml, pass every BV on the final `--build` |
| `06-source-txt-resume` | when a `.source.txt` already exists, don't regenerate over it (a human may have edited it by hand) |

There's no automated runner. You run one by opening an agent with a clean context, letting it read only `SKILL.md`, handing it the `query` verbatim, and checking the result against `expected_behavior` item by item.
Run each on at least two different models. Details in [evals/README.md](evals/README.md) (Chinese).

## Privacy

- **`BBDown.data` is equivalent to your bilibili login**, and `.env.local` holds your API key if you configured one. Both are in `.gitignore` — don't commit them, don't share them. `doctor` never echoes any fragment of a key.
- This skill talks only to bilibili's API. The mindmap step is done by **the agent already in front of you** by default, with no extra network call. It only reaches an LLM endpoint if you configured an API key yourself.

## License

Code is MIT (see [LICENSE](LICENSE)).

The bundled `NotoSansSC.ttf` is distributed under the SIL Open Font License 1.1; a copy sits next to the font as `OFL.txt`.

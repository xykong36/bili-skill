# evals

四份场景，用来在改动 SKILL.md 或脚本之后确认 agent 的行为没退化。

## 怎么跑

没有自动 runner（官方也没提供）。做法是开一个**干净上下文**的 agent，
让它**只读** `skills/digesting-bilibili-videos/SKILL.md`，把 `query`
原样给它，然后对着 `expected_behavior` 逐条核对。

至少拿两个不同的模型各跑一遍——弱模型会暴露文档里「你以为写清楚了」
的地方。这个仓之前用 Haiku + Sonnet 各跑过一次（见 commit fc8a548），
当时就是靠这个发现「SKILL.md 没写第 4、5 步依赖第 3 步的 opml」。

之前那次跑完没留下场景，所以第二次改动时无从对照。这个目录就是为了
把场景固化下来。

## 每份在防什么

| 文件 | 防的回归 |
|---|---|
| `01-routing-download.json` | 合并后下载请求还能不能路由到位。description 的下载触发词曾经被整段删掉过 |
| `02-routing-digest.json` | 「download 是 digest 的前置」这个误解；以及产物文件名是「阅读版」不是「可读版」 |
| `03-empty-subtitles.json` | 空字幕列表三种含义，别直接说「这个视频没字幕」 |
| `04-mp4-integrity.json` | 四个直觉判据里三个会放过截断的文件 |

## 字段

`skills` / `query` / `expected_behavior` 用的是官方 evaluation 格式。
`why` 是本仓自己加的：写清这条场景当初是为什么加的，免得以后有人
看不出它在防什么就顺手删了。

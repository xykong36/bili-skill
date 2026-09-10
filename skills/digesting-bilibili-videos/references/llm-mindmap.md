# 脑图那步：思考预算、时间戳、文本契约

`lib/gen_mindmap.py` 和 `lib/skill_config.py` 背后的踩坑结论。

## 内容

- 谁来写大纲（交接协议）
- `reasoning_effort` 必须关
- `--duration` 必须传
- 脑图节点的文本契约
- socks5 代理

## 谁来写大纲（交接协议）

第 3 步不绑任何一家模型。`skill_config.resolve_mindmap()` 前置解析出三条路之一：

| 结果 | 条件 | 谁写大纲 |
|---|---|---|
| `api` | 配了 `DEEPSEEK_API_KEY` / `BILI_LLM_API_KEY`，或显式 `--mindmap-backend api` | 脚本自己发 HTTP |
| `claude` | 只在显式 `--mindmap-backend claude` 时 | `claude -p` 子进程 |
| `agent` | 默认（什么都没配） | **跑这个 skill 的 agent** |

`auto` **永远不会**自己选 `claude`：它只救 Claude、救不了 Codex/workbuddy，跟
「自适应到当前 agent」正相反；而且在 Claude Code 会话里再起一个 `claude -p` 是
嵌套会话，计费和权限都有惊喜。

`OPENAI_API_KEY` 也**不会**被 `auto` 采纳（`_KEYS` 里它的 auto 位是 `False`）。
它在很多机器上是常年导出的、跟本 skill 无关的变量，认它就会出现「用户想让手边的
agent 写大纲，却被一个八竿子打不着的模型静默接管」。

交接的断点是 `<stem>.source.txt`：agent 写进去，`--build` 用 `gen_mindmap.py
--outline` 纯本地解析出 OPML，全程不调模型。`digest.py` 在 agent 模式下**不会**
拉起 `gen_mindmap.py` 子进程——它自己先 resolve，省一次进程往返。

写进去的大纲会过 `digest.outline_smells_bad()` 的体检：行数、tab 缩进、有无缩进、
`[mm:ss]` 密度。**tab 那条最要紧**——`parse()` 只按空格数算缩进，tab 会被当成零
缩进把整棵树压成一层，而且是**静默**的，不体检就只能等 PDF 出来才发现。

## `reasoning_effort` 必须关

`reasoning_effort="none"` 不是可选项。deepseek-v4-flash 默认开思考会把 `max_tokens` 吃光，返回 `finish_reason=length` 且**正文为空**——不报错，就是空的。

**只对 DeepSeek 端点带这个字段。** 它是非标扩展，别家（含 OpenAI 官方）见到未知
字段会直接 400。泛化成「任意 OpenAI 兼容端点」之后，`_outline_api()` 按
`ep["base"]` 含不含 `deepseek`（或 key 来自 `DEEPSEEK_API_KEY`）来决定加不加。

## `--duration` 必须传

没有它就无法判断「补出来的小时位有没有超出视频长度」。漏写小时位的时间戳修不了，章节顺序会乱。

## 脑图节点的文本契约

```
<层级编号> [时间戳] 【类型】正文
```

六种类型标签是固定的：

```
【观点】【数据】【案例】【金句】【做法】【交锋】
```

它们是下游大纲排版（`lib/pdf_content.py` 的 `KINDS`）和 PDF 配色（`ACCENTS`）的依据。**改 prompt 时别动它们**，改了下游会静默失色/错排。

## socks5 代理

`urllib` 不认 socks5。机器上有 `ALL_PROXY=socks5://...` 时，API 那条路会一路超时、
重试三次才报「网络错误」，看着像对面挂了。`skill_config.env_for_backend()` 在
拉起子进程前把 `*_proxy` 里 scheme 是 socks 的项剥掉。

这段逻辑 0.3.0 有过，在两个 skill 合并那次（`78a9916`）连同对应的 SKILL.md 排障行
一起被静默删掉了，1.0.0 补了回来。**别再顺手删它**，它没有测试覆盖，删了要等到
有人在代理环境下跑才会发现。

# bili-skills

一个 Claude Code skill，把 B 站视频变成能存能读的东西。两条并列的工作流：

- **下载** — BV 号 → 正片 mp4 + 封面 + 元信息，带一套真能发现坏文件的完整性校验。
- **嚼** — BV 号 → 官方 AI 字幕 → 阅读版 → 思维导图 OPML → 内容大纲 → 两本可搜索的中文 PDF。

两条工作流**并列，不是流水线**：字幕直接走接口拿、全程不碰 mp4，想要文字不必先下视频。
它们共享同一份 B 站接口封装和同一个 BBDown 登录态，登录一次两边都通。

> 0.4.0 起 `downloading-bilibili-videos` 和 `digesting-bilibili-videos` 合并成后者一个 skill。
> 之前按名字引用前者的地方要改。

## 安装

```
/plugin marketplace add xykong36/bili-skills
/plugin install bili-skills
```

装完在 Claude Code 里直接说「帮我把这个 B 站视频下下来」或「把这期整理成脑图」就会自动用上。

也可以手动：把 `skills/digesting-bilibili-videos/` 拷进 `~/.claude/skills/`，再把仓库根的 `lib/` 里的文件拷进**这个 skill 自己的 `lib/`**（文件名不冲突）。
注意不是拷到 `~/.claude/skills/lib/` —— 那样 `_paths.py` 找不到 `bili_api.py` 会直接退出。

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

## 先决条件

| 要什么 | 谁需要 | 怎么装 |
|---|---|---|
| [BBDown](https://github.com/nilaoda/BBDown/releases) | 下载 | 放进 PATH |
| `segno` | 扫码登录（一次性） | `pip install segno`，然后跑 `python3 skills/digesting-bilibili-videos/scripts/bili.py login` 扫码 |
| ffmpeg / ffprobe | 下载（完整性校验） | `brew install ffmpeg` |
| `fpdf2` `fonttools` | 出 PDF 时 | `pip install fpdf2 fonttools` |
| `pypdf` | 只在换字体后自检时 | `pip install pypdf` |
| 一个 OpenAI 兼容 API key | **可选**，生成脑图时 | 不配也能用——脑图那步会交给正在跑 skill 的 agent（Claude Code / Codex / 随便哪个）自己写。想无人值守：`echo 'DEEPSEEK_API_KEY=sk-...' >> .env.local` |

skill 自带 `scripts/bili.py doctor`，缺什么它会直接告诉你装什么命令。

**Python 3.9+**（已在 3.9 和 3.12 上实测跑通全链路）。

注意一个坑：**agent 沙箱里的 `python3` 可能跟你交互式终端里的不是同一个**。
pyenv / conda 的 shims 靠 shell 启动脚本注入 PATH，而沙箱常常起的是不加载
这些脚本的裸 shell —— 那时 `python3` 会落到系统自带的那个。所以依赖要装在
**跑脚本的那个 python** 里。不确定就先跑 `python3 skills/digesting-bilibili-videos/scripts/bili.py doctor`，
它报什么缺什么就是那个 python 的实情。


## 为什么值得用它，而不是自己写一个

这两个 skill 的价值不在代码量，在于代码里那些**只有踩过才知道的判断**：

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

## 改之前先看 evals

`evals/` 里有四份场景，用来确认改完 SKILL.md 之后 agent 的行为没退化
（路由走对没、文件名说对没、空字幕会不会瞎断言、坏 mp4 判据有没有用错）。
跑法见 [evals/README.md](evals/README.md)。

## 隐私

- **`BBDown.data` 等价于你的 B 站登录态**，`.env.local` 里是你的 API key（如果配了）。两个都在 `.gitignore` 里，别提交、别分享。`doctor` 不回显 key 的任何片段。
- 这个 skill 只跟 B 站接口通信；脑图那步默认由**手边的 agent**完成，不额外联网。只有你自己配了 API key 时才会去连那个端点。

## 许可

代码 MIT（见 [LICENSE](LICENSE)）。

内置的 `NotoSansSC.ttf` 按 SIL Open Font License 1.1 分发，许可证副本在字体旁边的 `OFL.txt`。

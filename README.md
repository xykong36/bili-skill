# bili-skills

两个 Claude Code skill，把 B 站视频变成能存能读的东西。

- **`downloading-bilibili-videos`** — BV 号 → 正片 mp4 + 封面 + 元信息，带一套真能发现坏文件的完整性校验。
- **`digesting-bilibili-videos`** — BV 号 → 官方 AI 字幕 → 可读版 → 思维导图 OPML → 内容大纲 → 两本可搜索的中文 PDF。

两个都可以单独用。它们共享同一份 B 站接口封装和同一个 BBDown 登录态。

## 安装

```
/plugin marketplace add xykong36/bili-skills
/plugin install bili-skills
```

装完在 Claude Code 里直接说「帮我把这个 B 站视频下下来」或「把这期整理成脑图」就会自动用上。

也可以手动：把 `skills/<名>/` 连同仓库根的 `lib/` 拷进 `~/.claude/skills/`。

## 先决条件

| 要什么 | 谁需要 | 怎么装 |
|---|---|---|
| [BBDown](https://github.com/nilaoda/BBDown/releases) | 两个都要 | 放进 PATH，然后 `BBDown login` 扫码登录 |
| ffmpeg / ffprobe | 下载 skill | `brew install ffmpeg` |
| `fpdf2` `fonttools` | 出 PDF 时 | `pip install fpdf2 fonttools` |
| DeepSeek API key | 生成脑图时 | `echo 'DEEPSEEK_API_KEY=sk-...' >> .env.local` |

每个 skill 都有 `scripts/doctor.py`，缺什么它会直接告诉你装什么命令。

## 为什么值得用它，而不是自己写一个

这两个 skill 的价值不在代码量，在于代码里那些**只有踩过才知道的判断**：

- B 站的老字幕接口 `x/player/v2` 会**返回别的视频的字幕**（不是截断，是串号），而 `BBDown --sub-only` 走的正是它。实测数据在 [references/subtitle-api.md](skills/digesting-bilibili-videos/references/subtitle-api.md)。
- 判断一个 mp4 完不完整，**比时长是没用的**：faststart 的 mp4 被截断后 ffprobe 报的时长依然是满的，连 `ffmpeg -c copy -f null` 都 rc=0。只有比对最后一个视频包的 pts 才看得出来。
- 下载**不能直接下到 exFAT / 网络盘**：分片合并会把 macOS 的 `._` 伴生文件并进去，产出 `moov atom not found` 的废文件。
- 字幕列表返回空数组有三种含义（没字幕 / 没登录 / 被限流），接口不会告诉你是哪种。
- PDF 里的中文要可搜索，字体不能随便换——很多中文字体会把常用字映射到康熙部首区。

## 隐私

- **`BBDown.data` 等价于你的 B 站登录态**，`.env.local` 里是你的 API key。两个都在 `.gitignore` 里，别提交、别分享。
- 这两个 skill 只跟 B 站接口和你配的 LLM 通信，不上报任何东西。

## 许可

代码 MIT（见 [LICENSE](LICENSE)）。

内置的 `NotoSansSC.ttf` 按 SIL Open Font License 1.1 分发，许可证副本在字体旁边的 `OFL.txt`。

# B 站官方 AI 字幕怎么拿（实测记录）

2026-07-23 实测。动字幕相关代码之前先读这一篇。

## 一句话结论

**只能走 `x/player/wbi/v2`。老接口 `x/player/v2` 返回的是别的视频的字幕——不是截断，是串号。BBDown 走的正是老接口，所以 `BBDown --sub-only` 的输出不可信，不要用它抓字幕。**

BBDown 只用来下视频和提供登录态。

## 老接口有多不可信

`BV1qThvzWEzs`（视频 **397 秒**）。同一个 aid+cid，连查三次 `x/player/v2`：

| 第几次 | 字幕 id | 条数 | 末条时间 | 覆盖率 | 首句 |
|---|---|---|---|---|---|
| 1 | 1588621382986598144 | 461 | 689s | 174% | 嗨互联网 |
| 2 | 1609757497004973824 | 86 | 170s | 43% | 而且他早期帮助维鲁斯打出 |
| 3 | 1605863673824552960 | 614 | 1063s | 268% | 当然是蔡徐坤被软封禁的第 |

三份字幕的 id、长度、内容全都不同，而且**跟这个视频毫无关系**（维鲁斯是英雄联盟英雄）。

同一时刻查 `x/player/wbi/v2`，连查四次：

| 第几次 | 字幕 id | 条数 | 末条时间 | 覆盖率 | 首句 |
|---|---|---|---|---|---|
| 1–4 | 1831969581716098048 | 211 | 391.9s | 99% | 用AI生成的内容有版权吗 |

**id、条数、内容完全一致，且与视频对得上。**

BBDown 因为走老接口，同样不稳定。`BV1U77Y6DEcT`（12 分 03 秒）连跑三次 `--sub-only`：**326 条 / 2053 条（1 小时 1 分）/ 326 条**。

### 造成过的实际损失

第一版实现用 BBDown 抓字幕，扫了某个频道的 50 期，**6 期拿到了别的视频的字幕并被当成主字幕写了进去**（覆盖率 302% / 214% / 186% / 144% / 113% / 112%）。靠「字幕比视频长」这个上限校验才暴露出来。改走 `wbi/v2` 重抓后 6 期全部恢复正常，其余 44 期与新接口内容一致（只差一个 BOM）。

## 正确的链路

```
x/web-interface/view?bvid=<BV>          -> data.aid / data.cid / data.duration
x/player/wbi/v2?aid=<aid>&cid=<cid>     -> data.subtitle.subtitles[]{lan, subtitle_url}
下载 subtitle_url（bcc，JSON）           -> body[]{from: 秒, to: 秒, content: 文本}
```

要点：

- **必须带 cookie**。不带的话接口返回 `code=0` 但 `subtitles` 是**空数组**——静默的空，不是报错。cookie 用 BBDown 登录后写的 `BBDown.data`（在 BBDown 可执行文件旁边；`lib/bili_api.py: cookie_file()` 负责找，`BILI_COOKIE_FILE` 可覆盖）。
- **不用做 wbi 签名**，带 `Cookie` + `Referer: https://www.bilibili.com/video/<BV>` + 常规 UA 就行。
- `subtitle_url` 是**协议相对**的（`//aisubtitle.hdslb.com/...`），要补 `https:`。
- URL 带 `auth_key`，**有时效，别缓存**。
- 一次返回 6 个语种（`ai-zh` / `ai-en` / `ai-ja` / `ai-es` / `ai-pt` / `ai-ar`），只取中文。
- **来源看 URL 的 host**，比 `lan` 字段可靠：`aisubtitle.hdslb.com` = 官方 AI 生成；`s1.hdslb.com` = UP 主投稿的人工字幕（质量通常更好，没有 AI 的识别错误）。
- bcc → srt 的转换见 `lib/srt.py: from_bcc`。

实现在 `lib/bili_api.py` 的 `subtitle_list` / `subtitle_body`，调用方是 `scripts/digest.py: fetch_subtitle`。

## 两道校验

拿到字幕后必须算 `覆盖率 = 最后一条字幕的结束时间 ÷ 视频时长`（`lib/srt.py: last_timestamp`），两头都要卡：

| 判定 | 阈值 | 处理 |
|---|---|---|
| **上限** `MISMATCH_MAX = 1.05` | 字幕比视频还长 | 判定串号，**丢弃字幕** |
| **下限** `COVERAGE_MIN = 0.90` | 字幕没覆盖完 | 保留但**告警**，下游产物会缺一段 |

- **上限那道必须有**：就是它逮出了老接口串号的 6 期。改走新接口后理论上不该再触发，但这是唯一能自动发现「拿错字幕」的手段，别删。
- **下限为什么不是 1.00**：片尾常有几十秒无语音的音乐/挂件段，最后一条字幕本来就不顶到末尾。
- **下限为什么不是 0.70**：那会接受一份漏掉整整 30% 视频的字幕——12 分钟的视频只有 8 分半有字幕也算合格，下游可读版和脑图跟着缺一大段。

两个阈值都可以用环境变量 `BILI_MISMATCH_MAX` / `BILI_COVERAGE_MIN` 覆盖，但改之前先读上面三条理由。

## 排查

| 现象 | 多半是 |
|---|---|
| 字幕列表返回空数组 | 没带 cookie / 登录过期。跑一次 `BBDown login` 刷新 `BBDown.data`，再跑 `doctor.py` |
| 字幕内容跟视频对不上 | 走到老接口了。检查 `PLAYER_API` 是不是被改回 `x/player/v2`，或有人改回用 BBDown 抓 |
| 日志报「判定串号，已丢弃」 | 上限校验生效了。先确认走的是 `wbi/v2` |
| 接口正常但确实没有中文 | 该视频没有官方 AI 字幕——不是所有视频都有。本 skill 到此为止，不做语音转录 |
| 连 canary 都拿不到字幕 | cookie 失效或被限流，不是「这个视频没字幕」。`doctor.py` 就是用来区分这两者的 |

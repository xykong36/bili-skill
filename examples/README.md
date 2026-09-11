# 一期视频的全部产出

这里是 bili-skill 跑完一整条「嚼」工作流之后，一期视频真实留下的东西。
不用装任何东西，点开就能看。

**样本**：[《苹果新CEO凭啥是他？》](https://www.bilibili.com/video/BV1oC5q6BESu) ·
UP 主 [林亦LYi](https://space.bilibili.com/4401694) · 14:09 · BV1oC5q6BESu

> 视频内容版权归原作者。这里放的文字产物**只是开头的节选**，用来展示产物格式，
> 不能也不打算替代原视频——想看完整内容请去 B 站看，顺手点个赞。

## 长什么样

| | |
|---|---|
| ![大纲 PDF](previews/outline-page.png) | **`-outline.pdf`**<br>143 个信息点分成 13 节。`观点` `数据` `案例` `金句` `做法` `交锋` 六种标签各有颜色，每个时间戳可点，直接跳回原视频那一秒。 |
| ![脑图全景](previews/mindmap-full.png) | **`-mindmap.pdf`**<br>整期铺一页。页面尺寸按内容自适应，不切不挤。 |
| ![脑图局部](previews/mindmap-detail.png) | **放大看**<br>矢量排版，放多大都不糊；PDF 里的中文可搜索、可复制。 |

## 文件

| 文件 | 哪一步 | 完整度 |
|---|---|---|
| [`BV1oC5q6BESu.info.json`](BV1oC5q6BESu.info.json) | 下载 | 完整 |
| [`…-BV1oC5q6BESu.srt`](20260515-苹果新CEO凭啥是他？-BV1oC5q6BESu.srt) | 嚼 1：官方 AI 字幕 | 节选前 39 条 |
| [`…-阅读版.md`](20260515-苹果新CEO凭啥是他？-BV1oC5q6BESu-阅读版.md) | 嚼 2：碎句合成自然段 | 节选前 5 段（共 43 段） |
| [`…-BV1oC5q6BESu.opml`](20260515-苹果新CEO凭啥是他？-BV1oC5q6BESu.opml) | 嚼 3：脑图 | 完整，143 个节点 |
| [`…-大纲.md`](20260515-苹果新CEO凭啥是他？-BV1oC5q6BESu-大纲.md) | 嚼 4：内容大纲 | 节选前 3 节（共 13 节） |
| `previews/*.png` | 嚼 5：两本 PDF 的渲染截图 | 见上表 |

`.opml` 可以直接拖进 XMind / MindNode / 幕布 / Freeplane 打开。

**没放的**：正片 `.mp4`（128 MB，太大）、封面 `.jpg`、以及两本 PDF 本身
（那是把整期内容排好版，不适合放在公开仓里）——它们跑一遍就有。

## 自己跑一遍

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py digest BV1oC5q6BESu \
  --out ./out --name 苹果新CEO凭啥是他 --with-video
```

没配 API key 的话，脚本会在出完字幕和阅读版之后停下来，
打印一份清单交给你手边的 agent 去写大纲，写完再跑一次同样的命令加 `--build` 收尾。
完整规则见 [SKILL.md](../skills/digesting-bilibili-videos/SKILL.md)。

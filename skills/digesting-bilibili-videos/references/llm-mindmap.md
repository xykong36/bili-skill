# 脑图那步：思考预算、时间戳、文本契约

`lib/gen_mindmap.py` 和 `lib/skill_config.py` 背后的踩坑结论。

## 内容

- `reasoning_effort` 必须关
- `--duration` 必须传
- 脑图节点的文本契约

## `reasoning_effort` 必须关

`reasoning_effort="none"` 不是可选项。deepseek-v4-flash 默认开思考会把 `max_tokens` 吃光，返回 `finish_reason=length` 且**正文为空**——不报错，就是空的。

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

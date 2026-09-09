#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 SRT 字幕转换为阅读友好的 Markdown 文档。

特点：
- 把大量零碎的字幕片段合并成自然的段落，读起来像文章而不是字幕列表。
- 每个段落开头保留一个时间戳 [MM:SS]（可点击定位视频），并在整体上保留时间信息。
- 合并规则：遇到较长的静音间隔、或句末标点、或段落过长时开始新段落。

用法：
    python3 srt_to_md.py 输入.srt [-o 输出.md] [--title 标题]
    python3 srt_to_md.py            # 无参数时使用脚本内置默认文件
"""

import argparse
import os
import re
import sys

# ---------- 合并参数（可按需微调） ----------
GAP_NEW_PARAGRAPH = 2.0     # 两段字幕之间静音超过该秒数 -> 换段
MAX_PARAGRAPH_CHARS = 120   # 单个段落最大字符数（超过则在合适处断段）
SENTENCE_END = "。！？!?…"    # 句末标点，达到最小长度后遇到则可换段
MIN_CHARS_FOR_SENTENCE_BREAK = 40  # 句末换段所需的最小段落长度


def parse_timestamp(ts):
    """'00:01:02,500' -> 秒(float)"""
    ts = ts.strip().replace(".", ",")
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def format_mmss(seconds):
    """秒 -> '[MM:SS]'（超过一小时则 HH:MM:SS）"""
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def parse_srt(text):
    """解析 SRT，返回 [(start, end, text), ...]"""
    # 兼容 \r\n / \n，按空行分块
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n").strip())
    entries = []
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if not lines:
            continue
        # 找到时间轴行
        time_idx = None
        for i, ln in enumerate(lines):
            if "-->" in ln:
                time_idx = i
                break
        if time_idx is None:
            continue
        start_str, end_str = lines[time_idx].split("-->")
        start = parse_timestamp(start_str)
        end = parse_timestamp(end_str)
        content = " ".join(ln.strip() for ln in lines[time_idx + 1:]).strip()
        if content:
            entries.append((start, end, content))
    return entries


def group_paragraphs(entries):
    """把字幕条目合并成段落，返回 [(start, end, text), ...]"""
    paragraphs = []
    cur_text = ""
    cur_start = None
    cur_end = None
    prev_end = None

    def flush():
        nonlocal cur_text, cur_start, cur_end
        if cur_text.strip():
            paragraphs.append((cur_start, cur_end, cur_text.strip()))
        cur_text = ""
        cur_start = None
        cur_end = None

    for start, end, content in entries:
        if cur_start is None:
            cur_start = start

        # 判断是否在加入本条之前先换段
        gap = (start - prev_end) if prev_end is not None else 0
        long_gap = prev_end is not None and gap >= GAP_NEW_PARAGRAPH
        too_long = len(cur_text) >= MAX_PARAGRAPH_CHARS
        sentence_break = (
            len(cur_text) >= MIN_CHARS_FOR_SENTENCE_BREAK
            and cur_text[-1:] in SENTENCE_END
        )

        if cur_text and (long_gap or too_long or sentence_break):
            flush()
            cur_start = start

        # 拼接（中文之间不加空格，避免多余空格）
        if cur_text and not cur_text.endswith(tuple(SENTENCE_END + "，、；：,;")):
            sep = "" if _is_cjk(cur_text[-1]) and _is_cjk(content[:1]) else ""
            cur_text += sep + content
        else:
            cur_text += content
        cur_end = end
        prev_end = end

    flush()
    return paragraphs


def _is_cjk(ch):
    return bool(ch) and "一" <= ch <= "鿿"


def build_markdown(paragraphs, title):
    lines = []
    lines.append(f"# {title}")
    lines.append("")
    if paragraphs:
        total = paragraphs[-1][1]
        lines.append(f"> 全文时长约 {format_mmss(total)} · 共 {len(paragraphs)} 段 · 时间戳为该段起始位置")
        lines.append("")
    lines.append("---")
    lines.append("")
    for start, end, text in paragraphs:
        lines.append(f"**`[{format_mmss(start)}]`** {text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    default_srt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "字幕-OCR画面识别.srt")

    parser = argparse.ArgumentParser(description="SRT -> 阅读友好 Markdown")
    parser.add_argument("srt", nargs="?", default=default_srt, help="输入 SRT 文件")
    parser.add_argument("-o", "--output", help="输出 Markdown 文件（默认与输入同名 .md）")
    parser.add_argument("--title", help="文档标题（默认取文件所在目录名/文件名）")
    args = parser.parse_args()

    if not os.path.isfile(args.srt):
        sys.exit(f"找不到输入文件：{args.srt}")

    with open(args.srt, encoding="utf-8") as f:
        text = f.read()

    entries = parse_srt(text)
    if not entries:
        sys.exit("未解析到任何字幕条目。")

    paragraphs = group_paragraphs(entries)

    if args.title:
        title = args.title
    else:
        # 优先用所在目录名（视频标题），否则用文件名
        parent = os.path.basename(os.path.dirname(os.path.abspath(args.srt)))
        title = parent or os.path.splitext(os.path.basename(args.srt))[0]

    md = build_markdown(paragraphs, title)

    out = args.output or os.path.splitext(args.srt)[0] + "-阅读版.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"✅ 已生成：{out}")
    print(f"   原始字幕 {len(entries)} 条 -> 合并为 {len(paragraphs)} 段")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""srt 的小工具（原 srt_last_timestamp.py，改成可 import 的形式）。"""
import re

TS = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{3})")


def _stamp(t):
    """秒(float) -> SRT 的 HH:MM:SS,mmm。"""
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def from_bcc(body):
    """B站字幕接口给的是 bcc(JSON)：[{from: 秒, to: 秒, content: 文本}, ...]。转成 srt 文本。"""
    out = []
    for e in body:
        text = (e.get("content") or "").strip()
        if not text:
            continue
        out.append(f"{len(out) + 1}\n"
                   f"{_stamp(e['from'])} --> {_stamp(e['to'])}\n{text}\n")
    return "\n".join(out)


def last_timestamp(path):
    """最后一条字幕的结束时间(秒)，用来判断字幕是否覆盖了完整视频。"""
    last = 0.0
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = TS.search(line)
            if m:
                h, mi, s, ms = (int(x) for x in m.group(5, 6, 7, 8))
                last = max(last, h * 3600 + mi * 60 + s + ms / 1000)
    return last


def longest_repeat_run(path):
    """最长的连续重复字幕条数——whisper 幻觉循环的特征。"""
    texts, buf = [], []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                if buf:
                    texts.append(" ".join(buf[2:]) if len(buf) > 2 else "")
                buf = []
            else:
                buf.append(line)
    if buf:
        texts.append(" ".join(buf[2:]) if len(buf) > 2 else "")
    texts = [t for t in texts if t]
    best, best_text, i = 0, "", 0
    while i < len(texts):
        j = i
        while j + 1 < len(texts) and texts[j + 1] == texts[i]:
            j += 1
        if j - i + 1 > best:
            best, best_text = j - i + 1, texts[i]
        i = j + 1
    return best, best_text

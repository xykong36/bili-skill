#!/usr/bin/env python3
"""内容大纲的**内容模型**：`【类型】` 标签怎么拆、怎么配色，以及 Markdown 输出。

不用"章节 / 论点 / 论据"三档固定缩进把所有内容压成同一个形状，而是按标签分流——
观点、数据、案例、金句、做法、交锋各有各的视觉语言，一章下面是三条案例还是一问一答，
读大纲的时候直接看得出来。没有标签的节点（模型漏标、或历史存量 OPML）走朴素缩进，不报错。

这里只管**内容怎么拆、配什么色**，不管怎么画。Markdown（本模块的 `to_markdown`）
和 PDF（`pdfbook.py`）共用这一份定义——两边各抄一套的话，标签表、正则、拆分函数会
逐字重复十几处，改一处就得记着改另一处。
"""
import re

from lib import opml_lib as L

# 标签 -> 主色。显示名就是标签本身，不再另设一列。
KINDS = {
    "观点": "#1d4ed8",
    "数据": "#b45309",
    "案例": "#4b5563",
    "金句": "#7c3aed",
    "做法": "#047857",
    "交锋": "#be123c",
}
TAG_RE = re.compile(r"^[【\[]\s*(" + "|".join(KINDS) + r")\s*[】\]]\s*(.*)$", re.S)

# 章节强调色，按章序轮用
ACCENTS = ["#2563eb", "#059669", "#d97706", "#dc2626", "#7c3aed",
           "#0891b2", "#db2777", "#65a30d", "#4f46e5", "#ea580c"]

# 数据类里要挑出来高亮的数字
NUM_RE = re.compile(r"\d+(?:[.,:]\d+)*\s*[%％×倍万亿兆kKmMbB]?")
NUM_STYLE = {"b": True, "c": "#92400e", "hl": "#fef3c7", "nb": True}


def split_tag(text):
    """`【数据】xxx` -> ('数据', 'xxx')；没标签返回 ('', 原文)。"""
    m = TAG_RE.match(text)
    return (m.group(1), m.group(2).strip()) if m else ("", text)


QUOTE_CHARS = re.compile(r'[“”"]')


def strip_quotes(text):
    """金句的引号一律由排版来加。

    模型自己也会加，而且常常不是加在两头。只剥两端会剩下一个孤零零的 `”`，
    所以把 `“ ” "` 全清掉。`’` 不能清——英文里那是 we're / body's 的撇号。
    """
    return QUOTE_CHARS.sub("", text).strip()


def split_qa(text):
    """交锋类拆成 (提问, 回应)。作者/模型常用 —— / -> / ：来分隔，没有就整条当提问。"""
    for sep in ("——", "→", "->", "｜", "|", "：", ":"):
        if sep in text:
            q, a = text.split(sep, 1)
            if len(q.strip()) > 3 and len(a.strip()) > 3:
                return q.strip(), a.strip()
    return text, ""


def split_num(text):
    """`2.1 正文` -> ('2.1', '正文')。章节级的编号/时间戳用 opml_lib.split_meta。"""
    m = re.match(r"^([\d.]+)\s+(.*)$", text, re.S)
    return (m.group(1), m.group(2)) if m else ("", text)


def hi_numbers(text, base_color):
    """数字挑出来高亮，返回 [(文字, 样式)] 的 span 列表给排版层用。

    先按数字切段再逐段处理，避免把已经切出来的片段二次匹配。
    """
    spans, pos = [], 0
    for m in NUM_RE.finditer(text):
        if m.start() > pos:
            spans.append((text[pos:m.start()], {"c": base_color}))
        spans.append((m.group(0), dict(NUM_STYLE)))
        pos = m.end()
    if pos < len(text):
        spans.append((text[pos:], {"c": base_color}))
    return spans or [(text, {"c": base_color})]


# ---------- Markdown 版（每期单独保存一份） ----------
MD_PREFIX = {"观点": "**观点** ", "数据": "**数据** ", "做法": "**做法** ",
             "案例": "*案例* ", "交锋": "**交锋** "}


def same_title(a, b):
    """比对标题时忽略安全化替换掉的那些字符（`:` -> `_` 之类）。"""
    norm = str.maketrans({c: "" for c in '/\\:*?"<>|_ 　'})
    return (a or "").translate(norm) == (b or "").translate(norm)


def to_markdown(display_title, subtitle, root_title, nodes):
    """OPML -> 单期大纲 Markdown。和 PDF 那本用同一套标签语义，只是换了载体。

    不做 `English ｜ 中文` 的双语拆分（youtube 那边有）：B站标题里的 `｜` 是正常
    标点（`AI时代…｜孙宇`），照双语拆会把章节标题从中间劈成两半。
    """
    head = subtitle if same_title(root_title, display_title) \
        else f"{subtitle}　·　{root_title}"
    out = [f"# {display_title}", "", f"> {head}", ""]

    def emit(items, depth):
        for nd in items:
            num, ts, txt = L.split_meta(nd["text"])
            if depth == 0:
                out.extend(["", f"## {num}. " + (f"`[{ts}]` " if ts else "") + txt, ""])
            else:
                kind, body = split_tag(txt)
                pad = "  " * (depth - 1)
                if kind == "金句":
                    # 引用块写在列表项里面，不然前后的空行会把这一章的列表切成两截
                    out.append(f"{pad}- > “{strip_quotes(body)}”")
                elif kind == "交锋":
                    q, a = split_qa(body)
                    out.append(f"{pad}- **交锋** {q}")
                    if a:
                        out.append(f"{pad}  ↳ {a}")
                else:
                    out.append(f"{pad}- {MD_PREFIX.get(kind, '')}{body}")
            emit(nd["children"], depth + 1)

    emit(nodes, 0)
    return "\n".join(out).rstrip() + "\n"

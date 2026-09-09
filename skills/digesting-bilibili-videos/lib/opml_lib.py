"""OPML 解析 + Markdown/HTML 生成的共用逻辑。"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def load(path):
    """返回 (标题, 根节点列表)；节点为 {'text': str, 'children': [...]}。"""
    tree = ET.parse(path)
    root = tree.getroot()

    def walk(el):
        return [
            {"text": (o.get("text") or "").strip(), "children": walk(o)}
            for o in el.findall("outline")
        ]

    body = walk(root.find("body"))
    head = root.find("head/title")
    title = (head.text or "").strip() if head is not None else ""

    # 绝大多数文件的 body 下只有一个根节点，其文本即导图中心主题
    if len(body) == 1:
        return (body[0]["text"] or title or path.stem), body[0]["children"]
    return (title or path.stem), body


def opml_files(src):
    """目录下的 opml，跳过 macOS 在 exFAT 上留的 ._ 资源分支文件。"""
    return sorted(
        (p for p in Path(src).glob("*.opml") if not p.name.startswith("._")),
        key=lambda p: p.name,
    )


def count_nodes(nodes):
    return len(nodes) + sum(count_nodes(n["children"]) for n in nodes)


# `<` 必须转义：markmap 走 markdown-it 且开着 inline HTML，节点文字里的
# `<token>`/`<id>` 会被当成未闭合标签，把后面整段嵌套 <ul> 子列表吞进自己的
# content，导致渲染出的节点数少于 OPML 节点数（进而卡死 inject.js 的等待条件）。
MD_ESC = re.compile(r"([\\`*_~<>])")


def md_escape(s):
    return MD_ESC.sub(r"\\\1", s)


def to_markdown(title, nodes):
    """深度 0 -> ##，深度 1 -> 列表，更深 -> 嵌套列表。"""
    out = [f"# {md_escape(title)}", ""]

    def emit(items, depth):
        for it in items:
            txt = md_escape(it["text"])
            if depth == 0:
                out.extend(["", f"## {txt}", ""])
            else:
                out.append("  " * (depth - 1) + f"- {txt}")
            emit(it["children"], depth + 1)

    emit(nodes, 0)
    return "\n".join(out) + "\n"


TIME_RE = re.compile(r"^\s*([\d.]+)?\s*\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*")
NUM_RE = re.compile(r"^\s*([\d.]+)\s+")


def to_sec(ts):
    """`mm:ss` / `h:mm:ss` -> 秒。fmt_duration 的逆运算。"""
    if not ts:
        return None
    p = [int(x) for x in ts.split(":")]
    return p[0] * 60 + p[1] if len(p) == 2 else p[0] * 3600 + p[1] * 60 + p[2]


def fmt_duration(sec):
    """秒 -> `h:mm:ss` / `mm:ss`，给大纲的副标题用。"""
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def split_meta(text):
    """拆出 (编号, 时间戳, 正文)，便于排版时分列显示。"""
    num = ts = ""
    m = NUM_RE.match(text)
    if m:
        num = m.group(1)
        text = text[m.end():]
    m = re.match(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*", text)
    if m:
        ts = m.group(1)
        text = text[m.end():]
    return num, ts, text.strip()

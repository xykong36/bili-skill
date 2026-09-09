#!/usr/bin/env python3
"""OPML -> 频道汇总 PDF（思维导图一本 + 内容大纲一本）。

纯 Python 矢量输出：不用 Chrome、不用 markmap、不用 pypdf，字体随仓库自带，
所以 macOS / Linux / Windows 出的结果一致，服务器上也能直接跑。

一本书用一个 FPDF 实例画完 —— 字体子集只内嵌一次，书签用 fpdf2 原生的
start_section，不需要先渲一遍数页码再合并那套机器。

大纲部分**保留 bilibili 的深层结构**（章节→论点→论据），并在此之上按节点的
`【类型】` 标签着色排版：递归下钻每一级，有标签走类型排版、无标签走朴素缩进。
同一份深层 OPML 同时喂两本——导图保持原有密度，大纲获得类型色彩。
"""
import shutil
import sys
from pathlib import Path

from fpdf import FPDF

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import opml_lib as L
from lib import pdf_content as O
from lib import pdftext as T


# ---------- 原片链接 ----------
LINK = "#1a56db"
PLAY = "▶ "        # U+25B6。Noto Sans SC 有这个字形；`►`/`▸`/`⏱`/`🔗` 都没有。

to_sec = L.to_sec           # 时间戳解析只此一份，见 lib/opml_lib.py


def video_url(bvid, sec=None):
    """原片播放链接；给了秒数就追加 `?t=<秒>`，B 站播放器直接定位到那一刻。"""
    if not bvid:
        return ""
    u = f"https://www.bilibili.com/video/{bvid}"
    return f"{u}?t={int(sec)}" if sec else u


def short_url(bvid):
    """印在纸上的显示形式，不参与跳转（跳转一律用 video_url）。"""
    if not bvid:
        return ""
    return f"bilibili.com/video/{bvid}"


# ---------- 思维导图：形制沿用 markmap，单位换成 pt ----------
PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
           "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]  # d3.schemeCategory10
INK = "#20242b"
SPACING_H, SPACING_V = 75.0, 10.5      # 父子横向间距 / 兄弟纵向间距
PAD_X, MARGIN, HDR_H = 10.5, 42.0, 54.0
FS, LH = 9.75, 1.45                    # 节点字号 / 行高倍数

# ---------- 内容大纲：A4 版心 ----------
L_MARGIN, R_MARGIN, T_MARGIN, B_MARGIN = 42, 45, 42, 44


# ---------- 链接原语（两本书共用） ----------
def _ts_url(vid, node_text):
    """节点文字里带 `[01:02]` 就换算成带 `?t=` 的链接，否则空串。"""
    if not vid:
        return ""
    _num, ts, _txt = L.split_meta(node_text)
    return video_url(vid, to_sec(ts)) if ts else ""


def _link_line(pdf, x, y, vid, size, sec=None):
    """一行可点的原片短链 `▶ bilibili.com/video/<BV>`。

    基线与 `pdftext.flow` 同口径（`y + size * 0.82`），返回值也和它一样是排完后的 y。
    """
    s = T.safe(PLAY + short_url(vid))
    T.text_at(pdf, x, y + size * 0.82, s, size, LINK)
    pdf.link(x, y, T.width(s, size), size * 1.15, video_url(vid, sec))
    return y + size * 1.5


_same = O.same_title      # 和 Markdown 那版共用一份定义，见 pdf_content.py


# ============ 思维导图 ============
class Node:
    __slots__ = ("text", "children", "lines", "w", "h", "x", "y", "color", "sub_h",
                 "link")

    def __init__(self, text, children):
        self.text, self.children = text, children
        self.link = ""


def _build(items, maxw, vid=""):
    out = []
    for it in items:
        n = Node(it["text"], _build(it["children"], maxw, vid))
        n.lines = T.wrap_text(n.text, maxw, FS)
        n.w = max(T.width(ln, FS) for ln in n.lines) + PAD_X * 2
        n.h = len(n.lines) * FS * LH + 6
        # 有时间戳的节点整块做成热区
        n.link = _ts_url(vid, n.text)
        out.append(n)
    return out


def _layout(node, x):
    """先算子树高、再把父节点竖直居中于子树区间 —— 等价于 markmap 的纵向堆叠。"""
    node.x = x
    for c in node.children:
        _layout(c, x + node.w + SPACING_H)
    if node.children:
        node.sub_h = max(node.h, sum(c.sub_h for c in node.children)
                         + SPACING_V * (len(node.children) - 1))
    else:
        node.sub_h = node.h


def _place(node, top):
    node.y = top + node.sub_h / 2
    if node.children:
        inner = (sum(c.sub_h for c in node.children)
                 + SPACING_V * (len(node.children) - 1))
        y = top + (node.sub_h - inner) / 2
        for c in node.children:
            _place(c, y)
            y += c.sub_h + SPACING_V


def _paint(node, depth, color):
    """一级章节各占一个颜色，其子树继承 —— markmap 的 colorFreezeLevel:2。"""
    node.color = color
    for i, c in enumerate(node.children):
        _paint(c, depth + 1, PALETTE[(i + 1) % len(PALETTE)] if depth == 0 else color)


def _walk(node):
    yield node
    for c in node.children:
        yield from _walk(c)


def _bezier(pdf, x0, y0, x1, y1, seg=28):
    """三次贝塞尔用折线逼近 —— 仍是矢量，段数够密肉眼看不出。"""
    dx = (x1 - x0) * 0.5
    cx0, cx1 = x0 + dx, x1 - dx
    px, py = x0, y0
    for i in range(1, seg + 1):
        t = i / seg
        u = 1 - t
        bx = u**3 * x0 + 3 * u * u * t * cx0 + 3 * u * t * t * cx1 + t**3 * x1
        by = u**3 * y0 + 3 * u * u * t * y0 + 3 * u * t * t * y1 + t**3 * y1
        pdf.line(px, py, bx, by)
        px, py = bx, by


def mindmap_page(pdf, ent):
    """一期一页，页面按导图自然尺寸开。"""
    root_title, items = L.load(ent["opml"])
    vid = ent.get("bvid") or ""
    n = L.count_nodes(items)
    maxw = 225.0 if n < 60 else (270.0 if n < 140 else 315.0)

    root = Node(root_title, _build(items, maxw, vid))
    root.link = video_url(vid)                # 中心主题 -> 整片，不带时间点
    root.lines = T.wrap_text(root.text, maxw, FS)
    root.w = max(T.width(ln, FS) for ln in root.lines) + PAD_X * 2
    root.h = len(root.lines) * FS * LH + 6
    _layout(root, 0)
    _place(root, 0)
    _paint(root, 0, PALETTE[0])

    nodes = list(_walk(root))
    x0 = min(nd.x for nd in nodes)
    y0 = min(nd.y - nd.h / 2 for nd in nodes)
    W = max(nd.x + nd.w for nd in nodes) - x0 + 2 * MARGIN
    H = max(nd.y + nd.h / 2 for nd in nodes) - y0 + 2 * MARGIN + HDR_H

    pdf.add_page(format=(W, H))
    pdf.start_section(ent["title"][:60], level=0)
    ox, oy = MARGIN - x0, MARGIN - y0 + HDR_H

    T.text_at(pdf, 18, 30, ent["title"], 14.25, "#111827", bold=True)
    T.text_at(pdf, 18, 46.5, ent["subtitle"], 9.4, "#6b7280")
    if vid:                                   # 副标题尾巴上接一段可点短链
        sx = 18 + T.width(T.safe(ent["subtitle"]), 9.4)
        T.text_at(pdf, sx, 46.5, " · ", 9.4, "#6b7280")
        _link_line(pdf, sx + T.width(" · ", 9.4), 46.5 - 9.4 * 0.82, vid, 9.4)
    pdf.set_draw_color(*T.rgb("#e5e7eb"))
    pdf.set_line_width(0.75)
    pdf.line(18, HDR_H - 9, W - 18, HDR_H - 9)

    for nd in nodes:                            # 连线先画，压在节点下面
        pbx, pby = nd.x + nd.w + ox, nd.y + nd.h / 2 + oy
        pdf.set_line_width(1.1)
        for c in nd.children:
            pdf.set_draw_color(*T.rgb(c.color))
            _bezier(pdf, pbx, pby, c.x + ox, c.y + c.h / 2 + oy)

    for nd in nodes:
        x, ytop = nd.x + ox, nd.y - nd.h / 2 + oy
        for i, ln in enumerate(nd.lines):
            T.text_at(pdf, x + PAD_X, ytop + (i + 1) * FS * LH - 2.5, ln, FS, INK)
        bar = nd.y + nd.h / 2 + oy
        pdf.set_draw_color(*T.rgb(nd.color))
        pdf.set_line_width(1.2)
        pdf.line(x, bar, x + nd.w, bar)
        if nd.children:                          # 有子节点的末端点个实心圆
            pdf.set_fill_color(*T.rgb(nd.color))
            pdf.ellipse(x + nd.w - 3.75, bar - 3.75, 7.5, 7.5, style="F")
        if nd.link:                              # 热区正好是节点框，布局本来就不重叠
            pdf.link(x, ytop, nd.w, nd.h, nd.link)
    return n


# ============ 内容大纲 ============
def _ensure(pdf, need):
    """页尾不够放下 need pt 就翻页，别把一条要点劈成两半。"""
    if pdf.get_y() + need > pdf.h - B_MARGIN:
        pdf.add_page()


def _pill(pdf, x, y, kind, color):
    """类型徽标：实心圆角块 + 白字。返回右边界。"""
    w = T.width(kind, 7.6, True) + 8
    pdf.set_fill_color(*T.rgb(color))
    pdf.rect(x, y + 1, w, 11.5, style="F", round_corners=True, corner_radius=2)
    T.text_at(pdf, x + 4, y + 9.6, kind, 7.6, "#ffffff", bold=True)
    return x + w + 6


def _indent(depth):
    """论点/论据的左缩进随层级递增，深到一定程度封顶免得挤没版心。"""
    return min(46 + (depth - 1) * 15, 118)


def _chapter_head(pdf, num, ts, body, ac, vid=""):
    """章节头：淡色渐变底 + 左侧强调条 + 时间戳描边框 + 标题。

    时间戳那个描边框正好是现成的链接把手：能跳转时染成链接色并登记热区，
    没有 vid 就维持章节强调色。
    """
    url = video_url(vid, to_sec(ts)) if (vid and ts) else ""
    right = pdf.w - R_MARGIN
    tx = L_MARGIN + 12
    spans = [(body, {"b": True, "c": "#1f2328"})]

    head_x = tx + T.width(num, 9, True) + 7 + (T.width(ts, 7.8) + 13 if ts else 0)
    h = T.flow(pdf, head_x, 0, right - head_x, spans, 11, 1.34, draw=False)
    _ensure(pdf, h + 34)

    top = pdf.get_y() + 8
    tint = T.rgb(ac)
    for i in range(20):                          # fpdf2 没有渐变，用竖切片朝白色插值
        k = i / 19
        col = tuple(round(255 - (255 - c) * 0.10 * (1 - k)) for c in tint)
        pdf.set_fill_color(*col)
        sw = (right - L_MARGIN) * 0.62 / 20
        pdf.rect(L_MARGIN + i * sw, top - 3, sw + 0.4, h + 10, style="F")

    cx = tx
    T.text_at(pdf, cx, top + 9.5, num, 9, ac, bold=True)
    cx += T.width(num, 9, True) + 7
    if ts:
        tc = LINK if url else ac
        w = T.width(ts, 7.8) + 7
        pdf.set_draw_color(*T.rgb(tc))
        pdf.set_line_width(0.5)
        pdf.rect(cx, top + 1.5, w, 11, style="D", round_corners=True, corner_radius=2)
        T.text_at(pdf, cx + 3.5, top + 9.4, ts, 7.8, tc)
        if url:
            pdf.link(cx, top + 1.5, w, 11, url)
        cx += w + 6
    bot = max(T.flow(pdf, cx, top - 1.5, right - cx, spans, 11, 1.34), top + 14)

    pdf.set_draw_color(*T.rgb(ac))
    pdf.set_line_width(3)
    pdf.line(L_MARGIN + 1.5, top - 3, L_MARGIN + 1.5, bot + 3)
    pdf.set_y(bot + 6)


def _item(pdf, x, num, kind, body, step):
    """画一条要点（左缘为 x）。六种类型各走各的排版；无标签走朴素缩进。"""
    kc = O.KINDS.get(kind, "#6b7280")
    right = pdf.w - R_MARGIN
    _ensure(pdf, 26)
    y0 = pdf.get_y() + 3

    if kind == "案例":                            # 灰底叙述块，字号收一点、行距放一点
        px = x + 8 + T.width(kind, 7.6, True) + 8 + 6
        end = T.flow(pdf, px, y0 + 3, right - px - 8, [(body, {})],
                     9.8, 1.7, "#52525b", draw=False)
        pdf.set_fill_color(*T.rgb("#f6f7f9"))     # 底色先铺，字后写
        pdf.rect(x, y0, right - x, end - y0 + 4, style="F",
                 round_corners=True, corner_radius=4)
        _pill(pdf, x + 8, y0 + 3, kind, kc)
        T.flow(pdf, px, y0 + 3, right - px - 8, [(body, {})], 9.8, 1.7, "#52525b")
        pdf.set_y(end + 6)

    elif kind == "金句":                          # 紫色引用块，合成斜体 + 引号由排版加
        px = _pill(pdf, x + 11, y0 + 2, kind, kc)
        end = T.flow(pdf, px, y0 + 2, right - px,
                     [("“" + O.strip_quotes(body) + "”", {})],
                     10.4, 1.6, "#5b21b6", italic=True)
        pdf.set_draw_color(*T.rgb("#c4b5fd"))
        pdf.set_line_width(3)
        pdf.line(x + 1.5, y0 + 1, x + 1.5, end + 1)
        pdf.set_y(end + 5)

    elif kind == "做法":                          # 带步骤号的清单
        step[0] += 1
        s = str(step[0])
        pdf.set_fill_color(*T.rgb("#047857"))
        pdf.ellipse(x, y0 + 2, 13, 13, style="F")
        T.text_at(pdf, x + 6.5 - T.width(s, 7.4, True) / 2, y0 + 10.8, s,
                  7.4, "#ffffff", bold=True)
        px = _pill(pdf, x + 18, y0 + 2, kind, kc)
        end = T.flow(pdf, px, y0 + 2, right - px, [(body, {})], 10.2, 1.55, "#065f46")
        pdf.set_y(end + 5)

    elif kind == "交锋":                          # 虚线左框 + 问答两行
        q, a = O.split_qa(body)
        px = _pill(pdf, x + 10, y0 + 2, kind, kc)
        end = T.flow(pdf, px, y0 + 2, right - px,
                     [(q, {"b": True, "c": "#9f1239"})], 10.2, 1.55)
        if a:
            T.text_at(pdf, x + 22, end + 8.5, "→", 10.2, "#fda4af")
            end = T.flow(pdf, x + 34, end + 1, right - x - 34, [(a, {})],
                         10.2, 1.55, "#3f3f46")
        pdf.set_draw_color(*T.rgb("#fda4af"))
        pdf.set_line_width(1.4)
        yy = y0 + 1
        while yy < end:                           # 虚线用短线段拼
            pdf.line(x + 1, yy, x + 1, min(yy + 3, end))
            yy += 5.5
        pdf.set_y(end + 5)

    elif kind == "数据":                          # 正文里的数字高亮
        px = _pill(pdf, x + 9, y0 + 2, kind, kc)
        end = T.flow(pdf, px, y0 + 2, right - px, O.hi_numbers(body, "#3f3f46"),
                     10.2, 1.55)
        pdf.set_y(end + 5)

    elif kind == "观点":                          # 骨干句：实字重 + 一道细左线
        px = _pill(pdf, x + 9, y0 + 2, kind, kc)
        end = T.flow(pdf, px, y0 + 2, right - px, [(body, {"b": True})],
                     10.2, 1.55, "#111827")
        pdf.set_draw_color(*T.rgb("#93b4f8"))
        pdf.set_line_width(2)
        pdf.line(x + 1, y0 + 1, x + 1, end + 1)
        pdf.set_y(end + 5)

    else:                                         # 无标签：朴素缩进（编号 + 正文）
        if num:
            T.text_at(pdf, x, y0 + 10, num, 8, "#9ca3af")
        end = T.flow(pdf, x + 30, y0 + 2, right - x - 30, [(body, {})],
                     9.9, 1.55, "#4b5563")
        pdf.set_y(end + 4)


def _render_children(pdf, nodes, depth, step):
    """递归下钻论点/论据每一级：拆标签、按类型排版、再进子节点。"""
    for nd in nodes:
        _num, _ts, txt = L.split_meta(nd["text"])
        kind, body = O.split_tag(txt)
        _item(pdf, _indent(depth), _num, kind, body, step)
        if nd["children"]:
            _render_children(pdf, nd["children"], depth + 1, step)


def outline_doc(pdf, ent, idx, total):
    """一期的大纲，接着当前页往下画（新一期从新页开始由调用方决定）。"""
    root_title, items = L.load(ent["opml"])
    vid = ent.get("bvid") or ""
    right = pdf.w - R_MARGIN

    T.text_at(pdf, L_MARGIN, pdf.get_y() + 8,
              f"{idx:02d} / {total}　·　{ent['subtitle']}", 8.5, "#8b949e")
    pdf.set_y(pdf.get_y() + 14)
    y = T.flow(pdf, L_MARGIN, pdf.get_y(), right - L_MARGIN,
               [(ent["title"], {"b": True})], 16, 1.35, "#1f2328")
    # OPML 根节点文本就是视频标题，和展示标题基本重合，重复印一遍很吵
    if not _same(root_title, ent["title"]):
        y = T.flow(pdf, L_MARGIN, y + 2, right - L_MARGIN,
                   [(root_title, {})], 9.5, 1.5, "#6b7280")
    if vid:
        y = _link_line(pdf, L_MARGIN, y + 3, vid, 9.5)
    pdf.set_draw_color(*T.rgb("#1f2328"))
    pdf.set_line_width(1.6)
    pdf.line(L_MARGIN, y + 6, right, y + 6)
    pdf.set_y(y + 15)

    for ci, ch in enumerate(items):
        num, ts, body = L.split_meta(ch["text"])
        pdf.start_section(f"{num} {body}"[:60].strip(), level=1)
        _chapter_head(pdf, num, ts, body, O.ACCENTS[ci % len(O.ACCENTS)], vid)
        step = [0]                                # 步骤号每章重新计
        _render_children(pdf, ch["children"], 1, step)


# ============ 成书 ============
KIND_TEXT = {
    "mindmap": ("思维导图汇总", "每期一页，按内容自然尺寸铺开。文字可搜索可复制，放大不糊。"
                "点带时间戳的节点，直接跳到原片对应时间点。"),
    "outline": ("内容大纲汇总", "章节取自作者手写的时间轴，要点按内容类型"
                "（观点/数据/案例/金句/做法/交锋）分别排版，无标签的节点按层级朴素缩进。"
                "点章节的时间戳徽章，直接跳到原片对应时间点。"),
}


def _cover(pdf, name, kind, ents):
    """封面 + 期数清单。跳转靠书签，不再单独算页码。"""
    head, desc = KIND_TEXT[kind]
    pdf.add_page(format="a4")
    right = pdf.w - R_MARGIN
    y = T.flow(pdf, L_MARGIN, T_MARGIN, right - L_MARGIN,
               [(f"{name} · {head}", {"b": True})], 20, 1.3, "#1f2328")
    y = T.flow(pdf, L_MARGIN, y + 6, right - L_MARGIN, [(desc, {})],
               9.5, 1.55, "#4b5563")
    y = T.flow(pdf, L_MARGIN, y + 2, right - L_MARGIN,
               [(f"共 {len(ents)} 期 · 按发布时间倒序（最新在前）· 左侧书签栏可直接跳转"
                 f" · {PLAY}短链与时间戳可点开原片", {})],
               9.5, 1.55, "#6b7280")
    pdf.set_draw_color(*T.rgb("#1f2328"))
    pdf.set_line_width(1.6)
    pdf.line(L_MARGIN, y + 8, right, y + 8)
    pdf.set_y(y + 18)

    for i, e in enumerate(ents, 1):
        if pdf.get_y() > pdf.h - B_MARGIN - 20:
            pdf.add_page(format="a4")
        y0 = pdf.get_y()
        T.text_at(pdf, L_MARGIN, y0 + 9, f"{i:02d}", 8, "#9ca3af")
        T.text_at(pdf, L_MARGIN + 22, y0 + 9, e["pubdate"] and
                  f"{e['pubdate'][:4]}-{e['pubdate'][4:6]}-{e['pubdate'][6:8]}" or "", 8, "#9ca3af")
        end = T.flow(pdf, L_MARGIN + 82, y0, right - L_MARGIN - 130,
                     [(e["title"], {})], 9.5, 1.4, "#1f2328")
        T.text_at(pdf, right - 44, y0 + 9, f"{e['nodes']} 节点", 8, "#9ca3af")
        pdf.set_draw_color(*T.rgb("#f0f1f3"))
        pdf.set_line_width(0.5)
        pdf.line(L_MARGIN, end + 3, right, end + 3)
        pdf.set_y(end + 6)


def _new_pdf(auto_break):
    pdf = FPDF(unit="pt", format="a4")
    T.register(pdf)
    pdf.set_margins(L_MARGIN, T_MARGIN, R_MARGIN)
    pdf.set_auto_page_break(auto_break, margin=B_MARGIN)
    return pdf


def _stale(pdfs, ents):
    """opml 比 PDF 新才重渲。不落缓存文件，比 mtime 就够。"""
    if not all(p.is_file() and p.stat().st_size > 0 for p in pdfs):
        return True
    newest = max((Path(e["opml"]).stat().st_mtime for e in ents), default=0)
    return newest > min(p.stat().st_mtime for p in pdfs)


def render_channel(entries, out_dir, channel_name, log=print, force=False):
    """出两本 PDF，返回 (导图本, 大纲本)；没有 entries 时返回 (None, None)。

    entries 由 digest.collect() 给出，字段：opml(路径字符串)、title、pubdate、bvid、
    nodes、subtitle，已按发布时间排好序。
    """
    if not entries:
        return None, None
    # 文件名用英文（跨平台稳），封面上印的仍是中文（KIND_TEXT）
    mm_pdf = out_dir / f"{channel_name}-mindmap.pdf"
    ol_pdf = out_dir / f"{channel_name}-outline.pdf"

    if not force and not _stale([mm_pdf, ol_pdf], entries):
        log(f"  PDF 已是最新（{len(entries)} 期），跳过")
        return mm_pdf, ol_pdf

    out_dir.mkdir(parents=True, exist_ok=True)

    mm = _new_pdf(auto_break=False)          # 每页尺寸各异，不能自动分页
    _cover(mm, channel_name, "mindmap", entries)
    for e in entries:
        mindmap_page(mm, e)
    _write(mm, mm_pdf)

    ol = _new_pdf(auto_break=True)
    _cover(ol, channel_name, "outline", entries)
    for i, e in enumerate(entries, 1):
        ol.add_page(format="a4")
        ol.start_section(e["title"][:60], level=0)
        outline_doc(ol, e, i, len(entries))
    _write(ol, ol_pdf)

    log(f"  ✓ PDF {len(entries)} 期 · 导图 {mm.pages_count} 页 "
        f"{mm_pdf.stat().st_size / 1024:.0f} KB · "
        f"大纲 {ol.pages_count} 页 {ol_pdf.stat().st_size / 1024:.0f} KB")
    return mm_pdf, ol_pdf


def _write(pdf, dest):
    """先写临时文件再改名：中途失败不会留下半本假成品被增量判断当成最新。"""
    tmp = dest.with_suffix(".tmp")
    pdf.output(str(tmp))
    shutil.move(str(tmp), str(dest))


def main():
    """独立入口：由 digest.run 用装了 fpdf2 的 venv 拉起。

    用法: pdfbook.py <manifest.json> <out_dir> <channel_name>
    manifest.json 就是 collect() 落盘的 entries（含 opml/title/pubdate/bvid/nodes/subtitle）。
    """
    import json
    if len(sys.argv) != 4:
        sys.exit("用法: pdfbook.py <manifest.json> <out_dir> <channel_name>")
    manifest, out_dir, channel_name = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    entries = json.loads(Path(manifest).read_text(encoding="utf-8"))
    render_channel(entries, out_dir, channel_name)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""排版原语：字体、字宽、分词、断行、行内富文本流。

浏览器白送的那几件事，纯 Python 出 PDF 时得自己做：按真实字体度量折行、中文避头尾、
缺字形兜底。这个模块就是那一层，导图和大纲共用同一份——两边各写一套的话，分词规则和
断行规则会悄悄跑偏。

单位一律用 pt，不做 px/pt 来回换算。
"""
import os
import sys
from pathlib import Path

from fpdf import FPDF

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import skill_config

# pdftext 在 <skill>/lib/ 下，assets 即 <skill>/assets
ASSETS = Path(__file__).resolve().parent.parent / "assets"
# BILI_SKILLS_FONT 可换成任意 CJK 变量/静态字体，但换完务必按 SKILL.md
# 「PDF 中文必须可搜索」那节验一遍 ToUnicode 映射。
VAR_FONT = Path(os.environ.get("BILI_SKILLS_FONT",
                               ASSETS / "fonts" / "NotoSansSC.ttf"))
FONT_DIR = skill_config.CACHE / "fonts"   # 静态实例的落盘位置，不进仓库

# 避头尾。收尾标点不落行首、起始括号不留行尾——浏览器默认就这么排。
# 直引号 " ' 可开可闭，两边都不列入，否则会把开引号硬拽到上一行。
NO_LINE_START = set("。，、；：！？）】》」』〕〉”’%…·.,;:!?)]}>")
NO_LINE_END = set("（【《「『〔〈“‘([{<")

# 分词：CJK 逐字断，拉丁按词断。这一份判定两边共用。
# 弯引号也要独立成词：它们码位在拉丁区，不列出来就会和相邻的一起并成
# `”“` 这种双标点 token，避头尾只看得到头一个，尾巴那个仍会留在行尾。
# **`’` 不能列**——英文里那是 we're / body's 的撇号，独立成词就能从词中间断行。
_CJK_PUNCT = "、，。：；！？（）【】《》「」『』〔〕｜—…“”‘"

_measurer = None
_widths = {}
_coverage = None


# ---------- 字体 ----------
def instance(weight=400):
    """变量字体定格到某个字重。fpdf2 吃静态 TTF 最稳，结果落盘复用，只算一次。"""
    out = FONT_DIR / f"NotoSansSC-{weight}.ttf"
    if out.is_file():
        return out
    if not VAR_FONT.is_file():
        raise RuntimeError(f"缺字体 {VAR_FONT}（随仓库自带，别漏同步 assets/）")
    from fontTools import ttLib
    from fontTools.varLib import instancer
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    f = ttLib.TTFont(str(VAR_FONT))
    instancer.instantiateVariableFont(f, {"wght": weight}, inplace=True)
    tmp = out.with_suffix(".tmp")
    f.save(str(tmp))
    tmp.replace(out)                       # 别让半截文件被下一次运行当成缓存
    return out


def register(pdf):
    """给一个 FPDF 实例挂上正文与粗体两个字重。"""
    pdf.add_font("noto", "", str(instance(400)))
    pdf.add_font("noto", "B", str(instance(700)))


def coverage():
    """字体覆盖的码位集合，只算一次。"""
    global _coverage
    if _coverage is None:
        from fontTools import ttLib
        f = ttLib.TTFont(str(instance(400)))
        _coverage = set()
        for t in f["cmap"].tables:
            _coverage |= set(t.cmap.keys())
    return _coverage


def safe(s):
    """丢掉字体里没有的字形。

    fpdf2 遇到缺字形会在 encode_text 里抛 TypeError，一个生僻字就能毁掉整本。
    实际撞上的绝大多数是标题里的 emoji（Noto Sans SC 不含），直接摘掉比换成占位符更干净。
    """
    cov = coverage()
    if all(ord(c) in cov for c in s):
        return s
    return "".join(c for c in s if ord(c) in cov)


# ---------- 度量 ----------
def _mp():
    global _measurer
    if _measurer is None:
        _measurer = FPDF(unit="pt", format=(1000, 1000))
        register(_measurer)
        _measurer.add_page()
    return _measurer


def width(s, size, bold=False):
    """字宽（pt）。按 (字, 字号, 字重) 缓存单字再求和——TTF 无 kerning 时
    get_string_width 本来就是逐字相加，结果一致，但把 O(文本长度²) 降成 O(不同字数)。"""
    c = _widths.setdefault((size, bold), {})
    pdf = None
    total = 0.0
    for ch in s:
        w = c.get(ch)
        if w is None:
            if pdf is None:
                pdf = _mp()
                pdf.set_font("noto", "B" if bold else "", size)
            w = pdf.get_string_width(ch)
            c[ch] = w
        total += w
    return total


# ---------- 分词与断行 ----------
def tokens(text):
    """切成最小的可断单元：CJK 一字一个，拉丁一词一个（空格跟在词尾）。

    缺字形在这里就先摘掉——测宽和落笔共用这一条路径，不然两边看到的文本不一样，
    折行会按"含 emoji 的宽度"算，印出来却少了那几个字形。
    """
    out, buf = [], ""
    for ch in safe(text):
        if ord(ch) > 0x2E80 or ch in _CJK_PUNCT:
            if buf:
                out.append(buf)
                buf = ""
            out.append(ch)
        elif ch == " ":
            out.append(buf + ch)
            buf = ""
        else:
            buf += ch
    if buf:
        out.append(buf)
    return [t for t in out if t]


def break_lines(items, w):
    """贪心折行 + 避头尾。items: [(文字, 宽度, 附带物)]，返回按行分组的同构列表。

    两条禁则都在这里，别在调用方各写一遍：
      - 行首禁则：收尾标点宁可让本行出头一点，也不落到下一行行首
      - 行尾禁则：起始括号不留在行尾，跟着下文一起挪走
    """
    lines, cur, curw = [], [], 0.0
    for it in items:
        t, tw = it[0], it[1]
        # 比的是 token 的首/末**字符**，不是整个 token：中文一字一 token 时两者等价，
        # 但拉丁是整词一个 token（`Mythos“`、`,Day4-5`），拿整串去比永远不命中。
        head = t[0] if t else ""
        if not cur and lines and head in NO_LINE_START:
            # 连着来的收尾标点（`”。`）：前一个被拉回上一行后本行已空，下面的
            # `if cur` 就失效了，第二个照样会独占一行。这里先接住。
            lines[-1].append(it)
            continue
        if cur and curw + tw > w:
            if head in NO_LINE_START:
                cur.append(it)
                lines.append(cur)
                cur, curw = [], 0.0
                continue
            carry = []
            # 留一个 token 兜底：整行都是起始括号时全搬走会留下空行
            while len(cur) > 1 and cur[-1][0].rstrip()[-1:] in NO_LINE_END:
                carry.insert(0, cur.pop())
            lines.append(cur)
            cur, curw = carry, sum(c[1] for c in carry)
            if t == " " and not cur:           # 行首不留空格
                continue
        cur.append(it)
        curw += tw
    if cur:
        lines.append(cur)
    return lines


def wrap_text(text, w, size, bold=False):
    """折成纯文本的若干行（导图节点用）。"""
    items = [(t, width(t, size, bold)) for t in tokens(text)]
    lines = break_lines(items, w)
    return [("".join(t for t, _ in ln)).rstrip() for ln in lines] or [""]


# ---------- 行内富文本 ----------
def flow(pdf, x, y, w, spans, size, lh, color="#3f3f46", italic=False, draw=True):
    """把 [(文字, 样式)] 排进宽 w 的框里，返回排完后的 y。

    样式键：b 粗体 · c 字色 · hl 背景色 · nb 不可断（整块不拆行）
    draw=False 只算高度不落笔，供"先铺底色再写字"的块用。
    """
    items = []
    for text, st in spans:
        if st.get("nb"):
            text = safe(text)                  # 不可断的整块不走 tokens()，兜底得自己来
            items.append((text, width(text, size, st.get("b")), st))
        else:
            items += [(t, width(t, size, st.get("b")), st) for t in tokens(text)]

    while items and not items[0][0].strip():   # 摘掉缺字形后可能留下的行首空格
        items.pop(0)

    lines = break_lines(items, w)
    if not draw:
        return y + len(lines) * size * lh

    for ln in lines:
        # 同样式的连续 token 合成一次落笔。逐 token 画的话中文会一字一个绘图指令，
        # PDF 阅读器提取文本时可能把每个字当成独立一行，跨字搜索就搜不到了。
        runs = []
        for t, tw, st in ln:
            if runs and runs[-1][2] == st:
                runs[-1][0] += t
                runs[-1][1] += tw
            else:
                runs.append([t, tw, st])

        cx = x
        base = y + size * 0.82
        for t, tw, st in runs:
            if st.get("hl"):
                pdf.set_fill_color(*rgb(st["hl"]))
                pdf.rect(cx - 1, y + 0.5, tw + 2, size * 1.15, style="F",
                         round_corners=True, corner_radius=1.6)
            pdf.set_font("noto", "B" if st.get("b") else "", size)
            pdf.set_text_color(*rgb(st.get("c", color)))
            if italic:
                # Noto Sans SC 没有真斜体，合成一个。ax 取正：fpdf2 的 y 轴朝下，
                # 负值会把字顶往左推，斜成反的。
                with pdf.skew(ax=11, x=cx, y=base):
                    pdf.text(cx, base, t)
            else:
                pdf.text(cx, base, t)
            cx += tw
        y += size * lh
    return y


def text_at(pdf, x, y, s, size, color, bold=False):
    """单行落笔（过一遍缺字形兜底）。"""
    pdf.set_font("noto", "B" if bold else "", size)
    pdf.set_text_color(*rgb(color))
    pdf.text(x, y, safe(s))


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 站官方 AI 字幕 -> 阅读版 -> 脑图 OPML -> 大纲 -> 两本中文 PDF。

    bili.py digest BV1xxx [BV2 ...] --out DIR [--name 书名]
    bili.py digest --srt path/to.srt --title 标题 --out DIR

本文件是模块，不是入口 —— 入口在 bili.py。

五步各自幂等：产物在就跳过，可以随时中断续跑。踩坑结论在 SKILL.md。
"""
import os
import subprocess
import sys
from pathlib import Path

import _paths  # noqa: F401  把 <plugin>/lib 和 <skill> 挂上 sys.path
import bili_api
from _common import collect_bvs, fresh, log, safe_title, stem_for
from lib import opml_lib, pdf_content, skill_config, srt as srtlib

LIB = Path(__file__).resolve().parent.parent / "lib"


# ---------- 1. 字幕 ----------
def fetch_subtitle(meta, dest):
    """调 wbi/v2 取中文 AI 字幕写到 dest。返回 True/False。

    两道质量闸门都在这里：串号（字幕比视频长太多）和残缺（覆盖率不够）。
    """
    subs = bili_api.subtitle_list(meta["aid"], meta["cid"], meta["bvid"])
    if not subs:
        # 空列表有三种可能，必须说清楚，否则用户会以为「这视频没字幕」。
        log("    ✗ 字幕列表为空。三种可能：这个视频确实没有官方 AI 字幕 / "
            "没登录（cookie 无效时接口是静默返回空，不报错）/ 被限流。"
            "跑 doctor.py 能区分前两种。")
        return False

    zh = [u for lan, u in subs if lan.endswith("zh")]
    if not zh:
        log(f"    ✗ 只有 {', '.join(sorted({l for l, _ in subs}))}，没有中文字幕")
        return False

    # 字幕的来源看 URL 的 host，比 lan 字段可靠：
    #   aisubtitle.hdslb.com -> B站官方 AI 生成
    #   s1.hdslb.com         -> UP 主自己投稿的人工字幕（通常质量更好）
    # 两种都能用，但值得说清楚是哪种 —— 人工字幕不会有 AI 的识别错误。
    src = ("官方AI" if "aisubtitle." in zh[0]
           else "UP主投稿" if "s1.hdslb.com" in zh[0] else "未知来源")

    body = bili_api.subtitle_body(zh[0])
    if not body:
        log("    ✗ 字幕内容下载失败（subtitle_url 带 auth_key，有时效，不能缓存）")
        return False

    text = srtlib.from_bcc(body)
    if not text.strip():
        log("    ✗ 字幕内容是空的")
        return False
    dest.write_text(text, encoding="utf-8")

    dur = meta.get("duration") or 0
    last = srtlib.last_timestamp(dest)
    if dur and last > dur * skill_config.MISMATCH_MAX:
        log(f"    ✗ 字幕末尾 {last:.0f}s 远超视频时长 {dur}s（{last / dur:.0%}）—— "
            f"这是接口串号的特征，字幕不是这个视频的，已丢弃")
        dest.unlink(missing_ok=True)
        return False
    if dur and last < dur * skill_config.COVERAGE_MIN:
        log(f"    ! 字幕只覆盖到 {last:.0f}s / {dur}s（{last / dur:.0%}），"
            f"低于 {skill_config.COVERAGE_MIN:.0%} —— 官方字幕走到一半断了。"
            f"下游产物会缺一大段，谨慎使用")
    log(f"    ✓ 字幕 {len(body)} 条 · {src} · 覆盖 {last / dur:.0%}" if dur
        else f"    ✓ 字幕 {len(body)} 条 · {src}")
    return True


# ---------- 2. 阅读版 ----------
def make_readable(srt_path, md_path, title):
    r = subprocess.run([sys.executable, str(LIB / "srt_to_md.py"), str(srt_path),
                        "-o", str(md_path), "--title", title],
                       stdin=subprocess.DEVNULL, capture_output=True,
                       text=True, timeout=300)
    if r.returncode != 0 or not md_path.is_file():
        log(f"    ✗ 阅读版生成失败: {r.stderr.strip()[-300:]}")
        return False
    log(f"    ✓ 阅读版 {md_path.stat().st_size // 1024} KB")
    return True


# ---------- 3. 脑图 ----------
def make_mindmap(md_path, opml_path, duration, workdir):
    """拉起 gen_mindmap.py 出 OPML。

    --duration 必须给：没有它就无法判断「补出来的小时位有没有超出视频长度」，
    gen_mindmap 会放弃修复漏写小时位的时间戳，章节顺序会乱。
    """
    prefix = opml_path.stem
    r = subprocess.run(
        [sys.executable, str(LIB / "gen_mindmap.py"), str(md_path), prefix,
         "--backend", skill_config.MINDMAP_BACKEND,
         "--model", skill_config.MINDMAP_MODEL,
         "--duration", str(int(duration or 0))],
        cwd=workdir, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=skill_config.MINDMAP_TIMEOUT)
    produced = Path(workdir) / f"{prefix}.opml"
    if r.returncode != 0 or not produced.is_file():
        tail = (r.stderr or r.stdout).strip()[-400:]
        log(f"    ✗ 脑图生成失败: {tail}")
        return False
    if produced != opml_path:
        produced.replace(opml_path)
    src = Path(workdir) / f"{prefix}.source.txt"
    if src.is_file() and src != opml_path.with_suffix(".source.txt"):
        src.replace(opml_path.with_suffix(".source.txt"))
    _, nodes = opml_lib.load(opml_path)
    log(f"    ✓ 脑图 {opml_lib.count_nodes(nodes)} 个节点")
    return True


# ---------- 4. 大纲 ----------
def make_outline(opml_path, md_path, title, pubdate, duration):
    """OPML -> 大纲 Markdown。纯本地渲染，不调模型，秒级。"""
    root_title, nodes = opml_lib.load(opml_path)
    date = (f"{pubdate[:4]}-{pubdate[4:6]}-{pubdate[6:8]}"
            if pubdate and len(pubdate) == 8 else "日期未知")
    bits = [date]
    if duration:
        bits.append(opml_lib.fmt_duration(duration))
    bits.append(f"{opml_lib.count_nodes(nodes)} 个节点")
    md_path.write_text(
        pdf_content.to_markdown(title, " · ".join(bits), root_title, nodes),
        encoding="utf-8")
    log(f"    ✓ 大纲 {md_path.stat().st_size // 1024} KB")
    return True


# ---------- 5. PDF ----------
def make_pdf(entries, out, name):
    """出两本 PDF。fpdf2 只在这一步需要，所以 import 放在函数里。"""
    try:
        from lib import pdfbook
    except ImportError as e:
        log(f"    ✗ 出 PDF 需要 fpdf2 和 fonttools：pip install fpdf2 fonttools（{e}）")
        return False
    entries.sort(key=lambda e: (e["pubdate"] or "00000000", e["title"]), reverse=True)
    mm, ol = pdfbook.render_channel(entries, out, name, log=lambda m: log("    " + m.strip()))
    return bool(mm and ol)


# ---------- 编排 ----------
def digest_one(bv, out, skip_mindmap):
    """返回 (成功?, PDF 条目或 None)。--skip-mindmap 时成功但没有条目。"""
    meta = bili_api.view_by_bvid(bv)
    if not meta:
        log(f"✗ {bv}: 查不到视频信息（BV 写错 / 视频被删 / 被限流）")
        return False, None
    if meta.get("pages", 1) > 1:
        log(f"⊘ {bv}: 分 P 视频（{meta['pages']} P），本 skill 不处理")
        return False, None

    stem = stem_for(bv, meta["title"], meta["pubdate"])
    log(f"▶ {bv} {meta['title'][:50]}")
    out.mkdir(parents=True, exist_ok=True)

    srt_path = out / f"{stem}.srt"
    if fresh(srt_path):
        log("    · 字幕已存在，跳过")
    elif not fetch_subtitle(meta, srt_path):
        return False, None

    md_path = out / f"{stem}-阅读版.md"
    if fresh(md_path):
        log("    · 阅读版已存在，跳过")
    elif not make_readable(srt_path, md_path, meta["title"]):
        return False, None

    if skip_mindmap:
        return True, None

    opml_path = out / f"{stem}.opml"
    if fresh(opml_path):
        log("    · 脑图已存在，跳过")
    elif not make_mindmap(md_path, opml_path, meta.get("duration"), out):
        return False, None

    outline_path = out / f"{stem}-大纲.md"
    make_outline(opml_path, outline_path, meta["title"],
                 meta["pubdate"], meta.get("duration"))

    _, nodes = opml_lib.load(opml_path)
    n = opml_lib.count_nodes(nodes)
    date = f"{meta['pubdate'][:4]}-{meta['pubdate'][4:6]}-{meta['pubdate'][6:8]}"
    return True, {"opml": str(opml_path), "title": meta["title"],
                  "pubdate": meta["pubdate"], "bvid": bv, "nodes": n,
                  "subtitle": f"{date} · {n} 个节点"}


def digest_local_srt(srt_path, out, title, duration, skip_mindmap):
    """次要入口：已经有 srt 了，只想要脑图/大纲/PDF。"""
    srt_path = Path(srt_path).expanduser().resolve()
    if not srt_path.is_file():
        log(f"✗ 找不到字幕文件 {srt_path}")
        return False, None
    title = title or srt_path.stem
    stem = safe_title(title)[:180]
    out.mkdir(parents=True, exist_ok=True)
    log(f"▶ 本地字幕 {srt_path.name}")

    if not duration:
        # 没给时长就按字幕末尾推算 —— gen_mindmap 修时间戳要用它。
        duration = int(srtlib.last_timestamp(srt_path))
        log(f"    · 未给 --duration，按字幕末尾推算为 {duration}s")

    md_path = out / f"{stem}-阅读版.md"
    if not (md_path.is_file() and md_path.stat().st_size) \
            and not make_readable(srt_path, md_path, title):
        return False, None
    if skip_mindmap:
        return True, None
    opml_path = out / f"{stem}.opml"
    if not (opml_path.is_file() and opml_path.stat().st_size) \
            and not make_mindmap(md_path, opml_path, duration, out):
        return False, None
    make_outline(opml_path, out / f"{stem}-大纲.md", title, "", duration)
    _, nodes = opml_lib.load(opml_path)
    n = opml_lib.count_nodes(nodes)
    return True, {"opml": str(opml_path), "title": title, "pubdate": "",
                  "bvid": "", "nodes": n, "subtitle": f"{n} 个节点"}


def run(targets, out, name="B站合集", skip_mindmap=False, skip_pdf=False,
        srt=None, title=None, duration=0):
    """嚼工作流。out 由调用方解析好传进来。返回退出码。"""
    skill_config.load_dotenv()
    if not skip_mindmap and skill_config.MINDMAP_BACKEND == "deepseek" \
            and not os.environ.get("DEEPSEEK_API_KEY"):
        sys.exit("缺 DEEPSEEK_API_KEY（脑图那步要用）。\n"
                 "  -> echo 'DEEPSEEK_API_KEY=sk-...' >> .env.local\n"
                 "  或者加 --skip-mindmap，只要字幕和阅读版。")

    entries, done = [], 0
    if srt:
        ok, e = digest_local_srt(srt, out, title, duration, skip_mindmap)
        done += bool(ok)
        if e:
            entries.append(e)
        total = 1
    else:
        # bad 这里只告警不计进退出码 —— 和 download 侧口径不同，见 _common
        bvs, _bad = collect_bvs(targets)
        total = len(bvs)
        for bv in bvs:
            ok, e = digest_one(bv, out, skip_mindmap)
            done += bool(ok)
            if e:
                entries.append(e)

    if entries and not skip_pdf and not skip_mindmap:
        log(f"\n出 PDF（{len(entries)} 期）…")
        make_pdf(entries, out, name)

    log(f"\n完成 {done}/{total} 期（字幕/脑图） -> {out}")
    return 0 if done == total else 1

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 站官方 AI 字幕 -> 阅读版 -> 脑图 OPML -> 大纲 -> 两本中文 PDF。

    bili.py digest BV1xxx [BV2 ...] --out DIR [--name 书名]
    bili.py digest --srt path/to.srt --title 标题 --out DIR

本文件是模块，不是入口 —— 入口在 bili.py。

五步各自幂等：产物在就跳过，可以随时中断续跑。踩坑结论在 SKILL.md。
"""
import os
import re
import shlex
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
# digest_one/digest_local_srt 的三态。PENDING = 没坏，只是在等 agent 写大纲。
OK, PENDING, FAIL = "ok", "pending", "fail"


def outline_smells_bad(path):
    """给 .source.txt 做体检。返回不合格的原因串，合格返回 ""。

    大纲现在可能是 agent 手写的，写歪了下游是**静默**出错的：tab 缩进会被
    parse() 当成零级缩进、整棵树压成一层，而不是报错。宁可在这里拦住。
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 5:
        return f"只有 {len(lines)} 行，像是被截断了"
    if any(l.startswith("\t") or l.startswith(" \t") for l in lines):
        return "用了 tab 缩进（parse 只认空格，会把整棵树压成一层）"
    if not any(l.startswith("  ") for l in lines):
        return "没有任何缩进行，不是一棵树"
    n_ts = sum(1 for l in lines if re.match(r"\s*\[\d{1,2}:\d{2}", l))
    if n_ts < 3:
        return f"只有 {n_ts} 行带 [mm:ss] 时间戳"
    return ""


def make_mindmap(md_path, opml_path, duration, workdir, build=False):
    """出 OPML。返回 (状态, 说明)。

    三条路，按顺序：
      1. 已有 .source.txt  -> --outline 纯本地解析，不调任何模型
      2. 配了 API key      -> HTTP，无人值守
      3. 都没有            -> PENDING，交给跑这个 skill 的 agent 写

    build=True 时只走第 1 条：--build 是「大纲已经写好了，收尾」，配了 key 也不该
    偷偷替用户调一次模型 —— 那会让「收尾，不调模型」这句日志变成假话。

    --duration 必须给：没有它就无法判断「补出来的小时位有没有超出视频长度」，
    gen_mindmap 会放弃修复漏写小时位的时间戳，章节顺序会乱。
    """
    prefix = opml_path.stem
    src = opml_path.with_suffix(".source.txt")

    if fresh(src):
        bad = outline_smells_bad(src)
        if bad:
            log(f"    ⏸ 已有 .source.txt 但不合格（{bad}），要重写")
            return PENDING, f"上一版不合格：{bad}"
        log("    · 发现 .source.txt，按大纲本地解析（不调模型）")
        # 纯本地解析是秒级的，给 120s 而不是 1800s —— 卡住能早点发现。
        infile, extra, budget = src, ["--outline"], 120
    elif build:
        return PENDING, "带了 --build，但这期还没有 .source.txt"
    else:
        kind, info = skill_config.resolve_mindmap()
        if kind == "error":
            log(f"    ✗ {info}")
            return FAIL, info
        if kind == "agent":
            return PENDING, ""
        infile, budget = md_path, skill_config.MINDMAP_TIMEOUT
        extra = (["--backend", "claude"] if kind == "claude"
                 else ["--backend", "api", "--model", info["model"]])

    r = subprocess.run(
        [sys.executable, str(LIB / "gen_mindmap.py"), str(infile), prefix,
         *extra, "--duration", str(int(duration or 0))],
        cwd=workdir, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=budget, env=skill_config.env_for_backend())
    produced = Path(workdir) / f"{prefix}.opml"
    if r.returncode != 0 or not produced.is_file():
        tail = (r.stderr or r.stdout).strip()[-400:]
        log(f"    ✗ 脑图生成失败: {tail}")
        return FAIL, tail
    if produced != opml_path:
        produced.replace(opml_path)
    got = Path(workdir) / f"{prefix}.source.txt"
    if got.is_file() and got != src:
        got.replace(src)
    # 时间戳的告警要透出来 —— 大纲可能是 agent 自己写的，它得看得见问题才好改。
    for line in (r.stderr or "").splitlines():
        if line.lstrip().startswith(("⚠", "修正", "  修正")):
            log("    " + line.strip())
    _, nodes = opml_lib.load(opml_path)
    log(f"    ✓ 脑图 {opml_lib.count_nodes(nodes)} 个节点")
    return OK, None


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
def digest_one(bv, out, skip_mindmap, build=False):
    """返回 (状态, payload)。状态见 OK/PENDING/FAIL。

    PENDING 时 payload 是交接信息（读哪个、写到哪），不是 PDF 条目。
    """
    meta = bili_api.view_by_bvid(bv)
    if not meta:
        log(f"✗ {bv}: 查不到视频信息（BV 写错 / 视频被删 / 被限流）")
        return FAIL, None
    if meta.get("pages", 1) > 1:
        log(f"⊘ {bv}: 分 P 视频（{meta['pages']} P），本 skill 不处理")
        return FAIL, None

    stem = stem_for(bv, meta["title"], meta["pubdate"])
    log(f"▶ {bv} {meta['title'][:50]}")
    out.mkdir(parents=True, exist_ok=True)

    srt_path = out / f"{stem}.srt"
    if fresh(srt_path):
        log("    · 字幕已存在，跳过")
    elif not fetch_subtitle(meta, srt_path):
        return FAIL, None

    md_path = out / f"{stem}-阅读版.md"
    if fresh(md_path):
        log("    · 阅读版已存在，跳过")
    elif not make_readable(srt_path, md_path, meta["title"]):
        return FAIL, None

    if skip_mindmap:
        return OK, None

    opml_path = out / f"{stem}.opml"
    if fresh(opml_path):
        log("    · 脑图已存在，跳过")
    else:
        st, why = make_mindmap(md_path, opml_path, meta.get("duration"), out, build)
        if st == PENDING:
            return PENDING, {"label": f"{bv} {meta['title'][:40]}",
                             "md": str(md_path),
                             "source": str(opml_path.with_suffix(".source.txt")),
                             "duration": int(meta.get("duration") or 0),
                             "why": why}
        if st == FAIL:
            return FAIL, None

    outline_path = out / f"{stem}-大纲.md"
    make_outline(opml_path, outline_path, meta["title"],
                 meta["pubdate"], meta.get("duration"))

    _, nodes = opml_lib.load(opml_path)
    n = opml_lib.count_nodes(nodes)
    date = f"{meta['pubdate'][:4]}-{meta['pubdate'][4:6]}-{meta['pubdate'][6:8]}"
    return OK, {"opml": str(opml_path), "title": meta["title"],
                "pubdate": meta["pubdate"], "bvid": bv, "nodes": n,
                "subtitle": f"{date} · {n} 个节点"}


def digest_local_srt(srt_path, out, title, duration, skip_mindmap, build=False):
    """次要入口：已经有 srt 了，只想要脑图/大纲/PDF。"""
    srt_path = Path(srt_path).expanduser().resolve()
    if not srt_path.is_file():
        log(f"✗ 找不到字幕文件 {srt_path}")
        return FAIL, None
    title = title or srt_path.stem
    stem = safe_title(title)[:180]
    out.mkdir(parents=True, exist_ok=True)
    log(f"▶ 本地字幕 {srt_path.name}")

    if not duration:
        # 没给时长就按字幕末尾推算 —— gen_mindmap 修时间戳要用它。
        duration = int(srtlib.last_timestamp(srt_path))
        log(f"    · 未给 --duration，按字幕末尾推算为 {duration}s")

    md_path = out / f"{stem}-阅读版.md"
    if not fresh(md_path) and not make_readable(srt_path, md_path, title):
        return FAIL, None
    if skip_mindmap:
        return OK, None

    opml_path = out / f"{stem}.opml"
    if not fresh(opml_path):
        st, why = make_mindmap(md_path, opml_path, duration, out, build)
        if st == PENDING:
            return PENDING, {"label": f"本地字幕 {title[:40]}",
                             "md": str(md_path),
                             "source": str(opml_path.with_suffix(".source.txt")),
                             "duration": int(duration or 0),
                             "why": why}
        if st == FAIL:
            return FAIL, None

    make_outline(opml_path, out / f"{stem}-大纲.md", title, "", duration)
    _, nodes = opml_lib.load(opml_path)
    n = opml_lib.count_nodes(nodes)
    return OK, {"opml": str(opml_path), "title": title, "pubdate": "",
                "bvid": "", "nodes": n, "subtitle": f"{n} 个节点"}


BAR = "═" * 68


def print_handoff(pendings):
    """把「该写哪些文件」讲清楚。读者是跑这个 skill 的 agent，不是人。"""
    # 原样重建这次的命令并补上 --build。已经带了就别再加一次。
    argv = [a for a in sys.argv[1:] if a != "--build"]
    cmd = shlex.join([sys.executable, str(Path(sys.argv[0]).resolve()),
                      *argv, "--build"])
    log("\n" + BAR)
    log(f"⏸ 字幕和阅读版好了。脑图这步交给你（正在跑这个 skill 的 agent）—— 共 {len(pendings)} 期。")
    log("")
    log("先读一遍 prompt（逐字遵守；六个【类型】标签是下游大纲排版和 PDF 配色的硬契约）：")
    log(f"  {skill_config.PROMPT_PATH}")
    log("")
    log("对下面每一期：读「阅读版」，按 prompt 整理成缩进式大纲，原样写进「写到」。")
    log("只写大纲本身 —— 不要代码围栏、不要前言。缩进用 2 个空格，别用 tab。")
    for n, p_ in enumerate(pendings, 1):
        log("")
        log(f"[{n}/{len(pendings)}] {p_['label']}")
        log(f"      阅读版  {p_['md']}")
        log(f"      写到    {p_['source']}")
        if p_["duration"]:
            log(f"      时长    {p_['duration']}s"
                f"（超 1 小时的时间戳写成 [h:mm:ss]，漏小时位章节会排错）")
        if p_["why"]:
            log(f"      注意    {p_['why']}")
    log("")
    log("全部写完之后，跑这条收尾（BV 一个都不能少 —— PDF 是整本出的）：")
    log(f"  {cmd}")
    log("")
    log("（不想自己写：配个 key 就自动走 HTTP 无人值守 ——")
    log("   echo 'DEEPSEEK_API_KEY=sk-...' >> .env.local；只要字幕和阅读版：--skip-mindmap）")
    log(BAR)


def run(targets, out, name="B站合集", skip_mindmap=False, skip_pdf=False,
        srt=None, title=None, duration=0, backend=None, build=False):
    """嚼工作流。out 由调用方解析好传进来。

    退出码：0 全成 / 1 有东西坏了 / 2 什么都没坏，有几期的大纲在等 agent 写。
    """
    skill_config.load_dotenv()
    if backend:
        # CLI 显式指定优先于环境变量和 .env
        os.environ[skill_config.BACKEND_ENV] = backend

    # ---- 前置检查：动任何文件之前就把「这批活谁干」定下来并说出来 ----
    # 只负责「说清楚这批活谁干」。真正的分流在 make_mindmap 里按每期独立判定
    # （有的期可能已经有 .source.txt 了），所以这里不需要记状态。
    if not skip_mindmap:
        kind, info = skill_config.resolve_mindmap()
        if kind == "error":
            sys.exit(info)
        if build:
            # --build 是收尾：大纲已经在 .source.txt 里了，不需要任何模型。
            log("脑图后端：读已有的 .source.txt（收尾，不调模型）")
        elif kind == "api":
            log(f"脑图后端：API {info['model']}（{info['via']}），无人值守")
        elif kind == "claude":
            log("脑图后端：claude CLI 子进程（显式指定）")
        else:
            # 显式 --mindmap-backend agent 时别说「没配 key」—— 可能配了，只是不想用。
            why = ("显式指定" if skill_config.mindmap_backend() == "agent"
                   else "没配 API key 不是错误，这是默认方式")
            log(f"脑图后端：交给当前 agent（{why}）。")
            log("           本轮出字幕和阅读版，大纲由你写，之后用 --build 收尾。")

    entries, pendings, ok_n, fail_n = [], [], 0, 0
    if srt:
        st, payload = digest_local_srt(srt, out, title, duration, skip_mindmap, build)
        total = 1
        ok_n += st == OK
        fail_n += st == FAIL
        if st == PENDING:
            pendings.append(payload)
        elif payload:
            entries.append(payload)
    else:
        # bad 这里只告警不计进退出码 —— 和 download 侧口径不同，见 _common
        bvs, _bad = collect_bvs(targets)
        total = len(bvs)
        for bv in bvs:
            st, payload = digest_one(bv, out, skip_mindmap, build)
            ok_n += st == OK
            fail_n += st == FAIL
            if st == PENDING:
                pendings.append(payload)
            elif payload:
                entries.append(payload)

    if pendings:
        print_handoff(pendings)

    if entries and not skip_pdf and not skip_mindmap:
        if pendings:
            # PDF 文件名只由 --name 决定、内容只含这一次的 BV。现在出半本，等 agent
            # 补完再跑一次就会把它盖掉，里面只剩后补的那几期。不如一次出全的。
            log(f"\n· 还有 {len(pendings)} 期待写大纲，本轮不出 PDF（PDF 是整本覆盖的，"
                f"出半本会被收尾那次盖掉）")
        else:
            log(f"\n出 PDF（{len(entries)} 期）…")
            make_pdf(entries, out, name)

    # 有待写的时候别报「完成 0/N」—— 字幕和阅读版是真做完了，说成 0 像是全崩了。
    if pendings:
        tail = f"{len(pendings)}/{total} 期等你写大纲（字幕和阅读版已就绪）"
        if ok_n:
            tail = f"完成 {ok_n}/{total} 期 · " + tail
    else:
        tail = f"完成 {ok_n}/{total} 期（字幕/脑图）"
    if fail_n:
        tail += f" · 失败 {fail_n}"
    log(f"\n{tail} -> {out}")
    if fail_n:
        return 1
    return 2 if pendings else 0

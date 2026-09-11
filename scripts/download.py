#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""下载 B 站视频的正片 mp4 + 封面 jpg + 元信息 info.json。

    bili.py download BV1xxx [BV2 ...] --out DIR

本文件是模块，不是入口 —— 入口在 bili.py。

设计上每个 BV 独立：一个失败不影响其它，重跑会跳过已完成的（幂等）。
踩坑结论写在 SKILL.md，改这个文件前先读那一份。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import bili_api
from _common import collect_bvs, fresh, log, stem_for

# 默认体积上限。超过就只出封面+info、不下正片，并明确报告出来。
# 800MB ≈ 一小时 1080p 的量级；设这个默认值是为了让一批里混进来的
# 一个几 GB 的长视频不会把整批时间吃光，而不是因为 800 有什么特殊。
DEFAULT_MAX_MB = int(os.environ.get("BILI_MAX_MP4_MB", "800"))

# BBDown 下载的墙钟上限。1080p 长视频在慢线路上确实会跑到小时级。
DOWNLOAD_TIMEOUT = int(os.environ.get("BILI_DOWNLOAD_TIMEOUT", "7200"))

# 解析 BBDown `-info` 输出里第 0 条（默认=最高清）流的估算体积。
# 这条正则绑死了 BBDown 的输出格式，BBDown 改版式就会失配 ——
# 失配时 _video_size_mb 返回 None，调用方按「探不到体积」处理（照常下载），
# 不会误判成 0MB，所以最坏情况是退化成不限体积，不会静默跳过。
_SIZE_RE = re.compile(r'^\s*0\.\s*\[.*?\]\s*\[\d+x\d+\].*?\[~\s*([\d.]+)\s*(GB|MB)\]')


# ---------- 外部依赖 ----------
def require_bins(*names):
    missing = [n for n in names if not shutil.which(n)]
    if missing:
        fixes = {
            "BBDown": "见 https://github.com/nilaoda/BBDown/releases 下载后放进 PATH",
            "ffprobe": "brew install ffmpeg（ffprobe 随 ffmpeg 一起装）",
            "ffmpeg": "brew install ffmpeg",
            "curl": "系统自带；PATH 里找不到说明环境被裁过",
        }
        lines = [f"  缺少 {n}  ->  {fixes.get(n, '请自行安装')}" for n in missing]
        sys.exit("依赖不完整：\n" + "\n".join(lines))


def _bbdown_mt_args():
    """BILI_BBDOWN_MT=false/0/no -> BBDown 单线程。

    走窄通道（比如一条 SSH-SOCKS 隧道）时多线程会把它打爆，这时关掉更快。
    """
    if os.environ.get("BILI_BBDOWN_MT", "true").lower() in ("false", "0", "no"):
        return ["--multi-thread", "false"]
    return []


def probe_duration(path):
    """ffprobe 量时长（秒）。读不到返回 None —— 这就是「文件是坏的」的判据。"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def _is_muxed(mp4):
    """同目录下还留着 .m4a 就说明音视频没合流，是被打断的半成品。"""
    return not list(mp4.parent.glob(f"{mp4.stem}*.m4a"))


def _streams(path):
    """返回文件里有哪些轨道类型的集合，如 {"video", "audio"}。"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return set()
    return {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}


def _last_video_pts(path):
    """最后一个视频包的呈现时间(秒)。读不到返回 None。

    这是判断「下到一半就断了」的**唯一可靠信号**。实测 0.27s / 184MB，不必优化。
    """
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(path)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in reversed(r.stdout.splitlines()):
        line = line.strip().rstrip(",")
        if line:
            try:
                return float(line)
            except ValueError:
                continue
    return None


def verify_mp4(path, want_duration=None):
    """判定一个 mp4 是不是完整可用的。返回 (ok, 说明)。

    坏文件的**大小看着是正常的**，光判「文件存在」必然漏。三道关：
    容器可解析 / 音视频轨都在 / 实际画面覆盖到了片尾。

    最后一关是重点：faststart 的 mp4 把 moov 放在文件头，**被截断后 ffprobe
    报的时长依然是满的**。实测把一个 3685s 的文件截到 60%，ffprobe 仍报
    3685s，连 `ffmpeg -c copy -f null` 都 rc=0 无输出 —— 只有比对最后一个
    视频包的 pts（1957s）才看得出来。所以别用时长或 demux 当判据。
    """
    dur = probe_duration(path)
    if not dur:
        return False, "ffprobe 读不出时长，容器是坏的"
    st = _streams(path)
    if "video" not in st:
        return False, "没有视频轨"
    if "audio" not in st:
        return False, "没有音频轨（多半是合流被打断了）"

    ref = want_duration or dur
    pts = _last_video_pts(path)
    if pts is None:
        return False, "读不出视频包，文件是坏的"
    if pts < ref * 0.98 - 2:
        return False, (f"画面只到 {pts:.0f}s，但应有 {ref:.0f}s"
                       f"（{pts / ref:.0%}）—— 下到一半断了")
    if want_duration and abs(dur - want_duration) > max(2, want_duration * 0.02):
        return False, f"时长对不上：接口说 {want_duration}s，文件是 {dur:.0f}s"
    return True, f"{dur:.0f}s"


def video_size_mb(bvid):
    """用 BBDown -info 读默认(最高清)流的估算体积(MB)。读不到返回 None。"""
    try:
        r = subprocess.run(["BBDown", bvid, "-info"] + _bbdown_mt_args(),
                           stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in r.stdout.splitlines():
        m = _SIZE_RE.match(line)
        if m:
            v = float(m.group(1))
            return v * 1024 if m.group(2) == "GB" else v
    return None


def bbdown(bvid, dest_mp4, timeout=DOWNLOAD_TIMEOUT):
    """下到系统临时目录再搬到目标位置。返回 True/False。

    **不直接下到目标目录**：BBDown 分块下载后按通配合并分片，而 macOS 在
    exFAT / 部分网络盘上会给每个分片配一个 `._` 伴生文件，`.` 排在数字前，
    会被一起并进去 —— 合出来的文件开头是 AppleDouble 魔数而不是 ftyp，
    ffmpeg 报 "moov atom not found"。实测同一视频下到 APFS 是 709MB 可播放，
    下到 exFAT 是 630MB 的废文件。临时目录在内置盘，绕开这件事。
    """
    tmp_root = Path(os.environ.get("TMPDIR", "/tmp"))
    with tempfile.TemporaryDirectory(dir=tmp_root, prefix="bili-dl-") as td:
        td = Path(td)
        try:
            subprocess.run(["BBDown", bvid, "--skip-ai", "false"] + _bbdown_mt_args(),
                           cwd=td, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            log(f"    ✗ BBDown 超时（>{timeout}s）")
            return False
        except OSError as e:
            log(f"    ✗ 拉不起 BBDown: {e}")
            return False
        # `._` 开头的是 macOS 资源分支伴生文件，不是真视频；
        # 还留着 .m4a 的是没合流的半成品。两种都不能要。
        got = [p for p in td.rglob("*.mp4")
               if not p.name.startswith("._") and _is_muxed(p)]
        if not got:
            return False
        dest_mp4.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(got[0]), str(dest_mp4))
        return True


def curl_download(url, dst, timeout=60):
    """curl 下载。"""
    try:
        subprocess.run(["curl", "-s", "-L", "--max-time", str(timeout),
                        "-A", "Mozilla/5.0", "-o", str(dst), url],
                       stdin=subprocess.DEVNULL, capture_output=True,
                       timeout=timeout + 10)
    except (OSError, subprocess.SubprocessError):
        return False
    return dst.is_file() and dst.stat().st_size > 0


def info_json(raw, bv):
    """view 原始数据 -> 紧凑的 info.json。"""
    stat = raw.get("stat") or {}
    return {
        "bvid": raw.get("bvid", bv),
        "aid": raw.get("aid"),
        "cid": raw.get("cid"),
        "title": raw.get("title", ""),
        "pubdate": raw.get("pubdate"),
        "duration": raw.get("duration"),
        "view": stat.get("view"),
        "like": stat.get("like"),
        "comment_count": stat.get("reply"),
        "owner": (raw.get("owner") or {}).get("name", ""),
        "owner_mid": (raw.get("owner") or {}).get("mid"),
        "desc": raw.get("desc", ""),
        "url": f"https://www.bilibili.com/video/{bv}",
    }


# ---------- 单期 ----------
def fetch_one(bv, out, max_mb, want_video, stem_title):
    raw = bili_api.view_raw(bv)
    if not raw:
        log(f"✗ {bv}: 查不到视频信息（BV 号写错？被删了？还是被限流了 —— "
            f"限流时接口是静默返回空，不报错）")
        return False

    title = raw.get("title", "")
    if stem_title:
        pub = bili_api.view_by_bvid(bv)
        stem = stem_for(bv, title, pub["pubdate"] if pub else None)
    else:
        stem = stem_for(bv)

    out.mkdir(parents=True, exist_ok=True)
    log(f"▶ {bv} {title[:50]}")

    # info.json 和封面永远出 —— 它们不依赖下载成功，且几乎不花时间。
    ij = out / f"{stem}.info.json"
    ij.write_text(json.dumps(info_json(raw, bv), ensure_ascii=False, indent=2),
                  encoding="utf-8")

    jpg = out / f"{stem}.jpg"
    if fresh(jpg):
        log("    · 封面已存在，跳过")
    elif raw.get("pic") and curl_download(raw["pic"], jpg):
        log(f"    ✓ 封面 {jpg.stat().st_size // 1024} KB")
    else:
        log("    ! 封面下载失败（不影响其它产物）")

    if not want_video:
        log("    · --no-video：不下正片")
        return True

    mp4 = out / f"{stem}.mp4"
    if mp4.is_file():
        ok, why = verify_mp4(mp4, raw.get("duration"))
        if ok:
            log(f"    · 正片已存在且完整（{why}），跳过")
            return True
        log(f"    ! 已存在的正片是坏的（{why}），删掉重下")
        mp4.unlink(missing_ok=True)

    if max_mb:
        sz = video_size_mb(bv)
        if sz is None:
            log("    ! 探不到体积（BBDown 输出格式可能变了），照常下载")
        elif sz > max_mb:
            log(f"    ⊘ 正片约 {sz:.0f}MB，超过上限 {max_mb}MB —— 跳过正片。"
                f"要它就加 --max-mb 0")
            return True

    if not bbdown(bv, mp4):
        log("    ✗ 下载失败")
        return False

    ok, why = verify_mp4(mp4, raw.get("duration"))
    if not ok:
        log(f"    ✗ 下下来的文件没通过校验（{why}），已删除")
        mp4.unlink(missing_ok=True)
        return False
    log(f"    ✓ 正片 {mp4.stat().st_size / 1024 / 1024:.0f} MB · {why}")
    return True


def run(targets, out, max_mb=DEFAULT_MAX_MB, want_video=True, stem_title=False):
    """下载工作流。out 由调用方解析好传进来。返回退出码。"""
    need = ("curl", "ffprobe", "ffmpeg", "BBDown") if want_video else ("curl",)
    require_bins(*need)

    # bad 要计进退出码 —— 给了个打错的链接就该非零退出，和 digest 侧口径不同
    bvs, bad = collect_bvs(targets)
    ok = sum(fetch_one(bv, out, max_mb, want_video, stem_title) for bv in bvs)
    log(f"\n完成 {ok}/{len(bvs)} 期（视频） -> {out}")
    return 0 if ok == len(bvs) and not bad else 1

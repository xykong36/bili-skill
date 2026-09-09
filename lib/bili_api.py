#!/usr/bin/env python3
"""B站接口的薄封装：view（视频元信息）+ player（字幕列表）。

只用标准库 + curl，和原来的 build_candidates.py 保持一致，
不给这套脚本引入额外的 Python 依赖。

字幕接口必须走 `x/player/wbi/v2`。老的 `x/player/v2` **会返回别的视频的字幕**——
不是截断，是串号：同一个视频连查三次，拿到的是 461条/689s、86条/170s、614条/1063s
三份内容完全不相干的字幕（"蔡徐坤被软封禁""维鲁斯"之类，跟视频毫无关系）。
BBDown 走的就是这个老接口，所以它的 `--sub-only` 输出同样不可信，
实测同一视频连跑三次拿到 326条 / 2053条(1小时) / 326条。详见 docs/字幕获取.md。
"""
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))
API = "https://api.bilibili.com/x/web-interface/view"
PLAYER_API = "https://api.bilibili.com/x/player/wbi/v2"
RETRY = 3
UA = "Mozilla/5.0"


def _curl_json(url, cookie=None, referer=None, retry=RETRY):
    for attempt in range(retry):
        cmd = ["curl", "-s", "--max-time", "30", "-A", UA]
        if referer:
            cmd += ["-H", f"Referer: {referer}"]
        if cookie:
            cmd += ["-H", f"Cookie: {cookie}"]
        out = subprocess.run(cmd + [url], capture_output=True, text=True).stdout
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            time.sleep(1 + attempt)      # 限流/抖动，退避重试
    return None


def _get(param):
    for attempt in range(RETRY):
        body = _curl_json(f"{API}?{param}", retry=1)
        if body and body.get("code") == 0:
            return body["data"]
        time.sleep(1 + attempt)
    return None


def cookie_file():
    """BBDown 登录后写的 cookie 文件。字幕接口必须带它——不带就返回空字幕列表。

    BBDown 把它写在自己可执行文件旁边（或当年运行时的工作目录），所以按
    可执行文件真身 → HOME 的顺序找。BILI_COOKIE_FILE 可以直接指定。

    这个文件等价于你的 B 站登录态，**别提交进任何仓库、别分发**。
    """
    env = os.environ.get("BILI_COOKIE_FILE")
    cands = [Path(env)] if env else []
    exe = shutil.which("BBDown")
    if exe:
        cands.append(Path(os.path.realpath(exe)).parent / "BBDown.data")
    cands.append(Path.home() / "BBDown.data")
    for p in cands:
        if p.is_file():
            return p
    return None


def cookie():
    p = cookie_file()
    return p.read_text(encoding="utf-8").strip() if p else ""


def subtitle_list(aid, cid, bvid=None):
    """返回 [(语言码, 字幕URL), ...]。空列表可能是没字幕，也可能是没登录。"""
    ref = f"https://www.bilibili.com/video/{bvid}" if bvid else "https://www.bilibili.com"
    body = _curl_json(f"{PLAYER_API}?aid={aid}&cid={cid}", cookie=cookie(), referer=ref)
    if not body or body.get("code") != 0:
        return []
    subs = (body.get("data") or {}).get("subtitle") or {}
    out = []
    for s in subs.get("subtitles") or []:
        url = s.get("subtitle_url") or ""
        if url.startswith("//"):         # 接口给的是协议相对URL
            url = "https:" + url
        if url:
            out.append((s.get("lan", ""), url))
    return out


def subtitle_body(url):
    """下载 bcc(JSON) 字幕，返回 [{from, to, content}, ...]。auth_key 有时效，别缓存URL。"""
    body = _curl_json(url, referer="https://www.bilibili.com")
    return (body or {}).get("body") or []


def _shape(d):
    return {
        "bvid": d["bvid"],
        "aid": d["aid"],
        "cid": d.get("cid"),           # 字幕接口要用；老缓存里没有，subs 会现查
        "pages": d.get("videos") or len(d.get("pages") or [1]),   # 分P数，>1 的整条流水线跳过
        "duration": d["duration"],
        "pubdate": datetime.fromtimestamp(d["pubdate"], tz=CST).strftime("%Y%m%d"),
        "title": d["title"],
        "owner_mid": d["owner"]["mid"],
        "owner_name": d["owner"]["name"],
    }


def view_raw(bvid):
    """view 接口的原始 data，比 view_by_bvid 多出 pic / stat / desc 等字段。

    需要封面地址或播放量时用这个；只要 aid/cid/时长/标题就用 view_by_bvid。
    """
    return _get(f"bvid={bvid}")


def view_by_bvid(bvid):
    d = _get(f"bvid={bvid}")
    return _shape(d) if d else None


def view_by_aid(aid):
    d = _get(f"aid={aid}")
    return _shape(d) if d else None

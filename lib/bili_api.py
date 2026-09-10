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
import tempfile
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


def get_json_with_cookies(url, referer=None, timeout=30):
    """GET 一个 JSON 接口，同时把响应里的 Set-Cookie 也带回来。

    返回 (body_dict_or_None, {cookie名: 值})。扫码登录要用它 —— B 站现在把
    登录 cookie 放在响应头里下发，光看 body 是拿不到的。
    """
    with tempfile.TemporaryDirectory(prefix="bili-hdr-") as td:
        hdr = Path(td) / "h.txt"
        cmd = ["curl", "-s", "--max-time", str(timeout), "-A", UA, "-D", str(hdr)]
        if referer:
            cmd += ["-H", f"Referer: {referer}"]
        out = subprocess.run(cmd + [url], capture_output=True, text=True).stdout
        try:
            body = json.loads(out)
        except json.JSONDecodeError:
            body = None
        jar = {}
        try:
            for line in hdr.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not line.lower().startswith("set-cookie:"):
                    continue
                # Set-Cookie: NAME=VALUE; Path=/; Domain=...  —— 只要第一段
                first = line.split(":", 1)[1].strip().split(";", 1)[0]
                if "=" in first:
                    k, v = first.split("=", 1)
                    if v.strip():
                        jar[k.strip()] = v.strip()
        except OSError:
            pass
    return body, jar


def get_json(url, cookie=None, referer=None, retry=RETRY):
    """GET 一个返回 JSON 的接口。走 curl 子进程，所以自动继承进程级 ALL_PROXY。

    登录流程也用它 —— 本机直连 B 站接口是不通的，必须跟其它请求走同一条出口。
    """
    return _curl_json(url, cookie=cookie, referer=referer, retry=retry)


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
    可执行文件真身 → HOME 的顺序找。

    **BILI_COOKIE_FILE 一旦设了就是权威的**：指到哪就用哪，文件不存在也不再
    往下找。显式指定了一个路径却被悄悄换成另一个账号的 cookie，是很难查的坑
    （多账号、跑测试时尤其）。

    这个文件等价于你的 B 站登录态，**别提交进任何仓库、别分发**。
    """
    env = os.environ.get("BILI_COOKIE_FILE")
    if env:
        p = Path(env).expanduser()
        return p if p.is_file() else None
    cands = []
    exe = shutil.which("BBDown")
    if exe:
        cands.append(Path(os.path.realpath(exe)).parent / "BBDown.data")
    cands.append(Path.home() / "BBDown.data")
    for p in cands:
        if p.is_file():
            return p
    return None


def cookie_target():
    """登录成功后该把 BBDown.data 写到哪。

    和 cookie_file() 同一套优先级，区别是它不要求文件已存在 —— 挑第一个
    **目录可写**的位置。BBDown 那个目录常常是只读的（比如装在 /opt 或
    只读挂载里），写不进去就退回 ~/BBDown.data，bili_api 照样找得到。
    """
    env = os.environ.get("BILI_COOKIE_FILE")
    if env:
        return Path(env).expanduser()
    cands = []
    exe = shutil.which("BBDown")
    if exe:
        cands.append(Path(os.path.realpath(exe)).parent / "BBDown.data")
    cands.append(Path.home() / "BBDown.data")
    for p in cands:
        if os.access(p.parent, os.W_OK):
            return p
    return Path.home() / "BBDown.data"


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

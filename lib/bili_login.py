#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 站扫码登录，产物是一份 BBDown 兼容的 BBDown.data。

    login.py [--timeout 180] [--qr both|png|text] [--qr-out PATH]

**为什么不直接用 `BBDown login`**：它没有任何选项可以关掉终端里那一大块 ASCII
二维码，而且跑起来就阻塞轮询到扫码为止 —— agent 调它会被挂死。这里自己走一遍
官方扫码 API，把二维码同时落成 PNG 文件和一小块文本，agent 想用哪个用哪个。
"""
import argparse
import os
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import bili_api

GENERATE = ("https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
            "?source=main-fe-header")
POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key="

# 二维码本身的有效期就是 180 秒，默认等待时间跟它对齐 —— 等更久没有意义，
# 到点了服务端只会回 86038。
DEFAULT_TIMEOUT = 180

# 轮询间隔。BBDown 用 1 秒；2 秒把请求数减半，而「已扫码」的反馈晚 2 秒
# 人是感觉不到的。
POLL_INTERVAL = 2

# data.code 的含义。外层 code 恒为 0，真正的状态在 data.code —— 这是个很容易
# 踩的坑，别去判外层。
SCAN_WAITING = 86101      # 还没扫
SCAN_CONFIRMING = 86090   # 扫了，等手机上点确认
SCAN_EXPIRED = 86038      # 码过期了
SCAN_OK = 0


def log(msg=""):
    print(msg, flush=True)


# ---------- API ----------
def generate():
    """申请二维码，返回 (要编码进码的 url, qrcode_key)。失败返回 (None, None)。"""
    body = bili_api.get_json(GENERATE)
    data = (body or {}).get("data") or {}
    return data.get("url"), data.get("qrcode_key")


def poll(qrcode_key):
    """轮询一次。返回 (data.code, data.url, set_cookie 字典)。

    登录 cookie 有两种下发方式，**两种都得接**：
      · 响应头 Set-Cookie（B 站现在走这条，account.bilibili.com 新端点）
      · body 里 data.url 的 query string（BBDown 当年写的那条，老端点）
    只认一种就会在对方改版时静默失败 —— 实际就踩过：扫码明明成功了，
    data.url 里却没有 SESSDATA。
    """
    body, jar = bili_api.get_json_with_cookies(POLL + qrcode_key)
    if not body:
        return None, "", {}
    data = body.get("data") or {}
    return data.get("code"), data.get("url") or "", jar


# BBDown.data 里的字段顺序（照它写的顺序来，纯粹为了 diff 时好看）。
# 前四个是真 cookie，Expires/gourl/first_domain 是老端点 URL 的伴生参数，
# 新端点没有它们 —— 缺了也完全不影响使用。
COOKIE_ORDER = ("DedeUserID", "DedeUserID__ckMd5", "Expires", "SESSDATA",
                "bili_jct", "gourl", "first_domain")
REQUIRED = "SESSDATA"


def build_cookie(url, jar):
    """把两个来源合并成 BBDown.data 的内容。返回 (内容, 用到的字段名列表)。

    Set-Cookie 优先（那是权威的 cookie），data.url 的 query 兜底。
    """
    from urllib.parse import parse_qsl
    merged = {}
    for k, v in parse_qsl(urlsplit(url).query):        # 兜底来源
        if v:
            merged[k] = v
    merged.update({k: v for k, v in (jar or {}).items() if v})   # 权威来源覆盖

    ordered = [k for k in COOKIE_ORDER if k in merged]
    ordered += [k for k in merged if k not in COOKIE_ORDER]
    # 值里的英文逗号要转义，否则 BBDown 解析 cookie 串时会断错
    parts = [f"{k}={merged[k].replace(',', '%2C')}" for k in ordered]
    return ";".join(parts), ordered


# ---------- 二维码 ----------
def render(url, want, png_path):
    """产出二维码。返回 (png 绝对路径或 None, 文本二维码或 None)。"""
    try:
        import segno
    except ImportError:
        log("✗ 缺 segno（纯 Python 的二维码库，自身零依赖）")
        log("  -> pip install segno")
        log("")
        log("  装不了的话，把下面这个链接自己转成二维码也能扫（180 秒内有效）：")
        log(f"  {url}")
        log("  ⚠ 别把它贴给在线二维码网站 —— 这个链接等于半个登录凭据。")
        return None, None

    qr = segno.make(url)
    png = text = None
    if want in ("both", "png"):
        png_path.parent.mkdir(parents=True, exist_ok=True)
        # scale=8 -> 每个模块 8 像素，手机隔着屏幕也扫得到
        qr.save(str(png_path), scale=8, border=2)
        png = str(png_path.resolve())
    if want in ("both", "text"):
        import io
        buf = io.StringIO()
        # compact=True 用 Unicode 半块字符，高度只有普通字符码的一半
        qr.terminal(out=buf, compact=True, border=2)
        text = buf.getvalue()
    return png, text


def present(url, png, text):
    """把二维码交给用户 —— agent 会把这段原样转述出去。"""
    log("=" * 60)
    log("用手机 B 站 App 扫下面的二维码登录（180 秒内有效）")
    log("=" * 60)
    if png:
        log(f"\n[二维码图片] {png}")
        log("  （agent：请把这张图显示给用户；用户也可以自己打开它）")
    if text:
        log("")
        log(text)
    log(f"[登录链接] {url}")
    log("")


# ---------- 落盘 ----------
def write_cookie(content, target):
    """写 BBDown.data。覆盖前先备份，别把人家原来的登录态弄没了。"""
    target = target.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.read_text(encoding="utf-8").strip():
        bak = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(target, bak)
        log(f"  · 原有登录态已备份到 {bak}")
    # 单行、无行尾换行 —— 跟 BBDown 写出来的一模一样
    target.write_text(content, encoding="utf-8")
    try:
        os.chmod(target, 0o600)      # 这是登录凭据，别让同机其他用户读
    except OSError:
        pass
    return target


def logged_in():
    """当前 cookie 是不是真的还能用。空字幕列表分不出「没字幕」和「没登录」，
    所以这里用一个必定需要登录态的判断：cookie 文件存在且含 SESSDATA。"""
    p = bili_api.cookie_file()
    if not p:
        return None
    try:
        return p if "SESSDATA=" in p.read_text(encoding="utf-8") else None
    except OSError:
        return None


# ---------- 主流程 ----------
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="B 站扫码登录，写出 BBDown 兼容的 BBDown.data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="agent 请用这个，别调 `BBDown login` —— 那个会糊一屏 ASCII 且不返回。")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help=f"最多等多少秒（默认 {DEFAULT_TIMEOUT}，等于二维码有效期）")
    ap.add_argument("--qr", choices=("both", "png", "text"), default="both",
                    help="二维码产出形式（默认 both）")
    ap.add_argument("--qr-out", default="bili-login-qr.png",
                    help="二维码 PNG 落在哪（默认当前目录）")
    ap.add_argument("--proxy", default=None,
                    help="给 B 站请求挂代理，如 socks5://127.0.0.1:1080")
    ap.add_argument("--force", action="store_true",
                    help="已经登录了也重新登录")
    ap.add_argument("--debug", action="store_true",
                    help="失败时多打一点诊断（**只打字段名，绝不打值**）")
    args = ap.parse_args(argv)

    if args.proxy:
        for k in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy",
                  "HTTP_PROXY", "http_proxy"):
            os.environ[k] = args.proxy

    if not args.force:
        have = logged_in()
        if have:
            log(f"✓ 已经登录过了：{have}")
            log("  要换账号或刷新登录态就加 --force。")
            return 0

    url, key = generate()
    if not url or not key:
        log("✗ 申请二维码失败。网络不通 / 需要代理 / B 站接口在抽风。")
        return 1

    png_path = Path(args.qr_out).expanduser()
    png, text = render(url, args.qr, png_path)
    if not png and not text:
        return 1
    present(url, png, text)

    def cleanup():
        # 这张图编码的就是登录链接，用完立刻删，别留在磁盘上
        if png:
            Path(png).unlink(missing_ok=True)

    log(f"等待扫码…（最多 {args.timeout} 秒）")
    deadline = time.time() + args.timeout
    said_confirming = False
    try:
        while time.time() < deadline:
            time.sleep(POLL_INTERVAL)
            code, ok_url, jar = poll(key)
            if code is None:
                continue                      # 网络抖一下，接着轮询
            if code == SCAN_WAITING:
                continue
            if code == SCAN_CONFIRMING:
                if not said_confirming:
                    log("  · 已扫码，请在手机上点「确认登录」")
                    said_confirming = True
                continue
            if code == SCAN_EXPIRED:
                log("✗ 二维码已过期（180 秒），重新跑一次这条命令。")
                cleanup()
                return 1
            if code == SCAN_OK:
                content, names = build_cookie(ok_url, jar)
                if REQUIRED not in names:
                    log("✗ 扫码成功了，但两个来源里都没找到 SESSDATA，写不了登录态。")
                    log("  这通常意味着 B 站又改了返回格式。带 --debug 再跑一次，"
                        "它只打字段名、不打任何值，把输出发给维护者即可。")
                    if args.debug:
                        from urllib.parse import parse_qsl
                        log(f"  [debug] Set-Cookie 字段名: "
                            f"{sorted(jar) or '（空）'}")
                        log(f"  [debug] data.url query 字段名: "
                            f"{sorted(k for k, _ in parse_qsl(urlsplit(ok_url).query)) or '（空）'}")
                        log(f"  [debug] data.url 的 host: "
                            f"{urlsplit(ok_url).netloc or '（空）'}")
                    cleanup()
                    return 1
                target = write_cookie(content, bili_api.cookie_target())
                cleanup()
                log(f"✓ 登录成功，登录态已写入 {target}")
                log(f"  写入字段：{', '.join(names)}")
                log("  这个文件等价于你的 B 站账号登录态，别提交进仓库、别分享。")
                log("  验证：跑一下同目录的 doctor.py")
                return 0
            log(f"✗ 没见过的状态码 data.code={code}，中止。")
            cleanup()
            return 1
    except KeyboardInterrupt:
        log("\n已取消。")
        cleanup()
        return 130

    log(f"✗ 等了 {args.timeout} 秒没等到扫码，重新跑一次这条命令。")
    cleanup()
    return 1

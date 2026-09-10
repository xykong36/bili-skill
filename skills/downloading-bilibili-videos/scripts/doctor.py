#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""依赖自检。缺什么就告诉你装什么命令，别等到下载到一半才炸。

    doctor.py [--canary BV1xxx]
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

import _paths  # noqa: F401
import bili_api

# 一个公开的、确认存在的视频，用来验证「能不能连上 B 站接口」。
# 它哪天可能被删；换一个随便什么公开 BV 都行。
DEFAULT_CANARY = os.environ.get("BILI_CANARY", "BV1zsXbBVE5d")


# 可选依赖：缺了只是少一部分功能，不是跑不了。
OPTIONAL = {"segno": "扫码登录用"}
missing_optional = []


def row(name, ok, detail, fix=""):
    mark = "✓" if ok else ("!" if name in OPTIONAL else "✗")
    line = f"{mark} {name:<12} {detail}"
    if not ok and fix:
        line += f"\n               -> {fix}"
    print(line)
    if not ok and name in OPTIONAL:
        missing_optional.append(name)
        return True          # 不算硬失败
    return ok


def main():
    ap = argparse.ArgumentParser(description="downloading-bilibili-videos 依赖自检")
    ap.add_argument("--canary", default=DEFAULT_CANARY,
                    help="用来探接口连通性的 BV 号")
    args = ap.parse_args()

    all_ok = True
    for name, exe, fix in [
        ("BBDown", "BBDown", "https://github.com/nilaoda/BBDown/releases 下载后放进 PATH"),
        ("ffprobe", "ffprobe", "brew install ffmpeg"),
        ("curl", "curl", "系统自带，PATH 被裁了才会缺"),
    ]:
        p = shutil.which(exe)
        all_ok &= row(name, bool(p), p or "未找到", fix)

    try:
        import segno  # noqa: F401
        row("segno", True, "扫码登录用")
    except ImportError:
        row("segno", False, "未安装（扫码登录用）", "pip install segno")

    ck = bili_api.cookie_file()
    row("登录 cookie", bool(ck), str(ck) if ck else "未找到 BBDown.data",
        "跑一次 `python3 scripts/login.py` 扫码登录。下载公开视频不一定需要，"
        "但抓官方字幕必须要（digesting skill 会用到）")

    proxies = [k for k in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY")
               if os.environ.get(k)]
    if proxies:
        vals = {os.environ[k] for k in proxies}
        row("代理", True, f"{', '.join(sorted(vals))}（BBDown 只认 socks5://，不认 socks5h://）")

    print()
    d = bili_api.view_raw(args.canary)
    if d:
        row("B站接口", True, f"{args.canary} -> {d.get('title', '')[:40]}")
    else:
        all_ok = False
        row("B站接口", False, f"{args.canary} 查不到",
            "可能是：网络不通 / 需要代理 / 被限流（限流时接口静默返回空，不报错）/ "
            "这个 canary 视频被删了（换一个：--canary <任意公开BV>）")

    print()
    if not all_ok:
        print("有 ✗，那是硬依赖，先补齐再跑 download.py。")
    elif missing_optional:
        print("下载链路就绪。带 ! 的只有扫码登录要用，"
              "已经有登录态的话不装也行。")
    else:
        print("全部就绪。")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

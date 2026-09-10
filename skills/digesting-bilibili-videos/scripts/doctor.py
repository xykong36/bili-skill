#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""依赖自检。重点是区分「这个视频没字幕」和「你没登录 / 被限流」——
这两种情况接口的返回是一样的（都是空列表），不探一下分不出来。

    doctor.py [--canary BV1xxx]
"""
import argparse
import os
import shutil
import sys

import _paths  # noqa: F401
import bili_api
from lib import skill_config

# 一个公开的、确认有官方中文 AI 字幕的视频。它哪天可能被删或撤字幕，
# 那时换成任意一个你确认有 AI 字幕的公开 BV 即可（--canary 或 BILI_CANARY）。
DEFAULT_CANARY = os.environ.get("BILI_CANARY", "BV1zsXbBVE5d")


# 可选依赖：缺了只是少一部分功能，不是跑不了。
OPTIONAL = {"fpdf": "--skip-pdf", "fontTools": "--skip-pdf",
            "DEEPSEEK_API_KEY": "--skip-mindmap"}
# segno 只有「还没登录、需要扫码」时才用得上，单独处理（它没有对应的 flag）。
SOFT = {"segno"}
missing_optional = {}


def row(name, ok, detail, fix=""):
    mark = "✓" if ok else ("!" if name in OPTIONAL or name in SOFT else "✗")
    print(f"{mark} {name:<16} {detail}")
    if not ok and fix:
        print(f"                   -> {fix}")
    if not ok and name in OPTIONAL:
        missing_optional[name] = OPTIONAL[name]
        return True          # 不算硬失败
    if not ok and name in SOFT:
        return True
    return ok


def main():
    ap = argparse.ArgumentParser(description="digesting-bilibili-videos 依赖自检")
    ap.add_argument("--canary", default=DEFAULT_CANARY,
                    help="一个已知有官方中文 AI 字幕的 BV 号")
    args = ap.parse_args()
    skill_config.load_dotenv()
    all_ok = True

    p = shutil.which("curl")
    all_ok &= row("curl", bool(p), p or "未找到", "系统自带，PATH 被裁了才会缺")

    for mod, why, fix in [
        ("fpdf", "出 PDF 用", "pip install fpdf2"),
        ("fontTools", "字体实例化用", "pip install fonttools"),
    ]:
        try:
            __import__(mod)
            row(mod, True, why)
        except ImportError:
            all_ok &= row(mod, False, f"未安装（{why}；加 --skip-pdf 可以不要它）", fix)

    try:
        from lib import pdftext
        row("中文字体", pdftext.VAR_FONT.is_file(),
            str(pdftext.VAR_FONT) if pdftext.VAR_FONT.is_file() else "缺失")
    except ImportError:
        pass

    key = os.environ.get("DEEPSEEK_API_KEY")
    all_ok &= row("DEEPSEEK_API_KEY", bool(key),
                  f"已设置（{key[:6]}…）" if key else "未设置",
                  "echo 'DEEPSEEK_API_KEY=sk-...' >> .env.local"
                  "（或加 --skip-mindmap 只要字幕和可读版）")

    try:
        import segno  # noqa: F401
        row("segno", True, "扫码登录用")
    except ImportError:
        row("segno", False, "未安装（扫码登录用）", "pip install segno")

    ck = bili_api.cookie_file()
    all_ok &= row("登录 cookie", bool(ck), str(ck) if ck else "未找到 BBDown.data",
                  "跑 `python3 scripts/login.py` 扫码登录。"
                  "**字幕接口没有它就只会返回空列表**")

    print()
    meta = bili_api.view_by_bvid(args.canary)
    if not meta:
        print(f"✗ 连不上 B 站接口（canary {args.canary} 查不到）")
        print("   -> 网络不通 / 需要代理 / 被限流 / 这个 canary 视频被删了")
        return 1
    row("B站接口", True, f"{args.canary} -> {meta['title'][:36]}")

    subs = bili_api.subtitle_list(meta["aid"], meta["cid"], meta["bvid"])
    zh = [l for l, _ in subs if l.endswith("zh")]
    if zh:
        row("字幕接口", True, f"canary 拿到 {', '.join(zh)} —— 登录态有效")
    else:
        all_ok = False
        row("字幕接口", False,
            f"canary 也拿不到中文字幕（返回 {len(subs)} 条其它语言）",
            "这说明不是「某个视频恰好没字幕」，而是 cookie 失效或被限流。"
            "先 `python3 scripts/login.py --force` 重新登录；还不行就等一会儿再试。")

    print()
    if not all_ok:
        print("有 ✗，那是硬依赖，先补齐再跑 digest.py。")
    elif missing_optional:
        flags = " ".join(sorted(set(missing_optional.values())))
        print(f"核心链路就绪。带 ! 的是可选项，缺了就加 {flags} 跑，"
              f"仍然能拿到字幕和可读版。")
    else:
        print("全部就绪。")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

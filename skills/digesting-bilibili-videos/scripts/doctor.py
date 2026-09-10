#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""依赖自检。两条工作流分组报告，各自结论独立。

重点是区分「这个视频没字幕」和「你没登录 / 被限流」—— 这两种情况接口
的返回是一样的（都是空列表），不拿一个已知有字幕的 canary 探一下分不出来。

退出码是个位掩码，好让调用方知道**是哪条**工作流不可用：

    0  两条都能跑
    1  下载不可用
    2  嚼不可用
    3  两条都不可用

    bili.py doctor [--canary BV1xxx]
"""
import os
import shutil
import sys

import _paths  # noqa: F401
import bili_api
from lib import skill_config

# 一个公开的、确认有官方中文 AI 字幕的视频。它哪天可能被删或撤字幕，
# 那时换成任意一个你确认有 AI 字幕的公开 BV 即可（--canary 或 BILI_CANARY）。
DEFAULT_CANARY = os.environ.get("BILI_CANARY", "BV1zsXbBVE5d")

DOWNLOAD, DIGEST = 1, 2

LOGIN_FIX = "跑 `python3 scripts/bili.py login` 扫码登录"


def _row(mark, name, detail, fix=""):
    print(f"  {mark} {name:<17} {detail}")
    if fix:
        print(f"    {'':<17} -> {fix}")


def ok_(name, detail):
    _row("✓", name, detail)


def soft(name, detail, fix=""):
    """缺了只是少一部分功能，有 flag 能绕过 —— 不进掩码。"""
    _row("!", name, detail, fix)


def hard(name, detail, fix=""):
    _row("✗", name, detail, fix)


def skipped(name, why):
    """没探，且说清为什么没探 —— 比探一次报个说明不了问题的失败要好。"""
    _row("·", name, why)


def run(canary=None):
    canary = canary or DEFAULT_CANARY
    skill_config.load_dotenv()
    blocked = 0

    # ---------------- 共用 ----------------
    print("共用")
    p = shutil.which("curl")
    if p:
        ok_("curl", p)
    else:
        hard("curl", "未找到", "系统自带，PATH 被裁了才会缺")
        blocked |= DOWNLOAD | DIGEST

    meta = bili_api.view_by_bvid(canary)
    if meta:
        ok_("B站接口", f"{canary} -> {meta['title'][:34]}")
    else:
        hard("B站接口", f"canary {canary} 查不到",
             "网络不通 / 被限流（限流时接口静默返回空，不报错）/ "
             "这个 canary 视频被删了（换一个：--canary <任意公开BV>）")
        blocked |= DOWNLOAD | DIGEST

    ck = bili_api.cookie_file()

    # ---------------- 下载 ----------------
    print("\n下载")
    for name, fix in [
        ("BBDown", "https://github.com/nilaoda/BBDown/releases 下载后放进 PATH"),
        ("ffprobe", "brew install ffmpeg"),
        ("ffmpeg", "brew install ffmpeg"),
    ]:
        p = shutil.which(name)
        if p:
            ok_(name, p)
        else:
            hard(name, "未找到", fix)
            blocked |= DOWNLOAD

    # 下载这条**不读** cookie：BBDown 自己去找 BBDown.data。缺了只是拿不到
    # 高清流，不影响正确性 —— 所以这里是 !，同一行在下面的「嚼」里是 ✗。
    if ck:
        ok_("登录 cookie", str(ck))
    else:
        soft("登录 cookie", "未找到（下载公开视频不需要，但没有它只能拿到低清流）",
             LOGIN_FIX)

    # ---------------- 嚼 ----------------
    print("\n嚼")
    # 字幕接口没有 cookie 就只返回空列表，且不报错 —— 这条是硬依赖。
    if ck:
        ok_("登录 cookie", str(ck))
    else:
        hard("登录 cookie", "未找到 BBDown.data",
             f"{LOGIN_FIX}。**字幕接口没有它只会返回空列表，而且不报错**")
        blocked |= DIGEST

    if not ck:
        # 没 cookie 时探字幕接口必然是空的，报出来说明不了任何问题。
        skipped("字幕接口", "跳过（没有 cookie，探了也说明不了问题）")
    elif not meta:
        skipped("字幕接口", "跳过（B站接口都不通）")
    else:
        subs = bili_api.subtitle_list(meta["aid"], meta["cid"], meta["bvid"])
        zh = [l for l, _ in subs if l.endswith("zh")]
        if zh:
            ok_("字幕接口", f"canary 拿到 {', '.join(zh)} —— 登录态有效")
        else:
            hard("字幕接口",
                 f"canary 也拿不到中文字幕（返回 {len(subs)} 条其它语言）",
                 "这说明不是「某个视频恰好没字幕」，而是 cookie 失效或被限流。"
                 "先 `bili.py login --force`；还不行就等一会儿再试")
            blocked |= DIGEST

    # 没配 key 必须报 ✓ 而不是 !。「!」的语义是「缺了少功能」，可这里没 key 是一个
    # 完整可用的配置 —— 大纲由跑这个 skill 的 agent 自己写。报成 ! 会让 agent 继续
    # 去劝用户买 key，正好跟这个 skill 要的「自适应到当前 agent」相反。
    #
    # 另外这里**不回显 key 的任何片段**。以前打的是 key[:6]，那会把真 key 的前缀
    # 写进 agent 的上下文和终端回滚，白白多一个泄漏面。报出处的变量名就够定位了。
    kind, info = skill_config.resolve_mindmap()
    if kind == "api":
        ok_("脑图后端", f"API {info['model']} @ {info['base']}"
                        f"（来自 {info['via']}，无人值守）")
    elif kind == "claude":
        ok_("脑图后端", "claude CLI 子进程（显式指定）")
    elif kind == "error":
        hard("脑图后端", info, "去掉 BILI_MINDMAP_BACKEND 就退回默认（交给当前 agent）")
        blocked |= DIGEST
    else:
        ok_("脑图后端", "交给当前 agent —— 第 3 步由你自己写大纲（默认方式，不是缺陷）。"
                        "想无人值守就配个 key："
                        "echo 'DEEPSEEK_API_KEY=sk-...' >> .env.local")

    if skill_config.PROMPT_PATH.is_file():
        ok_("脑图 prompt", str(skill_config.PROMPT_PATH))
    else:
        hard("脑图 prompt", f"缺失：{skill_config.PROMPT_PATH}",
             "这个文件随 skill 一起装，缺了说明装歪了 —— 重装这个 skill")
        blocked |= DIGEST

    for mod, why, fix in [("fpdf", "出 PDF 用", "pip install fpdf2"),
                          ("fontTools", "字体实例化用", "pip install fonttools")]:
        try:
            __import__(mod)
            ok_(mod, why)
        except ImportError:
            soft(mod, f"未安装（{why}）", f"{fix}，或加 --skip-pdf")

    try:
        from lib import pdftext
        if pdftext.VAR_FONT.is_file():
            ok_("中文字体", str(pdftext.VAR_FONT))
        else:
            # 字体是随 skill 自带的，缺了说明装歪了。--skip-pdf 能绕过，
            # 所以是 ! 不是 ✗ —— 但必须报出来，之前这行的结果是被丢掉的。
            soft("中文字体", f"缺失：{pdftext.VAR_FONT}",
                 "重装这个 skill，或设 BILI_SKILLS_FONT 指向一个中文 TTF，"
                 "或加 --skip-pdf")
    except ImportError:
        skipped("中文字体", "跳过（fpdf/fontTools 没装，查不了）")

    # ---------------- 登录 ----------------
    print("\n登录")
    try:
        import segno  # noqa: F401
        ok_("segno", "扫码登录用")
    except ImportError:
        soft("segno", "未安装（扫码登录时才要）", "pip install segno")

    # ---------------- 结论 ----------------
    print()
    say = {0: "两条工作流都能跑。",
           DOWNLOAD: "嚼可用；**下载**不可用，见上面的 ✗。",
           DIGEST: "下载可用；**嚼**不可用，见上面的 ✗。",
           DOWNLOAD | DIGEST: "两条都不可用，见上面的 ✗。"}[blocked]
    print(say)
    print("带 ! 的是可选项：缺了用对应的 flag 绕过，核心链路不受影响。")
    return blocked


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="digesting-bilibili-videos 自检")
    ap.add_argument("--canary", default=None,
                    help="一个已知有官方中文 AI 字幕的 BV 号")
    return run(ap.parse_args(argv).canary)


if __name__ == "__main__":
    sys.exit(main())

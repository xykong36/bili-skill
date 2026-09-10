#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 站视频：存下来，或者嚼成能读的东西。这个 skill 的唯一入口。

    bili.py doctor
    bili.py login    [--force]
    bili.py download BV1xxx [BV2 ...] --out DIR
    bili.py digest   BV1xxx [BV2 ...] --out DIR [--name 书名] [--with-video]
    bili.py digest   --srt path/to.srt --title 标题 --out DIR
    bili.py digest   BV1xxx [...] --out DIR --build     收尾（见下）

脑图那步不强制要 API key：配了就无人值守跑；没配就由**跑这个 skill 的 agent**
按 assets/mindmap-outline-prompt.md 把阅读版写成 <stem>.source.txt，再用
--build 收尾出脑图/大纲/PDF。退出码 2 就是「没坏，有几期大纲在等你写」。

digest 退出码：0 全成 / 1 有东西坏了 / 2 有几期在等 agent 写大纲

两条工作流**并列，不是流水线**：字幕直接走接口拿、全程不碰 mp4，
所以想要文字不必先下视频。--with-video 只是把两条各跑一遍。

只有一个入口，是为了让 SKILL.md 的 allowed-tools 只需要一条规则：
    Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/bili.py *)
"""
import argparse
import sys
from pathlib import Path

import _paths  # noqa: F401  把 <plugin>/lib 和 <skill> 挂上 sys.path

import digest
import download


def _out(arg):
    """输出目录只在这里解析一次，两条工作流共用同一个 Path。"""
    return Path(arg).expanduser().resolve()


def cmd_download(args):
    return download.run(args.targets, _out(args.out), args.max_mb,
                        not args.no_video, args.stem_title)


def cmd_digest(args):
    out = _out(args.out)
    if not args.targets and not args.srt:
        sys.exit("给几个 BV 号，或者用 --srt 指定本地字幕文件")

    rc_video = 0
    if args.with_video:
        if args.srt:
            sys.exit("--with-video 要 BV 号才能下视频，跟 --srt 一起用没意义")
        # --with-video 强制 --stem-title：否则 mp4 落成 BV1xxx.mp4，而字幕那边
        # 是「日期-标题-BV」，同一个目录里看着像两个不相干的东西。
        # 两侧的 stem 公式已经统一（_common.stem_for），强制是安全的。
        rc_video = download.run(args.targets, out, args.max_mb,
                                want_video=True, stem_title=True)
        if rc_video:
            # 视频没下成不影响字幕 —— 两条工作流没有依赖关系，把无依赖的
            # 失败做成阻断只会让用户白丢字幕。
            log_sep("视频这条没全成，字幕流程照常继续")

    rc_text = digest.run(args.targets, out, args.name, args.skip_mindmap,
                         args.skip_pdf, args.srt, args.title, args.duration,
                         args.mindmap_backend, args.build)
    return rc_text or rc_video


def log_sep(msg):
    print(f"\n! {msg}\n", flush=True)


def cmd_doctor(args):
    import doctor
    return doctor.run(args.canary)


def cmd_login(rest):
    """login 的参数原样转给 bili_login —— 它自己已经有完整的 argparse。"""
    import bili_login
    return bili_login.main(rest)


def build_parser():
    ap = argparse.ArgumentParser(
        prog="bili.py",
        description="B 站视频：存下来（download），或者嚼成能读的东西（digest）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例：bili.py digest BV1xxx --out ./out --name 我的合集")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # --out 只对两条真正干活的工作流有意义 —— doctor 不写文件。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", default=".", help="输出目录（默认当前目录）")

    d = sub.add_parser("download", parents=[common], help="下正片 + 封面 + 元信息")
    d.add_argument("targets", nargs="+", help="BV 号或视频链接，可给多个")
    d.add_argument("--max-mb", type=int, default=download.DEFAULT_MAX_MB,
                   help=f"正片体积上限 MB，超过就只出封面+info；0=不限"
                        f"（默认 {download.DEFAULT_MAX_MB}）")
    d.add_argument("--no-video", action="store_true",
                   help="只出封面和 info.json，完全不下正片")
    d.add_argument("--stem-title", action="store_true",
                   help="文件名用「日期-标题-BV」而不是光秃秃的 BV 号")
    d.set_defaults(func=cmd_download)

    g = sub.add_parser("digest", parents=[common],
                       help="官方 AI 字幕 -> 阅读版 / 脑图 / 大纲 / PDF")
    g.add_argument("targets", nargs="*", help="BV 号或视频链接")
    g.add_argument("--srt", help="改用本地 srt 文件作为输入（不联网抓字幕）")
    g.add_argument("--title", help="配合 --srt 用的标题")
    g.add_argument("--duration", type=int, default=0,
                   help="配合 --srt 用的视频时长（秒）；不给就按字幕末尾推算")
    g.add_argument("--name", default="B站合集", help="PDF 书名")
    g.add_argument("--skip-pdf", action="store_true",
                   help="不出 PDF（省掉 fpdf2 依赖）")
    g.add_argument("--skip-mindmap", action="store_true",
                   help="只要字幕和阅读版，不做脑图那步（既不调 API，也不找 agent 要大纲）")
    g.add_argument("--build", action="store_true",
                   help="收尾：把每期已写好的 .source.txt 当大纲，出脑图/大纲/PDF")
    g.add_argument("--mindmap-backend", choices=["auto", "api", "agent", "claude"],
                   default=None,
                   help="auto（默认）配了 key 走 API、没配交给当前 agent；"
                        "agent 即使配了 key 也交给 agent")
    g.add_argument("--with-video", action="store_true",
                   help="顺便把正片也下下来（等于两条工作流各跑一遍）")
    g.add_argument("--max-mb", type=int, default=download.DEFAULT_MAX_MB,
                   help="配合 --with-video 的体积上限")
    g.set_defaults(func=cmd_digest)

    k = sub.add_parser("doctor", help="自检：缺什么、装什么命令")
    k.add_argument("--canary", default=None, help="用来探接口的已知有字幕的 BV")
    k.set_defaults(func=cmd_doctor)

    sub.add_parser("login", help="扫码登录，写出 BBDown.data",
                   add_help=False)  # 参数原样转给 bili_login

    return ap


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    # login 的参数不由这里解析，直接原样转走。
    if argv and argv[0] == "login":
        return cmd_login(argv[1:])

    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

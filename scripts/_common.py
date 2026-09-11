#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""download 和 digest 两条工作流共用的小原语。

合并前这些在两个脚本里各有一份逐字相同的副本（BV 正则、日志、文件名
清洗、BV 抽取去重……），改一处忘另一处发生过好几次。

放进来的标准只有一条：**两侧行为必须完全一致**。两侧真有分歧的都不在
这里，那些分歧是实测出来的，不是疏忽：

  · 退出码   download 把「认不出的目标」计进失败，digest 只告警
             —— 所以 collect_bvs 把 bad 原样返回，由调用方定夺
  · 产物校验 封面用「存在且非空」够了，正片必须走 verify_mp4
             —— 见 fresh() 的警告
"""
import re
import sys

BV_RE = re.compile(r"(BV[0-9A-Za-z]{8,12})")

# B 站标题里什么字符都可能有，这几个在某个主流文件系统上是非法的。
UNSAFE = str.maketrans({c: "_" for c in '/\\:*?"<>|'})


def log(msg=""):
    print(msg, flush=True)


def safe_title(title):
    return (title or "").translate(UNSAFE).strip()


def parse_target(arg):
    """从 BV 号、视频 URL、或带一堆 query 参数的分享链接里抠出 BV 号。"""
    m = BV_RE.search(arg or "")
    return m.group(1) if m else None


def collect_bvs(targets):
    """targets -> (去重后的 BV 列表, 认不出的原始串)。一个都没有就直接退出。

    保持用户给的顺序：同一个 BV 给两遍只做一遍，但不打乱次序。

    bad 单独返回而不是就地吞掉，是因为两侧口径不同：download 把它计进
    退出码（给了个打错的链接就该非零退出），digest 只当告警。不要在这里
    替调用方做决定。
    """
    bvs, bad = [], []
    for t in targets:
        bv = parse_target(t)
        (bvs if bv else bad).append(bv or t)
    for t in bad:
        log(f"✗ 认不出 BV 号: {t}")
    bvs = list(dict.fromkeys(bvs))
    if not bvs:
        sys.exit("没有可处理的 BV 号")
    return bvs, bad


def stem_for(bv, title=None, pubdate=None):
    """产物文件名主干。给了标题就用「日期-标题-BV」，否则光秃秃的 BV。

    截到 180 字符：给 `-阅读版.md`、`.info.json` 这类后缀留余量，同时避开
    ext4/APFS 那条 255 字节的上限（一个中文字最多占 3 字节）。
    """
    if not title:
        return bv
    return f"{pubdate or '00000000'}-{safe_title(title)}-{bv}"[:180]


def fresh(path):
    """产物已经在了且非空 —— 幂等跳过的判据。

    非空这一半不能省：下载/生成被打断留下的 0 字节文件也 is_file()。

    **别拿这个判正片 mp4。** 坏掉的 mp4 体积看着完全正常，这个判据必然
    放过它。正片走 download.verify_mp4()：容器能解析 + 音视频轨都在 +
    最后一个视频包的 pts 覆盖到片尾。理由见
    references/mp4-integrity.md。
    """
    return path.is_file() and path.stat().st_size > 0

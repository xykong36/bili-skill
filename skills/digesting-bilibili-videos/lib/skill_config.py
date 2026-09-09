#!/usr/bin/env python3
"""本 skill 的全部可调项。没有别的配置文件，改行为就改这里或设环境变量。

设计上刻意不引入 venv / DEPS_HOME 那套：fpdf2 和 fonttools 装进用户当前的
Python 环境即可，字体静态实例落用户缓存目录。
"""
import os
from pathlib import Path

# ---------- 字幕质量闸门 ----------
# 字幕末条时间戳至少要覆盖视频时长的这个比例，否则判定「残缺」。
# 不设 1.0：片尾常有几十秒无语音的音乐/挂件段，最后一条字幕本来就不顶到末尾。
# 也别调到 0.7：那会接受一份漏掉整整 30% 视频的字幕，下游大纲和脑图跟着缺一大段。
COVERAGE_MIN = float(os.environ.get("BILI_COVERAGE_MIN", "0.90"))

# 字幕比视频长这么多倍就判定「这不是这个视频的字幕」（老接口串号的特征，
# 实测命中值 302% / 214% / 186%）。留 5% 余量给末尾时间戳的抖动。
MISMATCH_MAX = float(os.environ.get("BILI_MISMATCH_MAX", "1.05"))

# ---------- 脑图后端 ----------
MINDMAP_BACKEND = os.environ.get("BILI_MINDMAP_BACKEND", "deepseek")
MINDMAP_MODEL = os.environ.get("BILI_MINDMAP_MODEL", "deepseek-v4-flash")

# gen_mindmap 子进程的墙钟上限。一小时字幕的整理实测在 2~5 分钟量级，
# 1800s 是给最长的播客类内容留的余量，不是随手写的数。
MINDMAP_TIMEOUT = int(os.environ.get("BILI_MINDMAP_TIMEOUT", "1800"))

# ---------- 缓存 ----------
# 变量字体定格出的静态实例落这里（每个字重一份，约 10MB），只算一次。
CACHE = Path(os.environ.get("BILI_SKILLS_CACHE",
                            Path.home() / ".cache" / "bili-skills"))

# ---------- .env ----------
def load_dotenv():
    """从当前目录逐级向上找 .env.local / .env 填进环境变量。

    已存在的真实环境变量不覆盖（先到先得），所以 `DEEPSEEK_API_KEY=... cmd`
    这种一次性覆盖始终有效。
    """
    d = Path.cwd()
    dirs = []
    while True:
        dirs.append(d)
        if d.parent == d:
            break
        d = d.parent
    for d in dirs:
        for name in (".env.local", ".env"):
            p = d / name
            if not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.removeprefix("export ").split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v


# ---------- 代理 ----------
# B站 端点可以走代理，但**走 urllib 的端点不能走 socks5**：urllib 不支持 socks5，
# 带着 socks5:// 就会连不上。代理变量是进程级的、子进程默认继承，所以要按后端处理。
#
# 别一刀切全剥：`claude` 后端是个普通 HTTPS 客户端，在需要代理才能出网的机器上
# 把代理剥掉，它会直接拿到 403 Request not allowed（实测踩过）。
PROXY_KEYS = ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy",
              "HTTP_PROXY", "http_proxy")


def env_direct():
    """去掉全部代理变量的环境副本。给必须彻底直连的子进程用。"""
    return {k: v for k, v in os.environ.items() if k not in PROXY_KEYS}


def env_for_backend(backend):
    """按后端裁剪代理，返回给子进程用的 env。

    · deepseek 走 urllib：只剥掉 socks5 的代理（urllib 不支持），
      http/https 代理保留 —— 在只能靠代理出网的机器上，剥光了反而连不上。
    · 其它后端（claude CLI 等）原样透传。
    """
    env = dict(os.environ)
    if backend != "deepseek":
        return env
    for k in PROXY_KEYS:
        v = env.get(k, "")
        if v.startswith("socks"):
            env.pop(k, None)
    return env

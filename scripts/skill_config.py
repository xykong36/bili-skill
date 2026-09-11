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
# 这一步只需要「一个能读长文本、会遵格式的模型」。跑这个 skill 的 agent 自己就是，
# 所以 API key 是可选加速项，不是前置条件。
#
#   auto   有 key 就走 HTTP，没有就交给当前 agent 写（默认）
#   api    强制走 HTTP，没 key 直接报错（deepseek 是它的别名，保留给老配置）
#   agent  强制交给当前 agent，即使配了 key
#   claude 起一个 claude CLI 子进程。**只留作显式 opt-in，auto 永远不会选它** ——
#          它只救 Claude、救不了 Codex/workbuddy，正好跟「自适应」相反；而且在
#          Claude Code 会话里再起一个 claude -p 是嵌套会话，计费和权限都有惊喜。
BACKEND_ENV = "BILI_MINDMAP_BACKEND"

# 喂给模型的 prompt。它是 payload 不是文档 —— 整个文件会被原样塞进 messages[0]，
# 所以放 assets/（和 fonts 一样是「被脚本原样吃掉的素材」）而不是 references/。
# 脚本和 agent 两个消费者必须读到逐字相同的东西。
PROMPT_PATH = Path(__file__).resolve().parent.parent / "assets" / "mindmap-outline-prompt.md"

# key 的查找顺序。(key 变量, base 变量, base 默认值, model 默认值, auto 会不会自动选它)
#
# **OPENAI_API_KEY 的 auto 位是 False，这是故意的。** 它在很多人机器上是常年导出的
# 环境变量，跟这个 skill 毫无关系。让 auto 认它，就会出现「用户想让手边的 agent 写
# 大纲，结果被一个八竿子打不着的 gpt-4o-mini 静默接管」—— 正好跟本 skill 要的
# 「自适应到当前 agent」相反。想用它就显式 BILI_MINDMAP_BACKEND=api。
#
# DEEPSEEK_API_KEY 排第一且 auto=True 是为了向后兼容：老用户什么都不用改，行为
# 与改动前逐字相同。BILI_LLM_API_KEY 带 BILI_ 前缀，本身就是对本 skill 的明确表态。
_KEYS = (
    ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "https://api.deepseek.com", "deepseek-v4-flash", True),
    ("BILI_LLM_API_KEY", "BILI_LLM_BASE_URL", "", "", True),
    ("OPENAI_API_KEY", "OPENAI_BASE_URL", "https://api.openai.com/v1", "gpt-4o-mini", False),
)


def mindmap_backend():
    """**必须在 load_dotenv() 之后调。**

    以前这里是模块级常量，在 import 时就求值了，而 load_dotenv() 是运行时才跑的
    —— 于是 .env.local 里写 BILI_MINDMAP_BACKEND=... 是被静默忽略的。做成函数是
    为了不继承那个 bug，别再改回常量。
    """
    return os.environ.get(BACKEND_ENV, "auto").strip() or "auto"


def llm_endpoint(auto_only=False):
    """返回 {"key","base","model","via"}；没有可用的 key 就返回 None。

    auto_only=True 时只认「用户明确为这个 skill 配的」key，见 _KEYS 上面那段注释。
    """
    for k_env, b_env, b_default, m_default, auto_ok in _KEYS:
        if auto_only and not auto_ok:
            continue
        key = os.environ.get(k_env)
        if not key:
            continue
        base = (os.environ.get(b_env) or b_default).rstrip("/")
        model = os.environ.get("BILI_MINDMAP_MODEL") or m_default
        # BILI_LLM_API_KEY 是「任意 OpenAI 兼容端点」的口子，没有内置默认，
        # 必须自带 base 和 model，否则不知道往哪发、发给谁。
        if not base or not model:
            continue
        return {"key": key, "base": base, "model": model, "via": k_env}
    return None


def resolve_mindmap(backend=None):
    """脑图这步谁来干。-> ("api", ep) / ("agent", None) / ("claude", None) / ("error", 原因)"""
    b = backend or mindmap_backend()
    if b in ("api", "deepseek"):
        ep = llm_endpoint()
        if not ep:
            return ("error", f"{BACKEND_ENV}={b} 指定了走 API，但一个 API key 都没配。\n"
                             "  -> echo 'DEEPSEEK_API_KEY=sk-...' >> .env.local\n"
                             f"  或者去掉 {BACKEND_ENV}，默认就会交给当前 agent 自己写。")
        return ("api", ep)
    if b == "claude":
        return ("claude", None)
    if b == "agent":
        return ("agent", None)
    if b != "auto":
        return ("error", f"未知脑图后端: {b}（可选 auto / api / agent / claude）")
    ep = llm_endpoint(auto_only=True)
    return ("api", ep) if ep else ("agent", None)


def env_for_backend():
    """给 urllib 那条路剥掉 socks 代理。

    urllib 不认 socks5，机器上有 ALL_PROXY=socks5://... 时它会一路超时、重试三次
    才报「网络错误」，看着像 DeepSeek 挂了。这段逻辑 0.3.0 有过，在两个 skill 合并
    那次（78a9916）连同对应的 SKILL.md 排障行一起被静默删掉了，这里补回来。
    """
    env = dict(os.environ)
    for k in list(env):
        if k.lower().endswith("_proxy") and env[k].lower().startswith(("socks", "socks5h")):
            env.pop(k, None)
    return env

# gen_mindmap 子进程的墙钟上限。一小时字幕的整理实测在 2~5 分钟量级，
# 1800s 是给最长的播客类内容留的余量，不是随手写的数。
MINDMAP_TIMEOUT = int(os.environ.get("BILI_MINDMAP_TIMEOUT", "1800"))

# ---------- 缓存 ----------
# 变量字体定格出的静态实例落这里（每个字重一份，约 10MB），只算一次。
CACHE = Path(os.environ.get("BILI_SKILLS_CACHE",
                            Path.home() / ".cache" / "bili-skills"))

# ---------- .env ----------
def load_dotenv(*extra_dirs):
    """从当前目录逐级向上找 .env.local / .env 填进环境变量。

    已存在的真实环境变量不覆盖（先到先得），所以 `DEEPSEEK_API_KEY=... cmd`
    这种一次性覆盖始终有效。

    extra_dirs 追加在向上遍历之后（优先级最低）。gen_mindmap 用它把「脚本
    自身目录」加回来 —— 它被单独拉起时支持把 .env.local 放在自己旁边，
    统一到这个实现时不能把那个位置悄悄弄丢。
    """
    d = Path.cwd()
    dirs = []
    while True:
        dirs.append(d)
        if d.parent == d:
            break
        d = d.parent
    dirs.extend(Path(x) for x in extra_dirs)
    seen = set()
    for d in dirs:
        for name in (".env.local", ".env"):
            p = d / name
            if p in seen or not p.is_file():
                continue
            seen.add(p)
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

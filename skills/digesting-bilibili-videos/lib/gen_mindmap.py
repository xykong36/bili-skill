#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_mindmap.py —— 字幕文件 → OPML 思维导图(一个脚本跑完全流程)

用法:
    python3 gen_mindmap.py <字幕文件> [输出前缀]
        字幕文件: 带时间戳的 .srt / .md / .txt
        输出前缀: 默认 = 视频标题(同目录 .mp4 名, 否则文件夹名去 'BV..._' 前缀)
    可选:
        --backend auto|api|agent|claude
                                    auto(默认): 配了 key 就走 api, 没配就交给当前 agent
                                    api:    OpenAI 兼容端点(DeepSeek 是其中一个)
                                    agent:  不自己调模型, 让跑这个 skill 的 agent 写大纲
                                    claude: 起一个 claude CLI 子进程(显式 opt-in)
        --model M                   指定模型(claude 例: sonnet/haiku/opus)
        --outline                   把输入当作"已整理好的缩进大纲", 跳过 AI 这步
        --print-prompt              打印喂给模型的 prompt 后退出
        --duration N                视频时长(秒)。给了才会修复漏写小时位的时间戳
                                    (没有它无法判断补出来的时间是否超出视频)

    API 鉴权(可选! 不配就走 agent 那条路):
        A) 在 .env.local 写:  DEEPSEEK_API_KEY=sk-...   (脚本自动从当前目录逐级向上查找)
        B) 环境变量:          export DEEPSEEK_API_KEY=sk-...
        (可选) DEEPSEEK_BASE_URL / BILI_LLM_API_KEY+BILI_LLM_BASE_URL+BILI_MINDMAP_MODEL

流程:
    ① (AI 整理) 当前 agent / OpenAI 兼容 API / claude CLI 读字幕 → 缩进式大纲文本
    ② (解析)    缩进 → 树, 抽取 [mm:ss] 时间戳
    ③ (排序)    每个父节点下子节点按时间戳从早到晚
    ④ (编号)    层级序号 1 / 1.1 / 1.1.1
    ⑤ (输出)    <前缀>.opml   (顺带保存 <前缀>.source.txt 便于手动微调后重跑)

依赖: python3(仅标准库);  claude 后端需已登录的 claude CLI;  api 后端需一个 API key
      (agent 后端什么都不需要 —— 大纲由跑这个 skill 的 agent 自己写)
"""
import sys, os, re, subprocess, json, urllib.request, urllib.error
from pathlib import Path
from xml.sax.saxutils import escape

# 这个文件既被 digest 当子进程拉起，也支持单独跑，所以自己把 <skill> 挂上
# sys.path（和 pdftext.py 同一套做法）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import skill_config

INDENT = 2  # 大纲每级缩进空格数
NEAR_PARENT_SEC = 600  # 补小时位后允许离父节点多远(秒)，见 repair_timestamps

def load_prompt():
    """从 assets 读 prompt。

    故意放在函数里而不是模块顶层：顶层读文件会让任何 import 这个模块的地方都可能炸,
    而 digest.py 走 agent 那条路时根本不需要 prompt。
    """
    try:
        return skill_config.PROMPT_PATH.read_text(encoding="utf-8").strip() + "\n"
    except OSError as e:
        sys.exit(f"读不到脑图 prompt: {skill_config.PROMPT_PATH}({e})。\n"
                 "这个文件随 skill 一起装, 缺了说明装歪了 —— 重装这个 skill。")


# ---------- ① AI: 字幕 -> 大纲 (多后端) ----------
def _clean(out):
    """去掉可能的 ``` 代码围栏行, 规整结尾"""
    out = "\n".join(l for l in out.splitlines() if not l.lstrip().startswith("```"))
    if not out.strip():
        sys.exit("模型返回空内容,请检查鉴权或重试。")
    return out.rstrip() + "\n"

def _outline_claude(subtitle_text, prompt, model=None):
    cmd = ["claude", "-p", prompt]
    if model:
        cmd += ["--model", model]
    print("① 用 claude CLI 把字幕整理成大纲 ...", file=sys.stderr)
    r = subprocess.run(cmd, input=subtitle_text, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"claude 调用失败(returncode={r.returncode}):\n{r.stderr.strip()}")
    return _clean(r.stdout)

def _outline_api(subtitle_text, prompt, ep):
    """OpenAI 兼容的 /chat/completions。DeepSeek 只是其中一个端点。"""
    payload = {
        "model": ep["model"],
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": subtitle_text},
        ],
        "temperature": 0.3,
        # 模型上限 1M 上下文 / 384K 输出, 这里给足以容纳最长一期的详细大纲; 按实际生成量计费,
        # 高上限只是天花板不会白花钱。典型一期正文 3~8k tokens, 长播客也远不到这个数。
        "max_tokens": 65536,
        "stream": False,
    }
    # v4-flash 默认开思考(reasoning), 且 reasoning tokens 计入 max_tokens——整篇字幕下
    # 思考很容易把一个偏小的 max_tokens 吃光, 正文一个字都没出(finish_reason=length)。
    # 这个整理任务不需要思考(旧的 deepseek-chat 本就是非思考), 关掉更快更省, 预算全给正文。
    # 关思考: reasoning_effort=none。想要思考版就删掉这行并把 max_tokens 留足。
    #
    # **只对 DeepSeek 端点带。** 这是个非标字段, 别家(含 OpenAI 官方)见到未知字段会
    # 直接 400, 泛化成任意 OpenAI 兼容端点之后必须按端点区分。
    if "deepseek" in ep["base"].lower() or ep["via"] == "DEEPSEEK_API_KEY":
        payload["reasoning_effort"] = "none"

    req = urllib.request.Request(
        ep["base"] + "/chat/completions", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {ep['key']}"},
    )
    thinking = "非思考" if "reasoning_effort" in payload else "默认思考设置"
    print(f"① 用 API({ep['model']} @ {ep['base']}, {thinking}) 把字幕整理成大纲 ...",
          file=sys.stderr)
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return _clean(data["choices"][0]["message"].get("content") or "")
        except urllib.error.HTTPError as e:
            # 4xx(鉴权/参数)重试也没用, 直接报错
            sys.exit(f"API 失败 {e.code}: {e.read().decode('utf-8', 'ignore')[:500]}")
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            last = e
    sys.exit(f"API 网络错误(重试 3 次仍失败): {last}\n"
             "  有 socks5 代理的话 urllib 不认它 —— 见 references/llm-mindmap.md")

def _handoff_to_agent(prefix):
    """agent 后端：这个进程写不出大纲，把该做什么说清楚然后退出。

    digest.py 不走这里 —— 它自己先 resolve_mindmap()，agent 模式下根本不拉起这个
    子进程。这条只服务「单独跑 gen_mindmap.py」的人。
    """
    print(f"⏸ 脑图这步没有配 API key，要由跑这个 skill 的 agent 来写大纲。\n"
          f"  1) 读 prompt: {skill_config.PROMPT_PATH}\n"
          f"  2) 按它把字幕整理成缩进式大纲，写到: {prefix}.source.txt\n"
          f"  3) 再跑一次，这次加 --outline 并把输入换成那个 .source.txt\n"
          f"  (想无人值守就配个 key: echo 'DEEPSEEK_API_KEY=sk-...' >> .env.local)",
          file=sys.stderr)
    sys.exit(3)

def subtitle_to_outline(subtitle_text, backend="auto", model=None, prefix="out"):
    kind, info = skill_config.resolve_mindmap(backend)
    if kind == "error":
        sys.exit(info)
    if kind == "agent":
        _handoff_to_agent(prefix)
    prompt = load_prompt()
    if kind == "claude":
        return _outline_claude(subtitle_text, prompt, model)
    return _outline_api(subtitle_text, prompt, info)

# ---------- ② 解析缩进大纲 -> 树 ----------
def parse(text):
    root = ("__root__", None, [])
    stack = [(-1, root)]
    for raw in text.splitlines():
        if not raw.strip():
            continue
        indent = (len(raw) - len(raw.lstrip(" "))) // INDENT
        s = raw.strip()
        m = re.match(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*)", s)
        ts, title = (m.group(1), m.group(2)) if m else (None, s)
        node = (title, ts, [])
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack[-1][1][2].append(node)
        stack.append((indent, node))
    kids = root[2]
    return kids[0] if len(kids) == 1 else ("思维导图", None, kids)

# ---------- ③ 排序 ----------
def ts_sec(ts):
    if not ts:
        return None
    p = [int(x) for x in ts.split(":")]
    return p[0] * 60 + p[1] if len(p) == 2 else p[0] * 3600 + p[1] * 60 + p[2]

def fmt_ts(sec):
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def repair_timestamps(node, parent_sec=None, report=None, max_sec=None):
    """补回被模型漏掉的小时位。

    模型会把 01:05:56 写成 05:56。这种节点的时间戳比父节点小一大截，
    加回整小时后如果落进父节点所在的那一小时内，就基本可以断定是漏了小时位。

    判定要同时满足两条，少一条都会误伤：

    a) 补回来的值必须 ≤ 视频时长。实测一个 30 分钟的视频里有子节点早于父节点，
       补一小时后变成 1:01:41，比整个视频还长——那是模型写错了顺序，不是漏小时位。
       不知道时长时一律不改（只靠排序规则兜底）。
    b) 补回来的值必须**紧贴父节点**（默认 10 分钟内）。漏小时位的节点补回后
       本来就该落在父节点附近；而 03:39 vs 父节点 03:48 这种只差 9 秒的小颠倒，
       加一小时会跑到 1:03:39，同样能落进"父节点+1 小时"的宽窗口里，必须挡掉。
    """
    title, ts, kids = node
    cur = ts_sec(ts)
    if max_sec and cur is not None and parent_sec is not None and cur < parent_sec:
        for k in range(1, 6):
            cand = cur + 3600 * k
            if parent_sec <= cand <= min(parent_sec + NEAR_PARENT_SEC, max_sec):
                if report is not None:
                    report.append(f"[{ts}] -> [{fmt_ts(cand)}]  {title[:34]}")
                ts, cur = fmt_ts(cand), cand
                break
    base = cur if cur is not None else parent_sec
    return (title, ts, [repair_timestamps(k, base, report, max_sec) for k in kids])

def sortkey(node):
    """节点自己有时间戳就以自己为准。

    原来取的是整棵子树的最小值，于是任何一个写错的子节点都能把整章拖到别处
    ——实测有一章因为子节点漏写小时位(05:56 应为 01:05:56)，
    从 01:05 被拖到了 04:29 和 06:55 之间。
    """
    _, ts, kids = node
    own = ts_sec(ts)
    if own is not None:
        return own
    keys = [k for k in (sortkey(c) for c in kids) if k is not None]
    return min(keys) if keys else 10**9

def sort_tree(node):
    title, ts, kids = node
    return (title, ts, sorted((sort_tree(k) for k in kids), key=sortkey))

# ---------- ④+⑤ 编号并输出 OPML ----------
def disp(title, ts, num):
    head = f"{num} " if num else ""
    return f"{head}[{ts}] {title}" if ts else f"{head}{title}"

def to_opml(T):
    def node(o, depth, num=""):
        title, ts, kids = o
        ind = "  " * depth
        t = escape(disp(title, ts, num), {'"': "&quot;"})
        if kids:
            s = f'{ind}<outline text="{t}">\n'
            for i, k in enumerate(kids, 1):
                s += node(k, depth + 1, f"{num}.{i}" if num else str(i))
            return s + f'{ind}</outline>\n'
        return f'{ind}<outline text="{t}"/>\n'
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<opml version="2.0">\n'
            f'  <head><title>{escape(T[0])}</title></head>\n  <body>\n'
            + node(T, 2) + '  </body>\n</opml>\n')

# ---------- 校验 / 统计 ----------
def check_monotonic(T):
    bad = []
    def walk(o):
        _, ts, kids = o
        for k in kids:
            ck = sortkey(k)
            if ts and ck < ts_sec(ts):
                bad.append(f"{o[0][:16]} [{ts}] > {k[0][:20]} ({ck//60:02d}:{ck%60:02d})")
            walk(k)
    walk(T)
    return bad

def count(o):
    return 1 + sum(count(k) for k in o[2])

def derive_title(infile):
    """默认用视频标题当输出名: 优先同目录 .mp4 文件名, 否则文件夹名去掉 'BV..._' 前缀。"""
    d = os.path.dirname(os.path.abspath(infile))
    mp4 = [f for f in os.listdir(d) if f.lower().endswith(".mp4")]
    if mp4:
        return os.path.splitext(mp4[0])[0]
    base = os.path.basename(d)
    m = re.match(r"^BV[0-9A-Za-z]+_(.+)$", base)
    return m.group(1) if m else base


# ---------- main ----------
def main():
    # 「脚本自身目录」要显式传进去：单独拉起 gen_mindmap 时支持把
    # .env.local 放在它旁边，统一实现时不能把这个位置弄丢。
    skill_config.load_dotenv(os.path.dirname(os.path.abspath(__file__)))
    argv = sys.argv[1:]
    positional, model, backend, use_outline, duration = [], None, "auto", False, None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--print-prompt":
            print(load_prompt(), end="")
            return
        elif a == "--outline":
            use_outline = True
        elif a == "--model":
            i += 1; model = argv[i] if i < len(argv) else None
        elif a.startswith("--model="):
            model = a.split("=", 1)[1]
        elif a == "--duration":
            i += 1; duration = int(argv[i]) if i < len(argv) else None
        elif a.startswith("--duration="):
            duration = int(a.split("=", 1)[1])
        elif a == "--backend":
            i += 1; backend = argv[i] if i < len(argv) else backend
        elif a.startswith("--backend="):
            backend = a.split("=", 1)[1]
        elif a.startswith("--"):
            pass  # 忽略未知 flag
        else:
            positional.append(a)
        i += 1

    if not positional:
        sys.exit(__doc__)
    infile = positional[0]
    prefix = positional[1] if len(positional) > 1 else derive_title(infile)

    if not os.path.exists(infile):
        sys.exit(f"找不到输入文件: {infile}")
    raw = open(infile, encoding="utf-8").read()

    # ① 字幕 -> 大纲 (--outline 则直接把输入当大纲)
    src = f"{prefix}.source.txt"
    if use_outline:
        outline = raw
        # 输入本身就是那份 source.txt 时这是 no-op(别自我覆盖)；不是的话回写一份，
        # 让「API 出的」和「agent 写的」两条路产物形状一致。
        if os.path.abspath(infile) != os.path.abspath(src):
            open(src, "w", encoding="utf-8").write(outline)
    else:
        outline = subtitle_to_outline(raw, backend, model, prefix)
        open(src, "w", encoding="utf-8").write(outline)
        print(f"  已保存大纲: {src}(可手动微调后加 --outline 重跑)", file=sys.stderr)

    # ②③④⑤
    fixes = []
    T = sort_tree(repair_timestamps(parse(outline), report=fixes, max_sec=duration))
    for f in fixes:
        print(f"  修正漏写小时位的时间戳: {f}", file=sys.stderr)
    opml_path = f"{prefix}.opml"
    open(opml_path, "w", encoding="utf-8").write(to_opml(T))

    bad = check_monotonic(T)
    print(f"✓ 节点 {count(T)} | 章节 {len(T[2])}", file=sys.stderr)
    print(f"✓ 输出: {opml_path}", file=sys.stderr)
    print("✓ 时间戳单调" if not bad else "⚠ 非单调:\n  " + "\n  ".join(bad), file=sys.stderr)

if __name__ == "__main__":
    main()

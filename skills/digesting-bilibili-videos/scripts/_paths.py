"""定位共享代码。import 它就够了，它只改 sys.path，不做别的。

两种安装形态都要能跑：
  · 作为 plugin 装：共享 lib 在 <plugin>/lib/
  · 有人只把这一个 skill 目录拷进 ~/.claude/skills/：lib 在 <skill>/lib/
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL = SCRIPTS.parent
PLUGIN_ROOT = SKILL.parent.parent

# <skill> 本身要在 path 上：vendored 模块之间用 `from lib import x` 互相引用。
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

for _cand in (PLUGIN_ROOT / "lib", SKILL / "lib"):
    if (_cand / "bili_api.py").is_file():
        if str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
        BILI_LIB = _cand
        break
else:
    sys.exit(
        "找不到 bili_api.py。期望它在 <plugin>/lib/ 或 <skill>/lib/ 下。\n"
        "如果你是手动拷贝的这个 skill，把仓库根的 lib/ 一起拷到 skill 目录里。")

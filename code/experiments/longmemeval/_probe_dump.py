# -*- coding: utf-8 -*-
import inspect
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")
# 一次性探针: 把 D1a/D1c 需要的源码+数据结构 dump 成 _probe_out.txt (单行分隔)

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "_probe_out.txt"
lines_out = []


def sec(tag):
    lines_out.append(f"@@@ {tag}")


sec("LLM_SRC")
src = (ROOT / "llm.py").read_text(encoding="utf-8").splitlines()
for i, line in enumerate(src, 1):
    lines_out.append(f"L{i:03d}|{line}")

sec("ANSWER_WITH_MEMORY_SIG")
import llm

lines_out.append(str(inspect.signature(llm.answer_with_memory)))
src2 = inspect.getsource(llm.answer_with_memory)
for line in src2.splitlines()[:40]:
    lines_out.append("AWM| " + line)

sec("POLICIES_SRC")
src3 = (ROOT / "policies.py").read_text(encoding="utf-8").splitlines()
for i, line in enumerate(src3, 1):
    lines_out.append(f"L{i:03d}|{line}")

sec("COMMON_SRC")
src4 = (ROOT / "common.py").read_text(encoding="utf-8").splitlines()
for i, line in enumerate(src4, 1):
    lines_out.append(f"L{i:03d}|{line}")

sec("RUN_MAIN")
src5 = (ROOT / "run.py").read_text(encoding="utf-8").splitlines()
for i, line in enumerate(src5[93:], 94):
    lines_out.append(f"L{i:03d}|{line}")

sec("DATA_SAMPLE")

sys.path.append(str(ROOT))
from common import load_questions

qs = load_questions()
q0 = qs[0]
lines_out.append("Q0_KEYS " + ",".join(
    vars(q0).keys() if hasattr(q0, "__dict__") else dir(q0)))
s0 = q0.haystack_sessions[0]
lines_out.append("SESS0_KEYS " + ",".join(s0.keys()))
lines_out.append("TURN0 " + json.dumps(s0["turns"][0], ensure_ascii=False)[:200])
lines_out.append("TURN1 " + json.dumps(s0["turns"][1], ensure_ascii=False)[:200])
q0_map = {k: getattr(q0, k) for k in vars(q0) if not k.startswith("_")}
lines_out.append("Q0_Q " + json.dumps(q0_map, ensure_ascii=False)[:300])

OUT.write_text("\n".join(lines_out), encoding="utf-8")
logger.info("WROTE", OUT, len(lines_out))

"""生成部署版 research_pipeline.py（写入团队 workspace/swarmflow/）。

相对仓库版的差异：
- 去掉 options["model"]（统一用桌面版默认模型）；
- python 用绝对路径（agent shell 的 PATH 无 python）；
- 实验输出直写 ../output/results.json（= workspace/output/results.json，
  即幻觉校验 Rail 的默认基准路径）。
运行：python paper-lab/deploy/make_deployed_pipeline.py
"""
import os
import sys
from pathlib import Path

# paper-lab 根目录：相对本脚本定位（parents[1] = code/），可用 PAPER_LAB 覆盖。

ROOT = Path(os.environ.get("PAPER_LAB") or Path(__file__).resolve().parents[1])
SRC = ROOT / "swarmflow" / "research_pipeline.py"
DST = Path.home() / ".jiuwenswarm" / "agent" / "workspace" / "swarmflow" / "research_pipeline.py"

# 子进程解释器：默认为当前解释器，可用 PAPER_LAB_PY 指定。
PY = os.environ.get("PAPER_LAB_PY") or sys.executable

REPLACEMENTS = [
    ('RESULTS_REL = "output/results.json"  # 相对 paper-lab 根',
     'RESULTS_REL = "../output/results.json"  # 部署位：workspace/output/results.json（Rail 基准）'),
    ('options={"model": MODEL_STRONG},', 'options={},'),
    ('options={"model": MODEL_FAST},', 'options={},'),
    ('options={"model": MODEL_FAST, "timeout": 600},', 'options={"timeout": 600},'),
    ('"1. 在 paper-lab 根目录运行: "',
     '"1. 在 workspace/paper-lab 根目录运行: "'),
    ('"python scripts/sandbox_runner.py --script experiments/run_all.py "',
     f'"{PY} scripts/sandbox_runner.py --script experiments/run_all.py "'),
    ('"--timeout 300\\n"',
     '"--timeout 300 --arg=--out --arg=../output/results.json\\n"'),
    ('"你是实验审计员。在 paper-lab 根目录运行: "',
     '"你是实验审计员。在 workspace/paper-lab 根目录运行: "'),
    ('"python -m pytest tests/ -q\\n"',
     f'"{PY} -m pytest tests/ -q\\n"'),
    ('（即 paper-lab/" + RESULTS_REL + " 的真实落盘数据）',
     '（即 workspace/" + RESULTS_REL + " 的真实落盘数据）'),
    ('"是否都能在 paper-lab/" + RESULTS_REL + "（真实实验落盘文件）中"',
     '"是否都能在 workspace/" + RESULTS_REL + "（真实实验落盘文件）中"'),
]

text = SRC.read_text(encoding="utf-8")
for old, new in REPLACEMENTS:
    assert text.count(old) >= 1, f"anchor not found: {old[:50]}"
    text = text.replace(old, new)

DST.parent.mkdir(parents=True, exist_ok=True)
DST.write_text(text, encoding="utf-8")
compile(text, str(DST), "exec")  # 语法自检
print(f"OK -> {DST}  ({len(text.splitlines())} lines, compile pass)")

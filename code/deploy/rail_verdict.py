"""P2 闭环 Rail 显式裁决：双 Rail × 成稿论文 + 伪造数字阴性对照。

用法：python deploy/rail_verdict.py [论文路径]

第一个位置参数为待检论文；省略时用 code/paper_system/paper_memory_engine.md。
输出：两个 Rail 对该稿的 PASS/WARN 判决，以及三组阴性对照（伪造数字、缺章节、
悬空引用）应被告警。
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
PAPER = Path(sys.argv[1]) if len(sys.argv) > 1 else LAB_ROOT / "paper_system" / "paper_memory_engine.md"
HALLU_FILE = LAB_ROOT / "extensions" / "hallucination_check" / "rail.py"
ACAD_FILE = LAB_ROOT / "extensions" / "academic_format" / "rail.py"
RESULTS = LAB_ROOT / "output" / "results.json"


def _stub_openjiuwen():
    if "openjiuwen" in sys.modules:
        return
    rail_base = types.ModuleType("openjiuwen.core.single_agent.rail.base")

    class AgentCallbackContext:
        pass

    rail_base.AgentCallbackContext = AgentCallbackContext
    hr_base = types.ModuleType("openjiuwen.harness.rails.base")

    class DeepAgentRail:
        priority: int = 50

    hr_base.DeepAgentRail = DeepAgentRail
    for name in ("openjiuwen", "openjiuwen.core", "openjiuwen.core.single_agent",
                 "openjiuwen.core.single_agent.rail", "openjiuwen.harness",
                 "openjiuwen.harness.rails"):
        sys.modules[name] = types.ModuleType(name)
    sys.modules["openjiuwen.core.single_agent.rail.base"] = rail_base
    sys.modules["openjiuwen.harness.rails.base"] = hr_base


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ctx(output: str = ""):
    return types.SimpleNamespace(output=output, notes=[], inputs=types.SimpleNamespace(
        tool_name="", tool_args={}))


def _verdict(ctx, rail_name: str) -> str:
    if not ctx.notes:
        return f"[{rail_name}] PASS（无告警）"
    blocked = any(("拦截" in n or "阻断" in n or "missing" in n.lower()) for n in ctx.notes)
    tag = "BLOCK" if blocked else "WARN"
    lines = "\n".join(f"    - {n}" for n in ctx.notes[:6])
    return f"[{rail_name}] {tag}\n{lines}"


async def main() -> None:

    if not PAPER.is_file():

        print(f"论文不存在：{PAPER}")

        print("用法：python deploy/rail_verdict.py <论文路径>")

        return

    _stub_openjiuwen()

    paper = PAPER.read_text(encoding="utf-8")

    hallu = _load(HALLU_FILE, "ext_hallucination")
    hallu.RESULTS_PATH = str(RESULTS)
    acad = _load(ACAD_FILE, "ext_academic")

    print("=" * 60)
    print("Rail 1: hallucination_check × 成稿论文全文")
    print("=" * 60)
    ctx = _ctx(paper)
    await hallu.HallucinationCheckRail().after_model_call(ctx)
    print(_verdict(ctx, "hallucination_check"))

    print()
    print("=" * 60)
    print("Rail 2: academic_format × 成稿论文全文")
    print("=" * 60)
    ctx2 = _ctx(paper)
    await acad.AcademicFormatRail().after_model_call(ctx2)
    print(_verdict(ctx2, "academic_format"))

    print()
    print("=" * 60)
    print("阴性对照：伪造数字 0.9999 / 87.3% 应被 hallucination_check 告警")
    print("=" * 60)
    fake = "本方法在预算64下准确率达到 0.9999，遥遥领先，F1=0.9876，提升 87.3%。"
    ctx3 = _ctx(fake)
    await hallu.HallucinationCheckRail().after_model_call(ctx3)
    print(_verdict(ctx3, "hallucination_check"))

    print()
    print("=" * 60)
    print("阴性对照：像论文但缺方法/实验/结论/参考文献章节，应被 academic_format 告警")
    print("=" * 60)
    bad = "# 我的笔记\n\n## 摘要\n\n一些摘要内容。\n\n## 1 引言\n\n引言内容。\n"
    ctx4 = _ctx(bad)
    await acad.AcademicFormatRail().after_model_call(ctx4)
    print(_verdict(ctx4, "academic_format"))

    print()
    print("=" * 60)
    print("阴性对照：正文引用 [9] 无对应参考文献条目，应被 academic_format 告警")
    print("=" * 60)
    dangling = ("# 标题\n\n## 摘要\n\n摘要。\n\n## 1 引言\n\n引言参见文献 [9]。\n\n"
                "## 2 方法\n\n方法。\n\n## 3 实验\n\n实验。\n\n## 4 结论\n\n结论。\n\n"
                "## 参考文献\n\n[1] Author A. Paper. 2020.\n")
    ctx5 = _ctx(dangling)
    await acad.AcademicFormatRail().after_model_call(ctx5)
    print(_verdict(ctx5, "academic_format"))


if __name__ == "__main__":
    asyncio.run(main())

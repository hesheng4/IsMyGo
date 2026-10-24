"""幻觉校验 Rail × 真实 results.json 集成测试（真数据 vs 编造数据）。

验证闭环：论文断言里的量化数字，凡来自 output/results.json 的
真实实验结果都放行；编造的数字全部拦截。
运行：python -m pytest tests/test_rail_real_data.py -v
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

LAB_ROOT = Path(__file__).resolve().parent.parent
RAIL_FILE = LAB_ROOT / "extensions" / "hallucination_check" / "rail.py"
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
                 "openjiuwen.core.single_agent.rail",
                 "openjiuwen.harness", "openjiuwen.harness.rails"):
        sys.modules[name] = types.ModuleType(name)
    sys.modules["openjiuwen.core.single_agent.rail.base"] = rail_base
    sys.modules["openjiuwen.harness.rails.base"] = hr_base


@pytest.fixture(scope="module")
def rail_mod():
    _stub_openjiuwen()
    spec = importlib.util.spec_from_file_location("ext_hallucination", RAIL_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # 指向真实实验落盘数据（唯一事实基准）
    mod.RESULTS_PATH = str(RESULTS)
    return mod


def _ctx(output="", tool_name="", content=""):
    return types.SimpleNamespace(
        output=output, notes=[],
        inputs=types.SimpleNamespace(
            tool_name=tool_name, tool_args={"content": content} if content else {},
        ),
    )


@pytest.fixture(scope="module")
def real_rows():
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    bench = data["experiments"]["memory_bench"]
    return {r["policy"]: r for r in bench["main"]} | {
        (r["policy"], r["budget"]): r for r in bench["ablation"]
    }


# ---------------- 真数据：放行 ----------------

def test_real_accuracy_claims_pass(rail_mod, real_rows):
    row = real_rows[("sliding_window", 64)]
    claim = f"滑动窗口记忆在预算64时总体准确率为 {row['accuracy']:.2%}。"
    ctx = _ctx(output=claim)
    asyncio.run(rail_mod.HallucinationCheckRail().after_model_call(ctx))
    assert not any("未在真实实验结果中找到" in n for n in ctx.notes), ctx.notes


def test_real_band_and_footprint_claims_pass(rail_mod, real_rows):
    row = real_rows[("retrieval_recency", 64)]
    claim = (f"recency 检索 recent 带准确率 {row['accuracy_recent']:.2%}，"
             f"Accuracy 上限来自全量上下文（{real_rows['full_context']['accuracy']:.2%}）。")
    ctx = _ctx(output=claim)
    asyncio.run(rail_mod.HallucinationCheckRail().after_model_call(ctx))
    assert not any("未在真实实验结果中找到" in n for n in ctx.notes), ctx.notes


def test_real_decimal_form_passes(rail_mod, real_rows):
    row = real_rows[("retrieval", 16)]
    ctx = _ctx(output=f"Accuracy: {row['accuracy']}")
    asyncio.run(rail_mod.HallucinationCheckRail().after_model_call(ctx))
    assert not any("未在真实实验结果中找到" in n for n in ctx.notes), ctx.notes


def test_ci_column_header_exempt(rail_mod, real_rows):
    """统计口径词豁免："95% CI" 是列头/方法描述，不应被当作量化断言拦截。"""
    row = real_rows[("sliding_window", 64)]
    claim = (f"结果：Accuracy={row['accuracy']}（95% CI ±{row['accuracy_ci95']}），"
             "方法采用 95% 置信区间报告。")
    ctx = _ctx(output=claim)
    asyncio.run(rail_mod.HallucinationCheckRail().after_model_call(ctx))
    assert not any("95%" in n for n in ctx.notes), ctx.notes


# ---------------- 编造数据：拦截 ----------------

def test_fabricated_percentage_blocked(rail_mod):
    ctx = _ctx(output="我们的方法准确率 99.9%，全面超越基线。")
    asyncio.run(rail_mod.HallucinationCheckRail().after_model_call(ctx))
    assert any("99.9%" in n for n in ctx.notes), ctx.notes


def test_fabricated_metric_blocked(rail_mod):
    ctx = _ctx(output="实验表明 F1=0.987，显著性 p<0.001。")
    asyncio.run(rail_mod.HallucinationCheckRail().after_model_call(ctx))
    assert any("0.987" in n for n in ctx.notes), ctx.notes


def test_ordinary_verb_not_metric_claim(rail_mod):
    """英文动词误判回归：指标名模式必须带词边界。

    "accept 128" 曾被切成 Acc + [a-z_]* 而判为未溯源断言（正则缺 \\b）。
    """
    ctx = _ctx(output="Both readers accept 128k-token contexts, so the budget is shared.")
    asyncio.run(rail_mod.HallucinationCheckRail().after_model_call(ctx))
    assert not any("未在真实实验结果中找到" in n for n in ctx.notes), ctx.notes


def test_fabricated_write_blocked(rail_mod):
    ctx = _ctx(tool_name="write_file", content="结论：准确率提升至 88.8%。")
    asyncio.run(rail_mod.HallucinationCheckRail().before_tool_call(ctx))
    assert any("88.8%" in n for n in ctx.notes), ctx.notes


def test_real_write_passes(rail_mod, real_rows):
    row = real_rows[("retrieval_recency", 64)]
    ctx = _ctx(tool_name="write_file",
               content=f"实验：Accuracy={row['accuracy']}（真实结果）。")
    asyncio.run(rail_mod.HallucinationCheckRail().before_tool_call(ctx))
    assert ctx.notes == [], ctx.notes

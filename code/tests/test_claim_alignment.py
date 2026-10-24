"""主张对齐 Rail（ClaimAlignmentRail）测试：评审弱点 W1-W6 的正/负对照。

背景：Stanford Agentic Reviewer 3.2/10 评审暴露的六类"主张-证据-报告规范"
缺陷，逐项验证 Rail 能拦截（负例）且不误伤合规论文（正例）。
运行：python -m pytest tests/test_claim_alignment.py -v
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

LAB_ROOT = Path(__file__).resolve().parent.parent
RAIL_FILE = LAB_ROOT / "extensions" / "claim_alignment" / "rail.py"


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
    spec = importlib.util.spec_from_file_location("ext_claim_alignment", RAIL_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # 审计日志写测试区，避免污染线上 rail_runtime.log
    mod.RAIL_AUDIT_PATH = str(LAB_ROOT / "output" / "rail_test_claim.log")
    return mod


def _ctx(output="", tool_name="", content=""):
    return types.SimpleNamespace(
        output=output, notes=[],
        inputs=types.SimpleNamespace(
            tool_name=tool_name, tool_args={"content": content} if content else {},
        ),
    )


def _run(rail_mod, ctx, hook="after_model_call"):
    asyncio.run(getattr(rail_mod.ClaimAlignmentRail(), hook)(ctx))


# 合规论文：oracle 已标注 + std/CI + 延迟口径 + 复现要素 + ≥5 条参考文献
GOOD_PAPER = """# 层级记忆引擎：受限预算下的记忆策略权衡
## 摘要
受限策略间比较：retrieval_recency 的 accuracy 为 0.1181，高于同预算的
sliding_window（0.0777），均值来自 3 种子聚合（std 0.0157，CI95 0.0391）。
full context 作为 oracle 上界参照，accuracy 1.0，不参与受限比较。
## 引言
长程流式任务要求受限记忆管理。
## 实验设置
延迟为进程内内存查询耗时（in-process micro-benchmark），不含模型推理。
运行环境 Python 3.10 / Windows 平台；随机 seed 取 42/43/44；
budget 档位 16/32/64；BM25 检索 top-1。
## 结论
压缩层是受限预算下的关键组件。
## 参考文献
[1] MemGPT (2023)——OS 式分页记忆
[2] MemoryBank (2024)——长期记忆库
[3] Generative Agents (2023)——摘要式记忆
[4] RAG (2020)——检索增强
[5] DPR (2020)——稠密检索
"""

# 各弱点的最小负例论文骨架（论文形态，触发结构类检查）
def _paper(body: str) -> str:
    return ("# 测试论文\n## 摘要\n" + body +
            "\n## 引言\n引言。\n## 方法\n方法。\n## 实验设置\n设置。\n"
            "## 结论\n结论。\n## 参考文献\n[1] A\n[2] B\n[3] C\n[4] D\n[5] E\n")


# ---------------- 正例：合规论文放行 ----------------

def test_good_paper_passes(rail_mod):
    ctx = _ctx(output=GOOD_PAPER)
    _run(rail_mod, ctx)
    assert ctx.notes == [], ctx.notes


def test_oracle_labeled_sentence_passes(rail_mod):
    text = _paper("full context 作为 oracle 上界参照，accuracy 1.0，"
                  "std 0.0，CI95 0.0。延迟为进程内耗时。seed 42，budget 64，"
                  "Python 3.10。")
    ctx = _ctx(output=text)
    _run(rail_mod, ctx)
    assert ctx.notes == [], ctx.notes


def test_non_paper_output_skips_structural_checks(rail_mod):
    """构思阶段 JSON（无标题行）不触发结构类检查。"""
    ctx = _ctx(output='{"hypothesis": "受限策略间比较", "modules": ["检索"]}')
    _run(rail_mod, ctx)
    assert ctx.notes == [], ctx.notes


# ---------------- W2：oracle 不公平对照 ----------------

def test_unfair_oracle_claim_blocked(rail_mod):
    """评审原话：标题宣称 outperform full-context → 必须拦截。"""
    ctx = _ctx(output=_paper("我们的层级记忆引擎全面优于 full context 基线。"))
    _run(rail_mod, ctx)
    assert any("不公平对照" in n for n in ctx.notes), ctx.notes


def test_unfair_oracle_claim_english_blocked(rail_mod):
    ctx = _ctx(output=_paper("Our engine outperforms full-context across all budgets."))
    _run(rail_mod, ctx)
    assert any("不公平对照" in n for n in ctx.notes), ctx.notes


def test_unfair_oracle_write_blocked(rail_mod):
    ctx = _ctx(tool_name="write_file",
               content="# 论文\n## 摘要\n层级引擎超越 full context。\n")
    _run(rail_mod, ctx, "before_tool_call")
    assert any("不公平对照" in n for n in ctx.notes), ctx.notes


# ---------------- W3：统计置信缺失 ----------------

def test_missing_ci_blocked(rail_mod):
    ctx = _ctx(output=_paper("retrieval 的准确率为 0.1181，效果最好。"))
    _run(rail_mod, ctx)
    assert any("统计置信缺失" in n for n in ctx.notes), ctx.notes


def test_with_std_passes(rail_mod):
    text = _paper("准确率 0.1181（std 0.0157，CI95 0.0391）。"
                  "延迟为进程内耗时。seed 42，budget 64，Python 3.10。")
    ctx = _ctx(output=text)
    _run(rail_mod, ctx)
    assert ctx.notes == [], ctx.notes


# ---------------- W4：指标口径缺失 ----------------

def test_missing_latency_scope_blocked(rail_mod):
    text = _paper("准确率 0.1181（CI95 0.0391）。检索带来延迟 0.0334ms。"
                  "seed 42，budget 64，Python 3.10。")
    ctx = _ctx(output=text)
    _run(rail_mod, ctx)
    assert any("指标口径缺失" in n for n in ctx.notes), ctx.notes


def test_latency_scope_declared_passes(rail_mod):
    text = _paper("准确率 0.1181（CI95 0.0391）。"
                  "延迟 0.0334ms 为进程内内存查询耗时，不含模型推理。"
                  "seed 42，budget 64，Python 3.10。")
    ctx = _ctx(output=text)
    _run(rail_mod, ctx)
    assert ctx.notes == [], ctx.notes


# ---------------- W5：复现要素缺失 ----------------

def test_missing_repro_elements_blocked(rail_mod):
    text = _paper("准确率 0.1181（CI95 0.0391）。延迟为进程内耗时。")  # 无种子/预算/环境
    ctx = _ctx(output=text)
    _run(rail_mod, ctx)
    assert any("复现要素缺失" in n for n in ctx.notes), ctx.notes


# ---------------- W6：相关工作过少 ----------------

def test_too_few_refs_blocked(rail_mod):
    text = _paper("准确率 0.1181（CI95 0.0391）。延迟为进程内耗时。"
                  "seed 42，budget 64，Python 3.10。")
    text = text.replace("[3] C\n[4] D\n[5] E", "")  # 只剩 2 条
    ctx = _ctx(output=text)
    _run(rail_mod, ctx)
    assert any("相关工作过少" in n for n in ctx.notes), ctx.notes


def test_five_refs_passes(rail_mod):
    ctx = _ctx(output=GOOD_PAPER)
    _run(rail_mod, ctx)
    assert not any("相关工作过少" in n for n in ctx.notes), ctx.notes


# ---------------- 主张-证据不对齐的示例断言（应被 Rail 拦截） ----------------

def test_v1_title_claim_would_be_blocked(rail_mod):
    """标题级断言声称优于 full-context 基线时，应被不公平对照检查拦截。"""
    ctx = _ctx(output=_paper(
        "Hierarchical Memory Engines Outperform Full-Context Baselines "
        "in Long-Horizon Streaming Tasks."))
    _run(rail_mod, ctx)
    assert any("不公平对照" in n for n in ctx.notes), ctx.notes

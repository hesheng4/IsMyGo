"""学术规范 Rail 结构校验测试（编号标题、缺章节门控、引用对齐）。

运行：python -m pytest tests/test_academic_format.py -v
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

LAB_ROOT = Path(__file__).resolve().parent.parent
RAIL_FILE = LAB_ROOT / "extensions" / "academic_format" / "rail.py"


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
    spec = importlib.util.spec_from_file_location("ext_academic", RAIL_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ctx(output=""):
    return types.SimpleNamespace(
        output=output, notes=[],
        inputs=types.SimpleNamespace(tool_name="", tool_args={}),
    )


FULL_PAPER = """# 标题

## 摘要

摘要内容。

## 1 引言

引言内容。

## 2 相关方法

方法内容。

## 3 实验设置

实验内容。

## 4 结论

结论内容。

## 参考文献

[1] Author A. Some paper. 2020.
"""

NUMBERED_SUBSECTION_PAPER = """# 标题

## 摘要

摘要内容。

## 1 引言

### 1.1 背景

背景。

## 2 研究方法

### 2.3 本文方法：分层设计

方法内容。

## 3 实验结果与分析

实验内容。

## 5 结论

结论内容。

## 参考文献

[1] Author A. Some paper. 2020.
"""


def test_numbered_heading_paper_passes(rail_mod):
    ctx = _ctx(output=FULL_PAPER)
    asyncio.run(rail_mod.AcademicFormatRail().after_model_call(ctx))
    assert ctx.notes == [], ctx.notes


def test_chinese_variant_headings_pass(rail_mod):
    ctx = _ctx(output=NUMBERED_SUBSECTION_PAPER)
    asyncio.run(rail_mod.AcademicFormatRail().after_model_call(ctx))
    assert ctx.notes == [], ctx.notes


def test_missing_sections_warned(rail_mod):
    doc = """# 标题

## 摘要

摘要内容。

## 1 引言

引言内容。
"""
    ctx = _ctx(output=doc)
    asyncio.run(rail_mod.AcademicFormatRail().after_model_call(ctx))
    assert any("缺少必需章节" in n for n in ctx.notes), ctx.notes
    assert any("method" in n for n in ctx.notes), ctx.notes


def test_plain_text_skipped(rail_mod):
    ctx = _ctx(output="这是一段没有章节结构的普通文本。")
    asyncio.run(rail_mod.AcademicFormatRail().after_model_call(ctx))
    assert ctx.notes == [], ctx.notes


def test_dangling_citation_warned(rail_mod):
    doc = FULL_PAPER.replace("引言内容。", "引言内容，参见文献 [9]。")
    ctx = _ctx(output=doc)
    asyncio.run(rail_mod.AcademicFormatRail().after_model_call(ctx))
    assert any("[9]" in n and "未在参考文献列表中定义" in n for n in ctx.notes), ctx.notes


def test_aligned_citation_passes(rail_mod):
    doc = FULL_PAPER.replace("引言内容。", "引言内容，参见文献 [1]。")
    ctx = _ctx(output=doc)
    asyncio.run(rail_mod.AcademicFormatRail().after_model_call(ctx))
    assert ctx.notes == [], ctx.notes

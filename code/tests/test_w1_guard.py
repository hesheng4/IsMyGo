"""W1 模块覆盖硬约束单元测试：_parse_review 与 _w1_guard_text。

背景：Stanford Agentic Reviewer 3.2/10 最致命短板 W1 = 假设中的方法模块
未全部实验。v6 将 "仅靠 prompt 指令" 升级为运行时硬约束：
  hypothesis-review 的 JSON 输出 → _parse_review 抽取 module_gaps →
  _w1_guard_text 生成硬约束文本 → 注入 _planning / _writing。
本测试覆盖解析器的正/负/边界例，以及约束文本生成，确保闭环不依赖模型自觉。

运行：python -m pytest tests/test_w1_guard.py -v
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

LAB_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_FILE = LAB_ROOT / "deploy" / "research_pipeline_v5.py"


def _stub_swarmflow():
    """stub swarmflow facade，使流水线模块可无副作用导入。

    顶层 `from swarmflow import (agent, phase, log, compact, budget)` 仅需
    名字存在即可；纯函数测试不触发这些算子，用空壳对象占位。
    """
    if "swarmflow" in sys.modules:
        return
    sf = types.ModuleType("swarmflow")
    _noop = lambda *a, **k: None  # noqa: E731
    sf.agent = _noop
    sf.phase = _noop
    sf.log = _noop
    sf.compact = _noop
    sf.budget = _noop
    sys.modules["swarmflow"] = sf


@pytest.fixture(scope="module")
def pipeline_mod():
    _stub_swarmflow()
    spec = importlib.util.spec_from_file_location("research_pipeline_v5", PIPELINE_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- _parse_review 正向例 ----------

def test_parse_review_clean_json(pipeline_mod):
    """标准 JSON：passed/module_gaps/baseline_fairness 全字段正确解析。"""
    text = (
        '{"passed": false, "module_gaps": ["hierarchical", "retrieval"], '
        '"baseline_fairness": "full context 仅作 oracle 参照"}'
    )
    info = pipeline_mod._parse_review(text)
    assert info["passed"] is False
    assert info["module_gaps"] == ["hierarchical", "retrieval"]
    assert info["baseline_fairness"] == "full context 仅作 oracle 参照"


def test_parse_review_fenced_json(pipeline_mod):
    """模型用 ```json 包裹或前后夹带文本时仍能抽取首个对象。"""
    text = (
        "以下是评审结论：\n```json\n"
        '{"passed": true, "module_gaps": ["compression"]}\n```\n'
        "请据此修订方案。"
    )
    info = pipeline_mod._parse_review(text)
    assert info["module_gaps"] == ["compression"]


# ---------- _parse_review 负向/边界例（安全默认，不中断流水线） ----------

def test_parse_review_plain_text_returns_safe_default(pipeline_mod):
    """纯自然语言、无 JSON：返回放行默认（passed=True, gaps=[]）。"""
    info = pipeline_mod._parse_review("评审认为假设基本可行，建议补充实验。")
    assert info["passed"] is True
    assert info["module_gaps"] == []
    assert info["baseline_fairness"] == ""


def test_parse_review_json_is_list_not_dict(pipeline_mod):
    """顶层是 JSON 数组而非对象：视为无效，返回安全默认。"""
    info = pipeline_mod._parse_review('[{"module_gaps": ["x"]}]')
    assert info["module_gaps"] == []


def test_parse_review_none_and_empty(pipeline_mod):
    """空值/None/非字符串：不抛异常，返回安全默认。"""
    assert pipeline_mod._parse_review(None)["module_gaps"] == []
    assert pipeline_mod._parse_review("")["module_gaps"] == []
    assert pipeline_mod._parse_review(123)["module_gaps"] == []


def test_parse_review_module_gaps_as_scalar(pipeline_mod):
    """module_gaps 为单个字符串（非列表）：归一化为单元素列表。"""
    info = pipeline_mod._parse_review('{"module_gaps": "hierarchical"}')
    assert info["module_gaps"] == ["hierarchical"]


def test_parse_review_missing_module_gaps_field(pipeline_mod):
    """JSON 存在但缺 module_gaps 字段：默认空缺口。"""
    info = pipeline_mod._parse_review('{"passed": true}')
    assert info["module_gaps"] == []


# ---------- _w1_guard_text ----------

def test_w1_guard_empty_when_no_gaps(pipeline_mod):
    """无缺口（已实验覆盖全部模块）：返回空串，不注入约束。"""
    assert pipeline_mod._w1_guard_text([]) == ""
    assert pipeline_mod._w1_guard_text(None) == ""


def test_w1_guard_contains_gap_names(pipeline_mod):
    """有缺口：约束文本须含 W1 标识与各缺口模块名。"""
    text = pipeline_mod._w1_guard_text(["hierarchical", "retrieval"])
    assert "W1 模块覆盖硬约束" in text
    assert "hierarchical" in text
    assert "retrieval" in text
    # 约束要求降级为「未来工作」，且禁止进入优越性主张
    assert "未来工作" in text


def test_w1_end_to_end_parse_then_guard(pipeline_mod):
    """端到端：解析出缺口 → 生成非空硬约束（闭环生效）。"""
    review = '{"passed": false, "module_gaps": ["hierarchical"]}'
    gaps = pipeline_mod._parse_review(review)["module_gaps"]
    guard = pipeline_mod._w1_guard_text(gaps)
    assert gaps == ["hierarchical"]
    assert "hierarchical" in guard

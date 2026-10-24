"""模块④ Writing（写作）：把证据渲染为 ICLR 短论文（确定性渲染 + 因果分析）。

对齐 FARS：Writing 在证据先于草稿（防止机会主义声明）；本模块直接调用
paper_builder（确定性、零幻觉）生成全文，并嵌入 causal_analysis 的机制级洞察，
而非表面指标对比（FARS 优化③）。

LLM 层（swarmflow agent）可作为「衔接性 prose 润色」可选叠加，但数字/表/图
强制来自 results.json，模型无法篡改——这是 Task #15「空洞论文」失败的根本修复。
"""
from __future__ import annotations

import os
from typing import Callable, List, Optional

from .contracts import Hypothesis, ExperimentPlan, ExperimentEvidence, Manuscript
from . import paper_builder as pb
from . import causal_analysis as ca


def execute(hyp: Hypothesis, plan: ExperimentPlan, ev: ExperimentEvidence,
            out_dir: str, figures: Optional[List[str]] = None,
            llm: Optional[Callable[[str], str]] = None) -> Manuscript:
    """确定性写作：从 evidence.results_json_path 抽取真实数值渲染论文。

    figures: 由 charts.generate_all 预生成的图表路径，嵌入论文。
    llm: 可选，用于衔接性 prose 润色（不影响任何数值）。"""
    figures = figures or []
    manu = pb.build_manuscript(ev.results_json_path, out_dir, figures=figures)

    # 可选 LLM 润色（仅 prose，不动数值）：用占位说明，保持零幻觉
    if llm:
        # 设计上仅允许在「非数值段」调用；本实现直接保留确定性全文
        pass
    return manu


def build_causal_section(results_path: str) -> str:
    """对外便捷：单独产出因果分析章节（供评审/调试）。"""
    import json
    with open(results_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return ca.render_insights_md(ca.analyze(data))


__all__ = ["execute", "build_causal_section"]

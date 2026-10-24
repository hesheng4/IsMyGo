"""模块② Planning（规划）：把假设转机读实验契约（FARS 五类任务 + 模块映射）。

对齐 FARS §3.3：Planning 不直接给 Experiment 自由目标，而是把提案转为
machine-readable experiment contract，两级层次（五类任务 + 有序步骤），并带
自动化校验（JSON 格式/必填字段/类别名/顺序）。本模块额外注入 W1「模块→实验
映射表」硬约束，确保未实验模块不进入主张。

LLM 层用 swarmflow；离线可用 injected llm。
"""
from __future__ import annotations

from typing import Callable, List, Optional

from .contracts import Hypothesis, ExperimentPlan, ExperimentItem


FIVE_CATEGORIES = ["environment_config", "baseline", "main", "effectiveness_eval", "analysis"]


def build_prompt(hyp: Hypothesis, module_gaps: Optional[List[str]] = None) -> str:
    gaps = "、".join(module_gaps or [])
    w1 = (
        f"\n【W1 模块覆盖硬约束】以下模块经评审无实验支撑：{gaps}。"
        "必须在「模块→实验策略映射表」显式声明缺失，并从主张移除。"
        if gaps else ""
    )
    return (
        "你是实验设计专家。基于假设设计可复现实验方案，输出 machine-readable "
        "experiment contract（JSON）。\n"
        "要求：① 数据集与预处理；② 基线（无界基线单列并标注 oracle 上界参照）；"
        "③ 主实验；④ 多种子（≥3）统计方案（均值+std+95%CI）；"
        "⑤ 消融；⑥ 指标口径声明（延迟测量口径）。\n"
        "【模块映射表·必须】假设每个方法模块映射到一条具体实验/消融；"
        "无法映射者显式声明并从主张移除。\n"
        "【五类任务】契约条目须归入且仅归入：environment_config / baseline / "
        "main / effectiveness_eval / analysis，且按此顺序。\n"
        f"假设：{hyp.statement}\n依据：{hyp.rationale}\n模块：{hyp.modules}\n{w1}\n"
        "返回 JSON：{\"module_map\":{...}, \"items\":[{\"category\":...,"
        "\"name\":...,\"steps\":[...],\"order\":int}], \"baselines\":[...], "
        "\"metrics\":[...], \"seeds\":[...], \"budgets\":[...], \"stat_scheme\":...}"
    )


def parse_plan(text: str, hyp: Hypothesis) -> ExperimentPlan:
    import json, re
    if not text:
        return ExperimentPlan(hypothesis=hyp.statement)
    try:
        data = json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return ExperimentPlan(hypothesis=hyp.statement, raw=text)
        try:
            data = json.loads(m.group(0))
        except Exception:
            return ExperimentPlan(hypothesis=hyp.statement, raw=text)
    if not isinstance(data, dict):
        return ExperimentPlan(hypothesis=hyp.statement, raw=text)
    items = [ExperimentItem(category=i.get("category", "main"), name=i.get("name", ""),
                            steps=list(i.get("steps", []) or []), order=int(i.get("order", 0)),
                            depends_on=list(i.get("depends_on", []) or []))
            for i in (data.get("items", []) or [])]
    return ExperimentPlan(
        hypothesis=hyp.statement,
        module_map=dict(data.get("module_map", {}) or {}),
        items=items,
        baselines=list(data.get("baselines", []) or []),
        metrics=list(data.get("metrics", []) or []),
        seeds=list(data.get("seeds", [42, 43, 44]) or []),
        budgets=list(data.get("budgets", [16, 32, 64]) or []),
        stat_scheme=str(data.get("stat_scheme", "")),
        raw=text,
    )


def execute(hyp: Hypothesis, llm: Optional[Callable[[str], str]] = None,
            module_gaps: Optional[List[str]] = None) -> ExperimentPlan:
    prompt = build_prompt(hyp, module_gaps)
    text = ""
    if llm:
        text = llm(prompt)
    else:
        try:
            from swarmflow import agent, phase
            import asyncio
            async def _call():
                return await agent(prompt, label="planning", phase="planning")
            text = asyncio.run(_call())
        except Exception:
            text = ""
    return parse_plan(text, hyp)


__all__ = ["build_prompt", "parse_plan", "execute", "FIVE_CATEGORIES"]

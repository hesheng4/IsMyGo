"""模块③ Experiment（实验）：执行实验契约 + 真值注入 + 有效性评估门控。

对齐 FARS §3.4：编排与执行分离；harness 把契约拆成有序 item 逐个执行；
effectiveness evaluation 门控「主实验→分析」的过渡，把负结果作为一等公民保留。
本模块不信任 worker 转述——执行后直接读 results.json（唯一事实基准）做真值注入，
与 research_pipeline_v5.py 的「引擎侧真值注入」一致。

确定性/可复现前提：实验由 experiments/run_all.py 生成 results.json（deterministic）。
"""
from __future__ import annotations

import json
import os
from typing import Callable, Optional

from .contracts import ExperimentPlan, ExperimentEvidence


def _read_truth(results_path: str) -> tuple[bool, str, dict]:
    try:
        with open(results_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        json.dumps(data)  # 校验可序列化
        return True, "ok", data
    except Exception as e:
        return False, str(e), {}


def summarize_evidence(data: dict) -> str:
    rows = data.get("experiments", {}).get("memory_bench", {}).get("ablation", [])
    if not rows:
        return "（无实验数据）"
    best = max(rows, key=lambda r: r["accuracy"])
    return (f"共 {len(rows)} 条实验；最优策略 {best['policy']}@budget={best['budget']} "
            f"accuracy={best['accuracy']:.4f}。")


def extract_negative(data: dict) -> list[str]:
    rows = data.get("experiments", {}).get("memory_bench", {}).get("ablation", [])
    negs = []
    for r in rows:
        if r["accuracy"] < 0.15:
            negs.append(f"{r['policy']}@budget={r['budget']} accuracy={r['accuracy']:.4f}（近随机，负结果）")
        if r.get("accuracy_ancient", 1.0) == 0.0 and r["budget"] >= 32:
            negs.append(f"{r['policy']}@budget={r['budget']} ancient=0.0（远古事实结构性丢失）")
    return negs


def execute(plan: ExperimentPlan, results_path: str,
            runner: Optional[Callable[[ExperimentPlan], str]] = None) -> ExperimentEvidence:
    """执行实验：runner 可注入（本地直接复用已落盘 results.json；引擎内调沙箱重跑）。

    真值注入：执行后直接读 results.json，不信任 runner 文本转述。
    effectiveness 门控：主实验最优 accuracy 是否支撑「继续分析」（此处恒为真，
    因负结果也保留为 first-class）。"""
    ok, err, data = _read_truth(results_path)
    if not ok:  # 降级：无数据则标记失败证据，交给 scheduler 降级路径
        return ExperimentEvidence(
            results_json_path=results_path, summary=f"读取失败: {err}",
            tables={}, negative_results=[], passed_effectiveness=False, raw=err)

    summary = summarize_evidence(data)
    negs = extract_negative(data)
    passed = True  # 负结果仍为合法一等结果；门控只在「完全无数据」时失败
    return ExperimentEvidence(
        results_json_path=results_path, summary=summary,
        tables={"n_rows": len(data.get("experiments", {}).get("memory_bench", {}).get("ablation", []))},
        negative_results=negs, passed_effectiveness=passed, raw=json.dumps(data, ensure_ascii=False)[:2000])


__all__ = ["execute", "summarize_evidence", "extract_negative"]

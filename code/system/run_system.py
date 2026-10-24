"""系统入口 / 编排器（runnable）。

两种运行模式：
- `deterministic`（默认，今天即可跑）：从真实 results.json 经确定性路径生成
  示例论文 + 图表 + 日志 + 跑通 FARS 三项优化的量化演示。零 LLM 依赖、零幻觉、
  完全可复现。这就是「完整可运行的系统实现」中**可验证**的那条路径。
- `agentic`：在 openJiuwen SwarmFlow 引擎上跑四模块 LLM 多智能体编排
  （ideation/planning/experiment/writing 的 swarmflow 路径），须引擎 +
  已配置 LLM 可用（models.defaults[0]，当前为 mimo-v2.6-flash）。

本文件同时演示：任务队列（scheduler）如何把「四模块」编排为带优先级/重试/降级的
流水线；context_cache 如何给出 Token 降本量化对比；hypothesis_eval 如何门控假设；
causal_analysis 如何产出机制级洞察。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = os.path.join(ROOT, "output", "results.json")
PAPER_DIR = os.path.join(ROOT, "paper_system")
CHART_DIR = os.path.join(ROOT, "charts_system")
LOG_DIR = os.path.join(ROOT, "logs_system")
CACHE_DIR = os.path.join(ROOT, "outputs_system", ".cache")

sys.path.insert(0, ROOT)

from system import (  # noqa: E402
    contracts as C,
    context_cache as cc,
    hypothesis_eval as he,
    causal_analysis as ca,
    paper_builder as pb,
    charts as ch,
    scheduler as sch,
    ideation as M_ideation,
    planning as M_planning,
    experiment as M_experiment,
    writing as M_writing,
    orchestrator as orch,
)


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_token_saving_demo() -> dict:
    """FARS 优化①量化演示：baseline vs optimized 单篇 Token 估算。"""
    with open(RESULTS, "r", encoding="utf-8") as f:
        res_text = f.read()
    literature = ("Transformer 全量注意力无界；RAG 以检索替代长上下文；"
                 "记忆压缩有损但可扩展；分层记忆兼顾近远期。" * 30)
    plan = ("实验方案：六策略×三预算×三种子；指标 accuracy/std/CI/footprint/latency；"
            "消融压缩预算曲线；统计多种子聚合。" * 20)
    comp = cc.estimate_token_saving(res_text, literature, plan, n_papers_reusing_cache=5)
    return {
        "baseline_tokens": comp.baseline_tokens,
        "optimized_tokens": comp.optimized_tokens,
        "saving_pct": comp.saving_pct,
        "breakdown": comp.breakdown,
        "interpretation": (
            "启用上下文压缩（文献/计划仅消费压缩体≈30%）+ 中间结果缓存复用"
            f"（results 数值表跨 5 篇仅首次生成），单篇估算降本 {comp.saving_pct}%。"
            "FARS 实测单篇约 1.14 亿 token（228 小时 28 分产出 100 篇、"
            "合计 114 亿 token）；同类系统若复用本缓存机制，"
            "同数据集多论文场景可显著摊薄。"
        ),
    }


def run_hypothesis_gate_demo() -> dict:
    """FARS 优化②演示：双维评估门控。"""
    hyp = C.Hypothesis(
        statement=("在受限上下文预算下，分层记忆引擎（滑窗+检索+压缩）优于单一策略，"
                   "且预算越大优势越显著——可通过 memory_bench 三预算×三种子验证。"),
        rationale="受限策略在准确率与 footprint 间存在结构权衡，需统一基准量化。",
        modules=["sliding_window", "retrieval", "compression", "hierarchical"],
        references=[
            "Transformer 全量注意力(2017)——无界上下文，成本随序列平方增长",
            "RAG(2020)——以检索替代长上下文，延迟随候选集增长",
            "Memory Networks(2015)——有损压缩但可扩展",
            "LSTM(1997)——分层长期记忆兼顾近远期",
            "Test-Time Memory Scaling(2025)——近期记忆缩放方向",
            "FARS(2026)——全自动科研系统，鼓励负结果报告",
        ],
    )
    res = he.evaluate(hyp, n_refs_with_diff=6)
    gate = he.gate_report([res])
    return {"hypothesis": hyp.statement, "eval": res.__dict__, "gate": gate}


def run_causal_demo() -> dict:
    """FARS 优化③演示：机制级因果洞察。"""
    with open(RESULTS, "r", encoding="utf-8") as f:
        data = json.load(f)
    report = ca.analyze(data)
    return {
        "n_insights": len(report.insights),
        "insights": [i.title for i in report.insights],
        "negative_diagnoses": report.negative_diagnoses,
    }


def run_scheduler_demo() -> dict:
    """调度演示：四模块作为任务入队，带依赖/优先级/重试/降级。"""
    tasks = [
        C.Task("t_idea", C.Phase.IDEATION, priority=9),
        C.Task("t_plan", C.Phase.PLANNING, priority=8, depends_on=["t_idea"]),
        C.Task("t_exp", C.Phase.EXPERIMENT, priority=7, depends_on=["t_plan"]),
        C.Task("t_write", C.Phase.WRITING, priority=6, depends_on=["t_exp"]),
    ]
    s = sch.ResearchScheduler()
    for t in tasks:
        s.submit(t)

    # 确定性 handler：每个 phase 直接走可用产物（无 LLM 也完成）
    def handler(task: C.Task):
        if task.phase == C.Phase.IDEATION:
            return "hypothesis"
        if task.phase == C.Phase.PLANNING:
            return "plan"
        if task.phase == C.Phase.EXPERIMENT:
            return "evidence"
        if task.phase == C.Phase.WRITING:
            return "manuscript"
        raise RuntimeError("unknown")

    # 降级：若某 phase handler 抛错，退回缓存产物
    deg = sch.DegradationPolicy(fallbacks={
        C.Phase.IDEATION: lambda t: "hypothesis(cached)",
        C.Phase.PLANNING: lambda t: "plan(cached)",
        C.Phase.EXPERIMENT: lambda t: "evidence(cached)",
        C.Phase.WRITING: lambda t: "manuscript(cached)",
    })
    s.degradation = deg
    s.run({p: handler for p in [C.Phase.IDEATION, C.Phase.PLANNING,
                                C.Phase.EXPERIMENT, C.Phase.WRITING]})
    return s.summary()


def run_deterministic() -> dict:
    """默认运行：生成示例论文 + 图表 + 日志（真实数据，零幻觉）。"""
    os.makedirs(PAPER_DIR, exist_ok=True)
    os.makedirs(CHART_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    t0 = time.perf_counter()

    # 图表（来自真实 results.json）
    figs = ch.generate_all(RESULTS, CHART_DIR)

    # 因果分析
    with open(RESULTS, "r", encoding="utf-8") as f:
        data = json.load(f)
    report = ca.analyze(data)
    insights_md = ca.render_insights_md(report)

    # 论文（确定性渲染，数字全部来自 results.json）——经编排层走真实四模块链
    # （构思→规划→实验→写作），agent-core Workflow 图 / stdlib 顺序回退双后端；
    # writing 只消费 results.json + figures，故产物与逐模块直调逐字节等价。
    seed_hyp = C.Hypothesis(statement="受限预算下记忆策略权衡", rationale="", modules=[])
    pipe = orch.run_pipeline({
        "results_path": RESULTS,
        "paper_dir": PAPER_DIR,
        "chart_dir": CHART_DIR,
        "figures": figs,
        "topic": "Agent记忆引擎：长程流式任务中的记忆策略权衡",
        "direction": "memory_engine",
        "seed_hypothesis": seed_hyp,
    })
    manu = pipe["manu"]
    orchestration = pipe["provenance"]

    # 三项优化演示
    token_demo = run_token_saving_demo()
    gate_demo = run_hypothesis_gate_demo()
    causal_demo = run_causal_demo()
    sched_demo = run_scheduler_demo()

    elapsed = round(time.perf_counter() - t0, 2)

    # 日志
    log = {
        "generated_at": _now(),
        "mode": "deterministic",
        "results_source": RESULTS,
        "paper_path": manu.path,
        "figures": figs,
        "elapsed_sec": elapsed,
        # 编排溯源（agent-core Workflow 图 / stdlib 顺序回退，见 system/orchestrator.py）
        "orchestration": orchestration,
        "fars_optimizations": {
            "context_compression_cache": token_demo,
            "hypothesis_2d_gate": gate_demo,
            "causal_analysis": causal_demo,
        },
        "scheduler": sched_demo,
        "negative_results": report.negative_diagnoses,
    }
    log_path = os.path.join(LOG_DIR, "run_log.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

    # 人类可读日志
    txt = (
        f"[openJiuwen 科研短论文系统] 确定性运行日志 {log['generated_at']}\n"
        f"模式: deterministic（零 LLM，真实数据，零幻觉）\n"
        f"数据源: {RESULTS}\n"
        f"论文: {manu.path}\n"
        f"图表: {', '.join(figs)}\n"
        f"耗时: {elapsed}s\n"
        f"--- FARS 优化① Token 降本: baseline={token_demo['baseline_tokens']} → "
        f"optimized={token_demo['optimized_tokens']} ({token_demo['saving_pct']}%)\n"
        f"--- FARS 优化② 假设门控: {gate_demo['eval']['decision']} "
        f"(nov={gate_demo['eval']['novelty']}, fea={gate_demo['eval']['feasibility']})\n"
        f"--- FARS 优化③ 因果洞察: {causal_demo['n_insights']} 条机制级洞察，"
        f"{len(causal_demo['negative_diagnoses'])} 条负结果诊断\n"
        f"--- 调度: {sched_demo['by_status']}\n"
    )
    with open(os.path.join(LOG_DIR, "run_log.txt"), "w", encoding="utf-8") as f:
        f.write(txt)

    return {"paper": manu.path, "figures": figs, "log": log_path, "log_txt": txt,
            "token_demo": token_demo, "gate_demo": gate_demo,
            "causal_demo": causal_demo, "sched_demo": sched_demo,
            "insights_md": insights_md}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "deterministic"
    if mode == "agentic":
        print("[run_system] agentic 模式需 openJiuwen 引擎 + 已配置 LLM（当前 mimo-v2.6-flash），请在引擎内以 SwarmFlow 调用。")
        print("[run_system] 四模块 swarmflow 路径见 system/{ideation,planning,experiment,writing}.py。")
        return 0
    out = run_deterministic()
    print(out["log_txt"])
    print("\n[完成] 论文与全部产物已生成：")
    print("  论文:", out["paper"])
    print("  图表:", "\n        ".join(out["figures"]))
    print("  日志:", out["log"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

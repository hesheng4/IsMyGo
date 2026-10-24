"""memory_bench 主实验：记忆策略 × 预算 ablation × 距离分带机制分析。

指标（全部由真实代码执行得出）：
- accuracy / accuracy_{band}：总体与分带精确匹配率
- footprint：稳态记忆占用（事实条数）
- query_latency_ms：单查询平均耗时

输出结构见 run_all.py 的 results.json。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .strategies import build
from .task import Task, build_task

POLICIES = ("full_context", "sliding_window", "retrieval", "retrieval_recency",
            "compression", "hierarchical")
BANDS = ("ancient", "mid", "recent")


@dataclass
class RunResult:
    policy: str
    budget: int
    accuracy: float
    accuracy_ancient: float
    accuracy_mid: float
    accuracy_recent: float
    footprint: int
    query_latency_ms: float

    def as_dict(self) -> dict:
        return {
            "policy": self.policy,
            "budget": self.budget,
            "accuracy": round(self.accuracy, 4),
            "accuracy_ancient": round(self.accuracy_ancient, 4),
            "accuracy_mid": round(self.accuracy_mid, 4),
            "accuracy_recent": round(self.accuracy_recent, 4),
            "footprint": self.footprint,
            "query_latency_ms": round(self.query_latency_ms, 3),
        }


def run_one(task: Task, policy: str, budget: int) -> RunResult:
    """单次（策略, 预算）运行：写流 + 查询评估。"""
    mem = build(policy, budget)
    for ent, attr, val in task.stream:
        mem.write(ent, attr, val)

    correct = {"ancient": 0, "mid": 0, "recent": 0}
    total = {"ancient": 0, "mid": 0, "recent": 0}
    latency_sum = 0.0
    for ent, attr, answer, band in task.queries:
        t0 = time.perf_counter()
        got = mem.query(ent, attr)
        latency_sum += (time.perf_counter() - t0) * 1000.0
        total[band] += 1
        if got == answer:
            correct[band] += 1

    acc = {b: (correct.get(b, 0) / total.get(b, 0)) if total.get(b, 0) else 0.0 for b in BANDS}
    n = sum(total.values())
    return RunResult(
        policy=policy,
        budget=budget,
        accuracy=(sum(correct.values()) / n) if n else 0.0,
        accuracy_ancient=acc.get("ancient", 0.0),
        accuracy_mid=acc.get("mid", 0.0),
        accuracy_recent=acc.get("recent", 0.0),
        footprint=mem.footprint(),
        query_latency_ms=(latency_sum / n) if n else 0.0,
    )


def run_experiment(seeds: tuple[int, ...] = (42,), budgets: tuple[int, ...] = (16, 32, 64),
                   n_entities: int = 40, facts_per_entity: int = 6,
                   n_queries: int = 120) -> dict:
    """完整实验：全量基线 + 受限策略的预算 ablation（含 recency 对照），多种子聚合。

    Returns:
        {main: [...RunResult], ablation: [...RunResult], config: {...}}
    """
    main_rows: list[dict] = []
    ablation_rows: list[dict] = []

    for policy in POLICIES:
        for budget in budgets:
            per_seed: list[RunResult] = []
            for seed in seeds:
                task = build_task(seed, n_entities=n_entities,
                                  facts_per_entity=facts_per_entity,
                                  n_queries=n_queries)
                per_seed.append(run_one(task, policy, budget))
            agg = _aggregate(per_seed)
            row = {"policy": policy, "budget": budget, **agg}
            # full_context 只需一行主结果（预算不影响），受限策略进 ablation
            (main_rows if (policy == "full_context" and budget == budgets[0])
             else ablation_rows).append(row)

    return {
        "main": main_rows,
        "ablation": ablation_rows,
        "config": {
            "seeds": list(seeds),
            "budgets": list(budgets),
            "n_entities": n_entities,
            "facts_per_entity": facts_per_entity,
            "n_queries": n_queries,
        },
    }


def _aggregate(runs: list[RunResult]) -> dict:
    keys = ("accuracy", "accuracy_ancient", "accuracy_mid",
            "accuracy_recent", "footprint", "query_latency_ms")
    out: dict = {}
    for k in keys:
        vals = [getattr(r, k) for r in runs]
        out[k] = round(sum(vals) / len(vals), 4)
    # 逐种子统计：总体 accuracy 的标准差与 95% t 置信区间半宽
    import statistics as _st
    accs = [r.accuracy for r in runs]
    if len(accs) > 1:
        out["accuracy_std"] = round(_st.stdev(accs), 4)
        # t_{n-1, 0.975}
        t_crit = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571}.get(len(accs), 2.0)
        half = t_crit * _st.stdev(accs) / (len(accs) ** 0.5)
        out["accuracy_ci95"] = round(half, 4)
    return out

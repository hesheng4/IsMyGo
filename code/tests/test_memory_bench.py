"""memory_bench 核心测试：确定性、schema、机制级断言。

运行：python -m pytest tests/test_memory_bench.py -v
（在 paper-lab 根目录；纯标准库实现，无第三方依赖）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB_ROOT / "experiments"))

from memory_bench.experiment import run_experiment, run_one  # noqa: E402
from memory_bench.strategies import RetrievalMemory, build  # noqa: E402
from memory_bench.task import build_task  # noqa: E402

RESULTS = LAB_ROOT / "output" / "results.json"


# ---------------- 确定性 ----------------

def test_task_deterministic_same_seed():
    assert build_task(42) == build_task(42)


def test_task_different_seeds_differ():
    t1, t2 = build_task(42), build_task(43)
    assert t1.stream != t2.stream or t1.queries != t2.queries


def test_experiment_deterministic():
    kw = dict(seeds=(42,), budgets=(16,), n_entities=10,
              facts_per_entity=4, n_queries=30)

    def strip_latency(payload):
        for row in payload["main"] + payload["ablation"]:
            row.pop("query_latency_ms")  # 墙钟计时非种子控制
        return payload

    assert (strip_latency(run_experiment(**kw))
            == strip_latency(run_experiment(**kw)))


# ---------------- 机制级断言（真实失败模式） ----------------

def test_full_context_perfect():
    task = build_task(42)
    r = run_one(task, "full_context", budget=16)
    assert r.accuracy == 1.0
    assert r.accuracy_ancient == r.accuracy_mid == r.accuracy_recent == 1.0


def test_sliding_window_ancient_zero_when_budget_small():
    task = build_task(42)
    r = run_one(task, "sliding_window", budget=16)
    assert r.accuracy_ancient == 0.0


def test_retrieval_no_recency_returns_stale_value():
    """回归测试：无 recency 先验的检索在重写场景返回陈旧答案。

    此前 bug：检索基线恒 100%（键去重吞掉了版本冲突）。现在保留
    全部历史版本，BM25 平局按旧文档优先 → 陈旧答案失败模式。
    """
    mem = RetrievalMemory(budget=8, recency_boost=0.0)
    mem.write("e1", "color", "red")
    mem.write("e2", "size", "big")
    mem.write("e1", "color", "blue")
    assert mem.query("e1", "color") == "red"


def test_retrieval_with_recency_returns_latest():
    mem = RetrievalMemory(budget=8, recency_boost=1.0)
    mem.write("e1", "color", "red")
    mem.write("e2", "size", "big")
    mem.write("e1", "color", "blue")
    assert mem.query("e1", "color") == "blue"


def test_retrieval_not_perfect_regression():
    """受限检索（预算 << 流长）不得拿到满分，否则实验失去意义。"""
    task = build_task(42)
    for budget in (16, 32, 64):
        assert run_one(task, "retrieval", budget).accuracy < 1.0


def test_bounded_footprint():
    task = build_task(42)
    for policy in ("sliding_window", "retrieval", "retrieval_recency"):
        for budget in (16, 32):
            assert run_one(task, policy, budget).footprint <= budget


def test_recency_fixes_or_matches_at_every_budget():
    """机制结论：recency 先验在每个预算下都不差于无先验检索。"""
    task = build_task(42)
    for budget in (16, 32, 64):
        base = run_one(task, "retrieval", budget).accuracy
        boosted = run_one(task, "retrieval_recency", budget).accuracy
        assert boosted >= base


def test_build_rejects_unknown_policy():
    try:
        build("nope", 16)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


# ---------------- results.json schema ----------------

def _rows():
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    bench = data["experiments"]["memory_bench"]
    return data, bench


def test_results_schema():
    assert RESULTS.exists(), "results.json 缺失：先跑 experiments/run_all.py"
    data, bench = _rows()
    for key in ("topic", "experiment", "python", "platform",
                "duration_sec", "deterministic"):
        assert key in data["meta"]
    assert data["meta"]["deterministic"] is True
    for key in ("cmd", "cwd", "seed_policy"):
        assert key in data["provenance"]
    for key in ("main", "ablation", "config"):
        assert key in bench

    row_keys = {"policy", "budget", "accuracy", "accuracy_ancient",
                "accuracy_mid", "accuracy_recent", "footprint",
                "query_latency_ms"}
    for row in bench["main"] + bench["ablation"]:
        assert row_keys <= set(row), row
        for m in ("accuracy", "accuracy_ancient", "accuracy_mid",
                  "accuracy_recent"):
            assert 0.0 <= row[m] <= 1.0, row
        assert row["footprint"] >= 0 and row["query_latency_ms"] >= 0


def test_results_cover_all_policies():
    _, bench = _rows()
    main_policies = {r["policy"] for r in bench["main"]}
    abl_policies = {r["policy"] for r in bench["ablation"]}
    assert main_policies == {"full_context"}
    assert {"sliding_window", "retrieval", "retrieval_recency"} <= abl_policies
    cfg = bench["config"]
    for key in ("seeds", "budgets", "n_entities", "facts_per_entity",
                "n_queries"):
        assert key in cfg
    assert len(cfg["seeds"]) >= 3, "标准档应多种子聚合"


def test_results_reproduce_row_from_code():
    """results.json 的 full_context 主行可由当前代码独立复算（多种子均值）。"""
    _, bench = _rows()
    cfg = bench["config"]
    runs = []
    for seed in cfg["seeds"]:
        task = build_task(seed, n_entities=cfg["n_entities"],
                          facts_per_entity=cfg["facts_per_entity"],
                          n_queries=cfg["n_queries"])
        runs.append(run_one(task, "full_context", budget=cfg["budgets"][0]))
    row = bench["main"][0]
    assert row["accuracy"] == round(sum(r.accuracy for r in runs) / len(runs), 4)
    assert row["footprint"] == round(sum(r.footprint for r in runs) / len(runs), 4)

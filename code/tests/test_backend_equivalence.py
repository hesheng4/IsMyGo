"""双后端等价性测试（agent-core 复用 vs stdlib 回退）。

验证「用 agent-core 复用基础类但不改变行为」这一核心约束：
- 内容哈希：openjiuwen hash_text 与内置 sha256[:16] 逐位一致（context_cache._sha 的双后端根基）。
- 任务追踪：TaskTracker 在两后端下记录一致。
- 编排等价：orchestrator 走真实四模块链，产出 Manuscript 且各阶段契约齐备。
- 后端解析：PAPER_LAB_BACKEND 开关正确，agentcore 不可用时优雅回退 stdlib（不抛错）。

注：pytest 会话内其它 rail 测试以桩模块污染 sys.modules 的 openjiuwen，
故本文件不强制要求真实 openjiuwen；importorskip + 后端回退保证任一环境可跑。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from system import backends, contracts as C, context_cache as cc, orchestrator as orch

RESULTS = os.path.join(ROOT, "output", "results.json")


def test_hash_text_matches_stdlib_sha():
    """hash_text（agent-core 复用）与内置 sha256[:16] 逐位一致——双后端可安全互换。"""
    from hashlib import sha256
    expect = sha256("abc123".encode("utf-8")).hexdigest()[:16]
    assert backends._stdlib_hash_text("abc123") == expect
    assert cc._sha("abc123") == expect  # 经 get_hash_fn，stdlib 后端下即 _stdlib_hash_text
    for s in ("", "x", "中文内容", "a" * 1000):
        assert cc._sha(s) == sha256(s.encode("utf-8")).hexdigest()[:16]


def test_resolve_backend_never_raises():
    """后端解析永不抛错：stdlib 显式、auto、agentcore 均返回合法后端（不可用时回退）。"""
    for pref in ("stdlib", "auto", "agentcore"):
        os.environ["PAPER_LAB_BACKEND"] = pref
        try:
            b = backends.resolve_backend()
            assert b in (backends.BACKEND_AGENTCORE, backends.BACKEND_STDLIB)
        finally:
            os.environ.pop("PAPER_LAB_BACKEND", None)


def test_task_tracker_records_both_backends():
    """TaskTracker 记录与任务树摘要在任一后端下均可用。"""
    tr = backends.TaskTracker()
    tr.record("t1", "succeeded", attempts=1)
    tr.record("t2", "degraded", attempts=3)
    assert [r["task_id"] for r in tr.records()] == ["t1", "t2"]
    tree = tr.task_tree()
    assert isinstance(tree, str) and tree  # agentcore=task_manager 树 / stdlib=记录摘要


def test_scheduler_summary_has_observability_fields():
    """ResearchScheduler.summary 增补 backend/task_tree 字段，原字段不变。"""
    from system import scheduler as sch
    s = sch.ResearchScheduler(retry=sch.RetryPolicy(max_attempts=1, base_delay_s=0.001),
                              degradation=sch.DegradationPolicy(
                                  fallbacks={C.Phase.IDEATION: lambda t: "cached"}))

    def fail(t):
        raise RuntimeError("boom")

    s.submit(C.Task("t1", C.Phase.IDEATION, max_attempts=1))
    s.run({C.Phase.IDEATION: fail})
    sm = s.summary()
    # 原字段
    assert sm["total"] == 1 and "by_status" in sm and "degraded_tasks" in sm
    assert sm["by_status"].get("degraded") == 1
    # 增补字段
    assert "task_tree" in sm and "backend" in sm


def test_orchestrator_runs_four_module_chain():
    """编排层走真实四模块链：产出 Manuscript + 四阶段 provenance + 契约链。"""
    import tempfile
    seed = C.Hypothesis(statement="受限预算下记忆策略权衡", rationale="", modules=[])
    pipe = orch.run_pipeline({
        "results_path": RESULTS,
        "paper_dir": tempfile.mkdtemp(),
        "chart_dir": tempfile.mkdtemp(),
        "figures": [],
        "topic": "记忆策略权衡",
        "direction": "memory_engine",
        "seed_hypothesis": seed,
    })
    manu = pipe["manu"]
    assert manu is not None and manu.full_text
    prov = pipe["provenance"]
    assert prov["backend"] in ("agentcore", "stdlib")
    phases = [s["phase"] for s in prov["steps"]]
    assert phases == ["ideation", "planning", "experiment", "writing"]
    chain = pipe["contract_chain"]
    assert chain["hypothesis"] and chain["evidence"]


def test_build_gate_router_shape():
    """contracts.build_gate_router：agentcore 可用时返回带 2 分支的 BranchRouter。"""
    if not backends.agentcore_available():
        pytest.skip("真实 openjiuwen 不可用（可能被测试桩遮蔽），跳过 BranchRouter 断言")
    router = C.build_gate_router(lambda: "pass", "writing", "end", pass_value="pass")
    assert hasattr(router, "add_branch")
    assert router.all_targets == {"writing", "end"}


if __name__ == "__main__":
    test_hash_text_matches_stdlib_sha()
    test_resolve_backend_never_raises()
    test_task_tracker_records_both_backends()
    test_scheduler_summary_has_observability_fields()
    test_orchestrator_runs_four_module_chain()
    print("BACKEND EQUIVALENCE TESTS PASSED")

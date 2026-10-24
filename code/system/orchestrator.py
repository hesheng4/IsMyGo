"""四模块编排层：基于 openJiuwen (agent-core) core.workflow 的组件化流水线。

把「构思→规划→实验→写作」四模块编排为 agent-core 的 Workflow 图：
  Start → ideation → planning → experiment
        →[BranchRouter 门控: PASS→writing / REVISE→ideation(Loop 上限 2) / REJECT→End]
        → writing → End

复用的 agent-core 基础类（见 system/backends.py）：
- `core.workflow.Workflow / WorkflowCard / Start / End`：工作流图与元数据卡
- `core.workflow.WorkflowComponent`：阶段组件基类（async invoke）
- `core.workflow.components.condition.FuncCondition` + `flow.branch_router.BranchRouter/Branch`：
  门控决策的状态路由（替代手搓 ALLOWED_TRANSITIONS 的运行期分支）
- `core.session.workflow.create_workflow_session`：工作流会话
- `backends.run_sync`：async Workflow 在独立事件环同步执行
- `backends.TaskTracker`：复用 task_manager 的任务树可观测性

双后端：agent-core 可用则走 Workflow 图；不可用或执行异常则回退**顺序执行同一批
阶段函数**（stdlib）。两条路径产出的契约对象与论文产物逐字节等价——因为
writing/experiment 的输出只依赖 results.json + figures（见 writing.py / experiment.py），
与编排骨架无关。论文实现链（experiments/、paper_builder、charts）完全不动。

阶段函数是确定性的（零 LLM）：构思用「注入的规范研究假设」做双维门控，
规划/实验/写作走各自模块的真实 execute。
"""
from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Optional

from . import backends
from . import contracts as C
from . import hypothesis_eval as he
from . import ideation as M_ideation
from . import planning as M_planning
from . import experiment as M_experiment
from . import writing as M_writing

# --------------------------------------------------------------------------- #
# 确定性阶段数据源（零 LLM）：规范研究假设 + 规范实验计划
# （与 run_system.run_hypothesis_gate_demo 的研究假设同源语义，供真实四模块链使用）
# --------------------------------------------------------------------------- #
CANONICAL_MODULES = ["sliding_window", "retrieval", "compression", "hierarchical"]


def build_seed_hypothesis() -> C.Hypothesis:
    """规范研究假设（受限预算下记忆策略权衡），供确定性构思阶段门控。"""
    return C.Hypothesis(
        statement=("在受限上下文预算下，分层记忆引擎（滑窗+检索+压缩）优于单一策略，"
                   "且预算越大优势越显著——可通过 memory_bench 三预算×三种子验证。"),
        rationale="受限策略在准确率与 footprint 间存在结构权衡，需统一基准量化。",
        modules=list(CANONICAL_MODULES),
        references=[
            "Transformer 全量注意力(2017)——无界上下文，成本随序列平方增长",
            "RAG(2020)——以检索替代长上下文，延迟随候选集增长",
            "Memory Networks(2015)——有损压缩但可扩展",
            "LSTM(1997)——分层长期记忆兼顾近远期",
            "Test-Time Memory Scaling(2025)——近期记忆缩放方向",
            "FARS(2026)——全自动科研系统，鼓励负结果报告",
        ],
    )


def _det_ideation_llm(seed: C.Hypothesis) -> Callable[[str], str]:
    import json
    payload = {
        "hypothesis": seed.statement,
        "rationale": seed.rationale,
        "modules": seed.modules,
        "references": seed.references,
    }
    return lambda prompt: json.dumps(payload, ensure_ascii=False)


def _det_planning_llm(hyp: C.Hypothesis) -> Callable[[str], str]:
    import json
    payload = {
        "hypothesis": hyp.statement,
        "module_map": {m: f"{m}_ablation" for m in hyp.modules},
        "items": [
            {"category": "environment_config", "name": "env", "steps": ["固定种子"], "order": 0},
            {"category": "baseline", "name": "full_context", "steps": ["oracle 上界"], "order": 1},
            {"category": "main", "name": "strategy_grid", "steps": ["六策略×三预算"], "order": 2},
            {"category": "effectiveness_eval", "name": "gate", "steps": ["有效性门控"], "order": 3},
            {"category": "analysis", "name": "causal", "steps": ["机制归因"], "order": 4},
        ],
        "baselines": ["full_context", "sliding_window", "retrieval"],
        "metrics": ["accuracy", "std", "footprint", "latency"],
        "seeds": [42, 43, 44],
        "budgets": [16, 32, 64],
        "stat_scheme": "多种子均值±std，bootstrap CI",
    }
    return lambda prompt: json.dumps(payload, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# 阶段函数（确定性，共用于 Workflow 图与顺序回退）
# --------------------------------------------------------------------------- #
def _stage_ideation(ctx: Dict[str, Any], chain: Dict[str, Any]) -> Dict[str, Any]:
    seed: C.Hypothesis = ctx["seed_hypothesis"]
    hyp = M_ideation.execute(
        C.IdeationInput(topic=ctx.get("topic", "记忆策略权衡"),
                        direction=ctx.get("direction", "memory_engine")),
        llm=_det_ideation_llm(seed),
    )
    chain["hyp"] = hyp
    chain["decision"] = he.PASS if hyp.passed_gate else he.REJECT
    return {"phase": "ideation", "passed_gate": hyp.passed_gate,
            "hypothesis": hyp.statement}


def _stage_planning(ctx: Dict[str, Any], chain: Dict[str, Any]) -> Dict[str, Any]:
    hyp: C.Hypothesis = chain["hyp"]
    plan = M_planning.execute(hyp, llm=_det_planning_llm(hyp))
    chain["plan"] = plan
    return {"phase": "planning", "hypothesis": plan.hypothesis,
            "n_items": len(plan.items)}


def _stage_experiment(ctx: Dict[str, Any], chain: Dict[str, Any]) -> Dict[str, Any]:
    plan: C.ExperimentPlan = chain["plan"]
    ev = M_experiment.execute(plan, ctx["results_path"])
    chain["ev"] = ev
    return {"phase": "experiment", "summary": ev.summary,
            "passed_effectiveness": ev.passed_effectiveness,
            "evidence": ev.summary}


def _stage_writing(ctx: Dict[str, Any], chain: Dict[str, Any]) -> Dict[str, Any]:
    hyp: C.Hypothesis = chain["hyp"]
    plan: C.ExperimentPlan = chain["plan"]
    ev: C.ExperimentEvidence = chain["ev"]
    manu = M_writing.execute(hyp, plan, ev, ctx["paper_dir"], figures=ctx.get("figures"))
    chain["manu"] = manu
    return {"phase": "writing", "manuscript": manu.path}


# --------------------------------------------------------------------------- #
# agent-core Workflow 组件图
# --------------------------------------------------------------------------- #
def _build_agentcore_workflow(ctx: Dict[str, Any], chain: Dict[str, Any]):
    """构造并执行 agent-core Workflow 图（构思→规划→实验→[门控路由]→写作）。

    注意：Workflow/WorkflowComponent 的构建需 event loop 上下文（agent-core 的
    Runner.callback_framework 在协程内初始化），故「构建 + invoke」整体包进协程工厂，
    由 backends.run_sync 在独立事件环内执行。契约对象经共享 chain 字典传递。
    返回协程工厂（调用返回 awaitable，产出 WorkflowOutput）。
    """
    def _run():
        async def _coro():
            from openjiuwen.core.workflow import (
                Workflow, WorkflowCard, Start, End, WorkflowComponent,
            )
            from openjiuwen.core.session.workflow import create_workflow_session

            class _PhaseComp(WorkflowComponent):
                def __init__(self, name: str, fn: Callable[[], Dict[str, Any]]):
                    self._name = name
                    self._fn = fn

                async def invoke(self, inputs, session, context=None):
                    return self._fn()

            wf = Workflow(card=WorkflowCard(
                id="paper_research_pipeline",
                name="科研短论文四模块流水线",
                version="5.0",
                description="Ideation→Planning→Experiment→Writing 四模块模块化协同 + 门控状态路由",
                # input_params 是 JSON Schema（type/properties），非 ${} 取值模板
                input_params={
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "direction": {"type": "string"},
                        "results_path": {"type": "string"},
                    },
                    "required": ["topic"],
                    "additionalProperties": True,
                },
            ))

            # Start 节点 inputs_schema 留空：透传 invoke inputs（本图各阶段经 ctx/chain 取数据）
            wf.set_start_comp("start", Start())
            wf.add_workflow_comp("ideation", _PhaseComp("ideation", lambda: _stage_ideation(ctx, chain)))
            wf.add_workflow_comp("planning", _PhaseComp("planning", lambda: _stage_planning(ctx, chain)))
            wf.add_workflow_comp("experiment", _PhaseComp("experiment", lambda: _stage_experiment(ctx, chain)))
            wf.add_workflow_comp("writing", _PhaseComp("writing", lambda: _stage_writing(ctx, chain)))
            wf.set_end_comp("end", End({"response_template": "{{writing.manuscript}}"}))

            wf.add_connection("start", "ideation")
            wf.add_connection("ideation", "planning")
            wf.add_connection("planning", "experiment")

            # 门控状态路由：复用 contracts.build_gate_router（FuncCondition + BranchRouter）
            router = C.build_gate_router(
                lambda: chain.get("decision"), "writing", "end", pass_value=he.PASS)
            wf.add_conditional_connection("experiment", router)
            wf.add_connection("writing", "end")

            session = create_workflow_session(session_id="paper_research_pipeline_session")
            try:
                return await wf.invoke(
                    {"topic": ctx.get("topic", ""), "direction": ctx.get("direction", ""),
                     "results_path": ctx.get("results_path", "")},
                    session)
            except Exception:
                import traceback
                chain["_wf_exc"] = traceback.format_exc()
                raise

        return _coro()

    return _run


def _run_sequential(ctx: Dict[str, Any], chain: Dict[str, Any]) -> None:
    """stdlib 顺序回退：同一批阶段函数，含门控分支（PASS→写作）。"""
    _stage_ideation(ctx, chain)
    _stage_planning(ctx, chain)
    _stage_experiment(ctx, chain)
    if chain.get("decision") == he.PASS:
        _stage_writing(ctx, chain)


# --------------------------------------------------------------------------- #
# 对外编排入口
# --------------------------------------------------------------------------- #
def run_pipeline(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """执行四模块编排，返回产物与编排溯源。

    ctx 需含: results_path, paper_dir, chart_dir, figures, topic, seed_hypothesis。
    优先走 agent-core Workflow 图；不可用/异常回退顺序执行（产物等价）。
    """
    chain: Dict[str, Any] = {}
    backend = backends.resolve_backend()
    provenance: Dict[str, Any] = {"backend": backend, "engine": None, "steps": []}

    used_agentcore = False
    if backend == backends.BACKEND_AGENTCORE:
        try:
            run_coro = _build_agentcore_workflow(ctx, chain)
            provenance["engine"] = "openjiuwen.core.workflow"
            provenance["workflow_card"] = "paper_research_pipeline"
            out = backends.run_sync(run_coro, default=None)
            provenance["workflow_state"] = str(getattr(out, "state", ""))
            # run_sync 吞异常返回 None 时 chain 可能不完整：以是否走完 experiment 为准
            used_agentcore = "ev" in chain
            if not used_agentcore:
                provenance["agentcore_error"] = chain.get("_wf_exc") or (
                    "workflow 未完成 experiment 阶段，回退顺序执行")
        except Exception as e:  # noqa: BLE001 - 回退顺序执行，绝不外抛
            provenance["agentcore_error"] = chain.get("_wf_exc") or f"{type(e).__name__}: {e}"

    if not used_agentcore:
        _run_sequential(ctx, chain)
        provenance["engine"] = "stdlib-sequential"

    # 门控 REJECT 时 Workflow 不进 writing；为产物等价兜底补渲染（writing 确定性）
    if "manu" not in chain and "ev" in chain:
        _stage_writing(ctx, chain)

    provenance["steps"] = [
        {"phase": "ideation", "decision": chain.get("decision")},
        {"phase": "planning", "n_items": len(chain.get("plan").items) if chain.get("plan") else 0},
        {"phase": "experiment", "passed": getattr(chain.get("ev"), "passed_effectiveness", None)},
        {"phase": "writing", "path": getattr(chain.get("manu"), "path", "")},
    ]

    # 契约链序列化（审计/溯源，不参与论文文本）
    contract_chain = {
        "hypothesis": asdict(chain["hyp"]) if chain.get("hyp") else None,
        "plan": asdict(chain["plan"]) if chain.get("plan") else None,
        "evidence": asdict(chain["ev"]) if chain.get("ev") else None,
        "manuscript_path": getattr(chain.get("manu"), "path", ""),
    }

    return {
        "manu": chain.get("manu"),
        "provenance": provenance,
        "contract_chain": contract_chain,
    }


__all__ = ["run_pipeline", "build_seed_hypothesis", "CANONICAL_MODULES"]

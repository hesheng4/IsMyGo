# coding: utf-8
"""引擎内端到端校验：用 openjiuwen 真实 run_workflow 跑 research_pipeline_v5。

目的：在**真实 JiuwenSwarm 引擎**（非空壳 stub）上验证 v6 W1 闭环——
hypothesis-review 返回含 module_gaps 的 JSON 时，硬约束文本必须真实注入
planning / writing 两个 agent 的 prompt；无缺口时不得注入。

执行方式：
  conda python paper-lab/deploy/engine_e2e_check.py

后端用引擎自带的确定性离线 MockBackend（zero-network），通过 responder
钉住 hypothesis-review 输出，并记录所有 agent 调用的 prompt 供断言。
这复用了框架官方的 in-process 测试路径（run_workflow + MockBackend）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

try:
    from openjiuwen.agent_teams.workflow.engine.runner import run_workflow
    from openjiuwen.agent_teams.workflow.engine.backends.mock import MockBackend
    from openjiuwen.agent_teams.workflow.engine.progress import ProgressKind
except ImportError:
    sys.exit("engine_e2e_check.py 需要 openjiuwen 引擎环境（conda, 非标准库 venv）。"
             "请激活引擎环境后重试。")

logger = logging.getLogger("engine_e2e_check")
logging.basicConfig(level=logging.INFO, format="%(message)s")

HERE = Path(__file__).resolve().parent
PIPELINE = str(HERE / "research_pipeline_v5.py")

# 流水线确定的 agent 调用顺序（run() 串行 + pacing=False）
EXPECTED_SEQ = [
    "ideation",
    "hypothesis-review",
    "planning",
    "experiment-run",
    "experiment-audit",
    "writing",
    "proofread",
]


def _make_responder(review_json: str, captured: list):
    """返回 MockBackend responder：记录每次 agent 调用，钉住 hypothesis-review。"""

    def responder(prompt, opts, schema_json, rng):
        label = opts.get("label")
        captured.append({"label": label, "phase": opts.get("phase"), "prompt": prompt})
        if label == "hypothesis-review":
            return review_json
        return None  # 其余 label 走 MockBackend 确定性合成

    return responder


async def _run_once(review_json: str):
    captured: list = []
    events: list = []
    backend = MockBackend(responder=_make_responder(review_json, captured))
    result = await run_workflow(
        PIPELINE,
        args={"topic": "受限预算下的记忆策略权衡", "pacing": False},
        backend=backend,
        progress_sink=events.append,
    )
    log_lines = [getattr(e, "message", "") or "" for e in events if e.kind == ProgressKind.LOG]
    phases = [getattr(e, "phase", None) for e in events if e.kind == ProgressKind.PHASE]
    return result, captured, log_lines, phases


def _prompt_of(captured: list, label: str) -> str:
    for c in captured:
        if c["label"] == label:
            return c["prompt"]
    raise ValueError(f"未捕获到 label={label} 的 agent 调用")


def _check_common(result, captured):
    seq = [c["label"] for c in captured]
    if seq != EXPECTED_SEQ:
        raise ValueError(f"agent 调用顺序不符：{seq}")
    if not isinstance(result, dict):
        raise ValueError(f"run() 返回值应为 dict，实际 {type(result)}")
    for k in ("paper", "draft_file", "final_file", "hypothesis", "plan", "results", "token_spent"):
        if k not in result:
            raise ValueError(f"run() 返回缺键 {k}")
    if not (isinstance(result["token_spent"], int) and result["token_spent"] >= 0):
        raise ValueError(f"token_spent 应为非负整数，实际 {result['token_spent']}")


async def scenario_with_gaps():
    """评审返回 module_gaps → W1 硬约束必须注入 planning/writing。"""
    review = json.dumps(
        {
            "passed": False,
            "reason": "hierarchical 与 retrieval 模块无对应实验",
            "risks": ["模块覆盖不足"],
            "module_gaps": ["hierarchical", "retrieval"],
            "baseline_fairness": "full context 仅作 oracle 上界",
        },
        ensure_ascii=False,
    )
    result, captured, logs, phases = await _run_once(review)
    _check_common(result, captured)

    plan_prompt = _prompt_of(captured, "planning")
    write_prompt = _prompt_of(captured, "writing")
    for tag, prompt in (("planning", plan_prompt), ("writing", write_prompt)):
        if "W1 模块覆盖硬约束" not in prompt:
            raise ValueError(f"{tag} prompt 缺 W1 硬约束文本")
        if "hierarchical" not in prompt:
            raise ValueError(f"{tag} prompt 缺缺口模块名 hierarchical")
        if "retrieval" not in prompt:
            raise ValueError(f"{tag} prompt 缺缺口模块名 retrieval")
        if "未来工作" not in prompt:
            raise ValueError(f"{tag} prompt 缺『未来工作』降级要求")
    if not any("W1 模块覆盖缺口" in line for line in logs):
        raise ValueError("run() 未记录 W1 缺口日志")
    if phases != ["ideation", "planning", "planning", "experiment", "writing", "writing"]:
        raise ValueError(f"phase 序列不符：{phases}")
    logger.info("[PASS] 场景A 有缺口：W1 硬约束已注入 planning/writing，顺序/返回/phase 均正确")


async def scenario_no_gaps():
    """评审 module_gaps 为空 → 不得注入 W1 硬约束（证明是条件触发而非恒开）。"""
    review = json.dumps({"passed": True, "reason": "模块覆盖完整", "module_gaps": []}, ensure_ascii=False)
    result, captured, logs, phases = await _run_once(review)
    _check_common(result, captured)

    plan_prompt = _prompt_of(captured, "planning")
    write_prompt = _prompt_of(captured, "writing")
    if "W1 模块覆盖硬约束" in plan_prompt:
        raise ValueError("无缺口时 planning prompt 误注入 W1 约束")
    if "W1 模块覆盖硬约束" in write_prompt:
        raise ValueError("无缺口时 writing prompt 误注入 W1 约束")
    logger.info("[PASS] 场景B 无缺口：planning/writing 未注入 W1 约束（条件触发正确）")


async def main():
    await scenario_with_gaps()
    await scenario_no_gaps()
    logger.info("ALL_ENGINE_E2E_PASS")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

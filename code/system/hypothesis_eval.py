"""FARS 优化点②：假设「创新性-可行性」双维评估与准入门控。

FARS 局限（arXiv:2606.31651）：自主生成的假设并非都强——评审中 novelty 批评占
42.4%，低分论文多「贡献/实验充分性」不足。FARS 用 Peer Discussion Agent 对抗性
预审 + Evaluation Agent 做 accept/revise/reject，但阈值未显式公开。

本模块把「准入门控」显式化为可复现的双维评分函数 + 明确阈值，使「弱想法尽早剪枝」
（FARS 的 peer discussion 意图）成为确定性、可审计的步骤，而非仅依赖模型自觉。

评分标准（每维 0–10，可 LLM 填充，亦可确定性代理填充用于无网/可复现场景）：
  创新性 novelty：
    - 与近邻系统差异度（references 中逐条差异化陈述的数量与质量）
    - 是否提出新机制 / 新权衡视角，而非简单组合
  可行性 feasibility：
    - 是否可在有限算力下确定性复现（seeds/budgets 可枚举）
    - 是否有明确基线可对比、结论可由实验结果支撑
    - 模块是否全部可实验映射（W1：无模块缺口）

门控阈值：
    PASS   : novelty >= 6 and feasibility >= 6
    REVISE : (novelty >= 4 and feasibility >= 4) and not PASS   → 退回修订
    REJECT : novelty < 4 or feasibility < 4                      → 剪枝
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .contracts import Hypothesis


@dataclass
class EvalRubric:
    novelty_threshold_pass: float = 6.0
    feasibility_threshold_pass: float = 6.0
    reject_floor: float = 4.0


PASS, REVISE, REJECT = "pass", "revise", "reject"


@dataclass
class EvalResult:
    novelty: float
    feasibility: float
    decision: str            # pass | revise | reject
    rationale: str


def _deterministic_proxy(h: Hypothesis, n_refs_with_diff: int = 0) -> tuple[float, float]:
    """无 LLM 时的确定性代理评分（用于可复现示例 / 离线测试）。

    以结构性信号近似：references 差异化条数↑ → novelty↑；modules 非空且有
    rationale → feasibility↑。真实部署可替换为 LLM 双维评分（同 rubric）。
    """
    refs = h.references or []
    diff = n_refs_with_diff or sum(1 for r in refs if "差异" in r or "vs" in r or "——" in r)
    novelty = min(10.0, 3.0 + 0.7 * min(diff, 8))
    feas = 5.0
    if h.rationale:
        feas += 1.0
    if h.modules:
        feas += min(2.0, 0.5 * len(h.modules))
    if h.statement and ("可验证" in h.statement or "实验" in h.statement):
        feas += 1.0
    return round(novelty, 2), round(min(10.0, feas), 2)


def evaluate(h: Hypothesis, rubric: EvalRubric | None = None,
             llm_scores: tuple[float, float] | None = None,
             n_refs_with_diff: int = 0) -> EvalResult:
    """双维评估 + 门控决策。

    llm_scores: 可选，由 LLM 给出的 (novelty, feasibility)；缺省走确定性代理。
    返回决策并回写 h.novelty/feasibility/passed_gate。
    """
    rubric = rubric or EvalRubric()
    if llm_scores:
        nov, fea = llm_scores
    else:
        nov, fea = _deterministic_proxy(h, n_refs_with_diff)

    if nov >= rubric.novelty_threshold_pass and fea >= rubric.feasibility_threshold_pass:
        decision = PASS
    elif nov >= rubric.reject_floor and fea >= rubric.reject_floor:
        decision = REVISE
    else:
        decision = REJECT

    h.novelty, h.feasibility = nov, fea
    h.passed_gate = (decision == PASS)

    rationale = (
        f"novelty={nov:.1f}(≥{rubric.novelty_threshold_pass}) "
        f"feasibility={fea:.1f}(≥{rubric.feasibility_threshold_pass}) → {decision}"
    )
    return EvalResult(novelty=nov, feasibility=fea, decision=decision, rationale=rationale)


def gate_report(results: List[EvalResult]) -> dict:
    """对一批候选假设给出剪枝统计（对应 FARS peer discussion 的 early pruning）。"""
    n = len(results)
    passed = sum(1 for r in results if r.decision == PASS)
    revised = sum(1 for r in results if r.decision == REVISE)
    rejected = sum(1 for r in results if r.decision == REJECT)
    return {
        "total": n, "pass": passed, "revise": revised, "reject": rejected,
        "pass_rate": round(passed / n, 3) if n else 0.0,
    }


__all__ = [
    "EvalRubric", "EvalResult", "PASS", "REVISE", "REJECT",
    "evaluate", "gate_report",
]

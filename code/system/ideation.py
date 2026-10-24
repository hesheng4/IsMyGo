"""模块① Ideation（构思）：文献调研 + 假设生成 + 双维评估门控。

对齐 FARS：Ideation 内部六阶段（文献→候选方向→peer discussion 剪枝→提案→
修订循环→定稿），本模块以「LLM 生成假设 + hypothesis_eval 双维门控」落地，
把 FARS 的 Peer Discussion Agent 剪枝弱想法显式化为可审计阈值。

LLM 层兼容 openJiuwen SwarmFlow（swarmflow.agent），import 惰性化以便离线 import。
本地/可复现路径可用 injected llm callable 驱动（便于测试与无网运行）。
"""
from __future__ import annotations

from typing import Callable, Optional

from .contracts import IdeationInput, Hypothesis
from . import hypothesis_eval as he


def build_prompt(inp: IdeationInput) -> str:
    return (
        "你是科研构思研究员。围绕研究主题「{topic}」，方向限定为「{direction}」，"
        "检索最新文献，提出 1 个可验证、有创新点的研究假设，并给出支撑依据。\n"
        "【主张可实证纪律】假设中每个方法模块（如滑窗/检索/压缩/分层）都必须"
        "可独立实验验证；优越性比较对象只能是同等预算约束下的策略，"
        "无预算上界的基线只能作 oracle 上界参照。\n"
        "【相关工作定位】references 至少 5 个近邻系统（系统名+年份+差异一句话），"
        "并指出本研究相对它们的缺口。\n"
        "请返回 JSON：{{\"hypothesis\":..., \"rationale\":..., "
        "\"modules\":[...], \"references\":[...]}}"
    ).format(topic=inp.topic, direction=inp.direction)


def parse_hypothesis(text: str) -> Hypothesis:
    import json, re
    if not text:
        return Hypothesis(statement="", rationale="", modules=[], references=[])
    try:
        data = json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return Hypothesis(statement=text, rationale="", modules=[], references=[])
        try:
            data = json.loads(m.group(0))
        except Exception:
            return Hypothesis(statement=text, rationale="", modules=[], references=[])
    if not isinstance(data, dict):
        return Hypothesis(statement=text, rationale="", modules=[], references=[])
    return Hypothesis(
        statement=str(data.get("hypothesis", text)),
        rationale=str(data.get("rationale", "")),
        modules=list(data.get("modules", []) or []),
        references=list(data.get("references", []) or []),
        raw=text,
    )


def execute(inp: IdeationInput, llm: Optional[Callable[[str], str]] = None,
            rubric: Optional[he.EvalRubric] = None) -> Hypothesis:
    """执行构思：LLM 生成假设 → 解析 → 双维评估门控。

    llm: 注入的 prompt→text 函数（本地测试用）；缺省尝试 SwarmFlow agent。
    """
    text = ""
    if llm:
        text = llm(build_prompt(inp))
    else:
        try:
            from swarmflow import agent, phase  # 惰性导入：仅在引擎内可用
            import asyncio
            async def _call():
                return await agent(build_prompt(inp), label="ideation", phase="ideation")
            text = asyncio.run(_call())
        except Exception as e:  # 引擎外或无 LLM：返回空假设，交由门控判 REJECT
            hyp = Hypothesis(statement="", rationale=f"ideation LLM 不可用: {e}",
                             modules=[], references=[])
            res = he.evaluate(hyp, rubric=rubric)
            hyp.passed_gate = False
            return hyp
    hyp = parse_hypothesis(text)
    # 双维评估门控（FARS 优化②）
    res = he.evaluate(hyp, rubric=rubric, n_refs_with_diff=len(hyp.references))
    hyp.passed_gate = res.decision == he.PASS
    return hyp


__all__ = ["build_prompt", "parse_hypothesis", "execute"]

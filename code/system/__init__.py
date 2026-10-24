"""openJiuwen 科研短论文自动生成系统（FARS 架构对齐）。

四模块：Ideation / Planning / Experiment / Writing，经共享工作区（文件系统）
以机读契约（contracts.py 的 dataclass）传递；调度层（scheduler.py）提供
队列式并行 + 优先级 + 重试 + 降级；FARS 三项优化见
context_cache / hypothesis_eval / causal_analysis。

LLM 多智能体层（ideation/planning/experiment/writing）基于已验证的
research_pipeline_v5.py 模式，兼容 openJiuwen SwarmFlow（swarmflow facade）。
确定性渲染层（paper_builder / charts / causal_analysis）不依赖 LLM，
从 results.json 抽取真实数值，从根本消除幻觉（Task #15 修复）。
"""
from __future__ import annotations

from .contracts import (  # noqa: F401
    Phase, TaskStatus, IdeationInput, Hypothesis, ExperimentItem, ExperimentPlan,
    ExperimentEvidence, Manuscript, Task,
)

__all__ = ["Phase", "TaskStatus", "IdeationInput", "Hypothesis", "ExperimentItem",
           "ExperimentPlan", "ExperimentEvidence", "Manuscript", "Task"]

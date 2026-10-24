"""系统模块契约（I/O 数据结构）与状态定义。

本文件是 openJiuwen 科研短论文自动生成系统的「接口层」：
- 四个核心模块的 输入/输出 全部以强类型 dataclass 声明（FARS 的 machine-readable
  experiment contract 思想），模块间只通过这些契约传递数据，互不依赖内部实现。
- Phase 状态机 + TaskStatus 定义全局流转与异常状态，供 scheduler 调度与降级使用。

参考：FARS (arXiv:2606.31651) 四阶段（Ideation/Planning/Experiment/Writing）
经共享工作区（shared workspace）以机读实验契约传递；本系统将契约显式化为 dataclass。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# 状态机
# ─────────────────────────────────────────────────────────────────────────────
class Phase(str, Enum):
    """四模块主状态（对应 FARS 四阶段）。"""
    IDEATION = "ideation"
    PLANNING = "planning"
    EXPERIMENT = "experiment"
    WRITING = "writing"
    DONE = "done"
    FAILED = "failed"


class TaskStatus(str, Enum):
    """调度器可见的任务级状态（含重试/降级/熔断）。"""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    DEGRADED = "degraded"      # 经缓存/降级路径成功，非全量执行
    CIRCUIT_OPEN = "circuit_open"  # 熔断器开启，跳过执行
    CANCELLED = "cancelled"


# 合法状态流转（scheduler 校验用）
ALLOWED_TRANSITIONS: Dict[TaskStatus, List[TaskStatus]] = {
    TaskStatus.QUEUED: [TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.CIRCUIT_OPEN],
    TaskStatus.RUNNING: [TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.RETRYING, TaskStatus.DEGRADED],
    TaskStatus.RETRYING: [TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.DEGRADED],
    TaskStatus.FAILED: [TaskStatus.QUEUED, TaskStatus.CANCELLED],
    TaskStatus.DEGRADED: [TaskStatus.SUCCEEDED],
    TaskStatus.CIRCUIT_OPEN: [TaskStatus.QUEUED, TaskStatus.DEGRADED],
    TaskStatus.SUCCEEDED: [],
    TaskStatus.CANCELLED: [],
}


def build_gate_router(decide, pass_target: str, reject_target: str, pass_value: str = "pass"):
    """把「门控决策」编成 agent-core 的 BranchRouter（复用 core.workflow 条件路由）。

    这是状态机允许转换在编排期的映射点：PASS 走 pass_target（如 writing），
    其余（REVISE/REJECT）走 reject_target。仅 agent-core 后端编排用；
    函数体内懒 import openjiuwen，故本模块仍可纯标准库导入。

    decide: 返回门控决策字符串的可调用（如 hypothesis_eval 决策 "pass"/"revise"/"reject"）。
    返回 openjiuwen BranchRouter；openjiuwen 不可用时抛 ImportError（调用方回退 stdlib）。
    """
    from openjiuwen.core.workflow import BranchRouter, FuncCondition

    router = BranchRouter()
    router.add_branch(FuncCondition(lambda: decide() == pass_value),
                      [pass_target], branch_id="gate_pass")
    router.add_branch(FuncCondition(lambda: decide() != pass_value),
                      [reject_target], branch_id="gate_reject")
    return router


# ─────────────────────────────────────────────────────────────────────────────
# Ideation 模块
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class IdeationInput:
    """选题输入。direction 限定选题方向（赛题三允许三选一）。"""
    topic: str
    direction: str = "memory_engine"   # context_engineering | memory_engine | self_evolution
    constraints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Hypothesis:
    """构思产出：一个可验证假设 + 支撑依据 + 方法模块 + 文献。

    novelty / feasibility 由 hypothesis_eval 双维评估填充（FARS 优化点②）。
    """
    statement: str
    rationale: str
    modules: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
    novelty: float = 0.0           # 创新性 0–10
    feasibility: float = 0.0       # 可行性 0–10
    passed_gate: bool = False      # 是否通过准入门控
    raw: str = ""                  # 原始 agent 文本（用于审计/缓存）


# ─────────────────────────────────────────────────────────────────────────────
# Planning 模块
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ExperimentItem:
    """FARS 实验契约的原子单元——五类任务之一，含有序步骤。

    五类（FARS §3.3）：environment_config / baseline / main /
    effectiveness_eval / analysis。
    """
    category: str            # 上述五类之一
    name: str
    steps: List[str] = field(default_factory=list)
    order: int = 0
    depends_on: List[str] = field(default_factory=list)


@dataclass
class ExperimentPlan:
    """规划产出：机读实验契约。

    编码研究的证据结构（FARS：先环境、再基线、再主实验、有效性评估门控、
    最后分析实验）。module_map 实现 W1「模块→实验策略」硬映射。
    """
    hypothesis: str
    module_map: Dict[str, str] = field(default_factory=dict)  # 模块→实验策略/消融
    items: List[ExperimentItem] = field(default_factory=list)
    baselines: List[str] = field(default_factory=list)
    metrics: List[str] = field(default_factory=list)
    seeds: List[int] = field(default_factory=list)
    budgets: List[int] = field(default_factory=list)
    stat_scheme: str = ""
    raw: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Experiment 模块
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ExperimentEvidence:
    """实验产出：唯一事实基准（results.json）的封装 + 可程序化引用的摘要。

    writing 模块只从此处取数，杜绝「模型转述」导致的幻觉（FARS 审计性要求）。
    """
    results_json_path: str
    summary: str
    tables: Dict[str, Any] = field(default_factory=dict)
    negative_results: List[str] = field(default_factory=list)
    passed_effectiveness: bool = False   # 有效性评估门控是否通过
    raw: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Writing 模块
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Manuscript:
    """写作产出：ICLR 短论文。

    sections 按 ICLR 结构分区；figures/tables 指向确定性生成的产物路径，
    由 paper_builder 从 results.json 抽取真实数值渲染（零幻觉）。
    """
    sections: Dict[str, str] = field(default_factory=dict)
    figures: List[str] = field(default_factory=list)
    tables: List[str] = field(default_factory=list)
    full_text: str = ""
    path: str = ""
    raw: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# 调度任务
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Task:
    """队列任务单元：含优先级、重试策略引用、状态。"""
    task_id: str
    phase: Phase
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: int = 5            # 数字越大越优先
    status: TaskStatus = TaskStatus.QUEUED
    attempts: int = 0
    max_attempts: int = 3
    depends_on: List[str] = field(default_factory=list)
    result: Optional[Any] = None
    error: str = ""
    degraded: bool = False


__all__ = [
    "Phase", "TaskStatus", "ALLOWED_TRANSITIONS", "build_gate_router",
    "IdeationInput", "Hypothesis",
    "ExperimentItem", "ExperimentPlan",
    "ExperimentEvidence", "Manuscript", "Task",
]

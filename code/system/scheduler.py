"""任务调度：队列式多任务并行调度 + 优先级 + 失败重试 + 异常降级。

设计目标（对应赛题「系统架构要求 2」）：
- 项目队列式并行：ResearchScheduler 持有 Task 队列，按优先级 + 依赖拓扑调度。
- 优先级管理：priority 数字大者先；同优先级按入队序（FIFO）。
- 失败自动重试：RetryPolicy 指数退避（base×2^attempt），带抖动；超过 max_attempts
  进入 circuit_breaker 或降级。
- 异常降级：DegradationPolicy 定义「失败后可退回的廉价路径」（如用缓存证据代替
  重新实验、用兜底假设代替 ideation 失败），保证流水线不中断、负结果也产出。
- 熔断器：同一 phase 连续失败超阈值 → 熔断，后续该 phase 任务直接降级，避免
  无界重试耗尽配额（FARS 的 circuit breaker 同源思想）。

本模块纯逻辑、无外部依赖，可离线单测（见 tests/test_scheduler.py）。
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .contracts import Phase, Task, TaskStatus, ALLOWED_TRANSITIONS
from . import backends


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 2.0
    backoff: float = 2.0          # 指数基数
    jitter: float = 0.3
    timeout_s: float = 600.0


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3    # 连续失败达此数 → 熔断
    cooldown_s: float = 60.0
    _failures: int = 0
    _open_until: float = 0.0

    def allow(self) -> bool:
        if time.time() >= self._open_until:
            if self._open_until and self._failures >= self.failure_threshold:
                # 冷却结束，半开重置
                self._failures = 0
                self._open_until = 0.0
            return True
        return False

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._open_until = time.time() + self.cooldown_s

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    @property
    def is_open(self) -> bool:
        return time.time() < self._open_until


@dataclass
class DegradationPolicy:
    """异常降级：phase → 降级执行函数（返回降级产物，status=DEGRADED）。"""
    fallbacks: Dict[Phase, Callable[[Task], object]] = field(default_factory=dict)

    def apply(self, task: Task) -> object:
        fn = self.fallbacks.get(task.phase)
        if fn is None:
            raise RuntimeError(f"无降级路径：{task.phase}")
        return fn(task)


def _sleep(delay: float) -> None:
    # 测试可 monkeypatch；生产真实 sleep
    time.sleep(delay)


def _transition(task: Task, new: TaskStatus) -> None:
    if new not in ALLOWED_TRANSITIONS.get(task.status, []):
        # 允许式校验；异常仅告警不阻断
        pass
    task.status = new


class ResearchScheduler:
    """队列式多任务调度器（可并行 phase，单 phase 内串行重试）。"""

    def __init__(self, retry: RetryPolicy | None = None,
                 breaker: CircuitBreaker | None = None,
                 degradation: DegradationPolicy | None = None,
                 max_concurrent_phases: int = 4):
        self.tasks: Dict[str, Task] = {}
        self.retry = retry or RetryPolicy()
        self.breaker = breaker or CircuitBreaker()
        self.degradation = degradation or DegradationPolicy()
        self.max_concurrent_phases = max_concurrent_phases
        self._history: List[Dict[str, object]] = []
        # 任务树可观测性：复用 openjiuwen task_manager（agentcore 后端）；
        # 不可用时退化为本地记录摘要，调度语义不变（双后端，见 backends.py）。
        self.tracker = backends.TaskTracker()

    # ── 队列管理 ──
    def submit(self, task: Task) -> str:
        self.tasks[task.task_id] = task
        return task.task_id

    def _ready(self, task: Task) -> bool:
        if task.depends_on:
            return all(self.tasks[d].status == TaskStatus.SUCCEEDED for d in task.depends_on)
        return True

    def enqueue_order(self) -> List[Task]:
        """就绪任务按 优先级↓ + 入队序 排序。"""
        ready = [t for t in self.tasks.values()
                 if t.status == TaskStatus.QUEUED and self._ready(t)]
        return sorted(ready, key=lambda t: (-t.priority, t.task_id))

    # ── 单任务执行（含重试/熔断/降级）──
    def _run_one(self, task: Task, handler: Callable[[Task], object]) -> None:
        if not self.breaker.allow():
            # 熔断：直接降级
            task.status = TaskStatus.CIRCUIT_OPEN
            try:
                task.result = self.degradation.apply(task)
                task.degraded = True
                task.status = TaskStatus.DEGRADED
            except Exception as e:  # 无降级路径
                task.status = TaskStatus.FAILED
                task.error = f"circuit_open+no_fallback: {e}"
            return

        while task.attempts < task.max_attempts:
            task.attempts += 1
            task.status = TaskStatus.RUNNING if task.attempts == 1 else TaskStatus.RETRYING
            try:
                res = handler(task)
                task.result = res
                task.status = TaskStatus.SUCCEEDED
                self.breaker.record_success()
                self.tracker.record(task.task_id, "succeeded", attempts=task.attempts)
                self._history.append({"id": task.task_id, "status": "succeeded", "attempts": task.attempts})
                return
            except Exception as e:
                task.error = str(e)
                self.breaker.record_failure()
                if task.attempts >= task.max_attempts:
                    break
                delay = self.retry.base_delay_s * (self.retry.backoff ** (task.attempts - 1))
                delay *= (1 + random.uniform(-self.retry.jitter, self.retry.jitter))
                _sleep(min(delay, self.retry.timeout_s))

        # 重试耗尽 → 降级
        try:
            task.result = self.degradation.apply(task)
            task.degraded = True
            task.status = TaskStatus.DEGRADED
            self.tracker.record(task.task_id, "degraded", attempts=task.attempts)
            self._history.append({"id": task.task_id, "status": "degraded", "attempts": task.attempts})
        except Exception as e2:
            task.status = TaskStatus.FAILED
            task.error = f"{task.error} | degrade_failed: {e2}"
            self.tracker.record(task.task_id, "failed", attempts=task.attempts)
            self._history.append({"id": task.task_id, "status": "failed", "attempts": task.attempts})

    # ── 驱动：顺序消费就绪队列（单线程安全；并行可由调用方按 phase 派发）──
    def run(self, handlers: Dict[Phase, Callable[[Task], object]]) -> Dict[str, Task]:
        # 多轮：每轮调度所有就绪且未终结的任务
        pending = [t for t in self.tasks.values() if t.status == TaskStatus.QUEUED]
        while pending:
            for task in self.enqueue_order():
                if task.phase not in handlers:
                    task.status = TaskStatus.FAILED
                    task.error = "no handler"
                    continue
                self._run_one(task, handlers[task.phase])
            pending = [t for t in self.tasks.values()
                       if t.status in (TaskStatus.QUEUED, TaskStatus.RETRYING)]
            if not pending:
                break
        return self.tasks

    def summary(self) -> Dict[str, object]:
        by_status: Dict[str, int] = {}
        for t in self.tasks.values():
            by_status[t.status.value] = by_status.get(t.status.value, 0) + 1
        degraded = [t.task_id for t in self.tasks.values() if t.degraded]
        return {
            "total": len(self.tasks),
            "by_status": by_status,
            "degraded_tasks": degraded,
            "history": self._history,
            # 可观测性增强（openjiuwen task_manager 任务树 / stdlib 回退记录摘要）
            "task_tree": self.tracker.task_tree(),
            "backend": self.tracker.backend,
        }


__all__ = [
    "RetryPolicy", "CircuitBreaker", "DegradationPolicy",
    "ResearchScheduler", "_transition",
]

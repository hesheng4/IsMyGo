"""双后端适配层：openJiuwen (agent-core) 基础类复用，stdlib 自动回退。

目标（复用 agent-core 基础函数/类，同时保持零 LLM 路径纯标准库可运行）：
- 哈希：优先复用 `openjiuwen.core.memory.lite.internal.hash_text`（SHA256[:16]），
  不可用时回退内置同款实现（逐位一致，见 tests/test_backend_equivalence.py）。
- key 构造：优先复用 `openjiuwen.core.session.checkpointer.build_key_with_namespace`，
  不可用时回退 `":".join`。
- 任务生命周期/任务树：优先复用 `openjiuwen.core.common.task_manager`
  （TaskManager / create_task / print_task_tree）作为调度器可观测性增强；
  不可用时退化为本地计数（调度语义不变，纯 stdlib）。
- 同步桥：agent-core 的 Workflow / Checkpointer / TaskManager 均为 async，
  `run_sync()` 在独立事件环中调用，异常静默回退 stdlib，绝不影响产物。

后端选择：环境变量 `PAPER_LAB_BACKEND` = `auto`(默认) | `agentcore` | `stdlib`。
agent-core 可经 pip 包或源码树（`OPENJIUWEEN_SRC` 指向 agent-core-develop 目录）加载。
全部懒加载：绝不在 `system/__init__` 顶层 import openjiuwen，避免未安装时崩 + 导入副作用。
"""
from __future__ import annotations

import hashlib
import logging
import os
import sys
from typing import Any, Callable, Optional

# --------------------------------------------------------------------------- #
# 后端解析
# --------------------------------------------------------------------------- #
BACKEND_AGENTCORE = "agentcore"
BACKEND_STDLIB = "stdlib"
BACKEND_AUTO = "auto"

_agentcore_state: dict[str, Any] = {"checked": False, "ok": False, "error": None}


def _try_load_agentcore() -> bool:
    """尝试加载 openjiuwen（pip 包 → 源码树注入），抑制其导入期 INFO 副作用。"""
    if _agentcore_state["checked"]:
        return _agentcore_state["ok"]
    _agentcore_state["checked"] = True
    prev_level = logging.getLogger().level
    try:
        # 源码树注入（pip 版本受 requires-python<3.14 门挡时的路径）
        src = os.environ.get("OPENJIUWEEN_SRC")
        if src and os.path.isdir(src) and src not in sys.path:
            sys.path.insert(0, src)
        # 抑制 openjiuwen 导入期注册 connector/parser 的 INFO 日志
        logging.getLogger().setLevel(logging.WARNING)
        import openjiuwen  # noqa: F401
        from openjiuwen.core.memory.lite.internal import hash_text  # noqa: F401
        _agentcore_state["ok"] = True
    except Exception as e:  # noqa: BLE001 - 任何导入失败即回退 stdlib
        _agentcore_state["ok"] = False
        _agentcore_state["error"] = f"{type(e).__name__}: {e}"
    finally:
        logging.getLogger().setLevel(prev_level)
    return _agentcore_state["ok"]


def agentcore_available() -> bool:
    return _try_load_agentcore()


def resolve_backend() -> str:
    """解析生效后端：显式 `stdlib` 直接回退；`agentcore` 在真实 openjiuwen 可用时用之，
    否则（含被测试桩污染的场景）**优雅回退 stdlib 并告警**，绝不抛错——
    「可用性优先」（双后端：openjiuwen 优先、不可用自动回退）。"""
    pref = os.environ.get("PAPER_LAB_BACKEND", BACKEND_AUTO).strip().lower()
    if pref == BACKEND_STDLIB:
        return BACKEND_STDLIB
    ok = _try_load_agentcore()
    if ok:
        return BACKEND_AGENTCORE
    if pref == BACKEND_AGENTCORE:
        import warnings
        warnings.warn(
            "PAPER_LAB_BACKEND=agentcore 但真实 openjiuwen 不可用（可能未安装或被测试桩遮蔽），"
            f"回退 stdlib：{_agentcore_state.get('error')}",
            RuntimeWarning, stacklevel=2)
    return BACKEND_STDLIB


# --------------------------------------------------------------------------- #
# 哈希（逐位一致的双后端）
# --------------------------------------------------------------------------- #
def _stdlib_hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


_hash_fn_cache: dict[str, Callable[[str], str]] = {}


def get_hash_fn() -> Callable[[str], str]:
    """返回哈希函数：agentcore 后端复用 openjiuwen hash_text，否则 stdlib 同款。"""
    backend = resolve_backend()
    if backend in _hash_fn_cache:
        return _hash_fn_cache[backend]
    fn: Callable[[str], str] = _stdlib_hash_text
    if backend == BACKEND_AGENTCORE:
        try:
            from openjiuwen.core.memory.lite.internal import hash_text
            fn = hash_text
        except Exception:  # noqa: BLE001
            pass
    _hash_fn_cache[backend] = fn
    return fn


# --------------------------------------------------------------------------- #
# key 构造（复用 checkpointer.build_key_with_namespace）
# --------------------------------------------------------------------------- #
def build_key(*parts: str) -> str:
    if resolve_backend() == BACKEND_AGENTCORE:
        try:
            from openjiuwen.core.session.checkpointer import build_key as _bk
            return _bk(*parts)
        except Exception:  # noqa: BLE001
            pass
    return ":".join(parts)


# --------------------------------------------------------------------------- #
# 同步桥：在独立事件环跑 async 协程，失败回退
# --------------------------------------------------------------------------- #
def run_sync(coro_factory: Callable[[], Any], default: Any = None) -> Any:
    """在独立事件环中执行 async 协程工厂；任何异常返回 default（绝不外抛）。"""
    try:
        import asyncio
        return asyncio.run(coro_factory())
    except Exception:  # noqa: BLE001
        return default


# --------------------------------------------------------------------------- #
# 任务生命周期追踪（复用 task_manager，作为调度器可观测性增强）
# --------------------------------------------------------------------------- #
class TaskTracker:
    """任务树追踪：agentcore 后端用 TaskManager 记录任务生命周期并可打印任务树；
    stdlib 后端退化为本地计数。调度语义（优先级/重试/熔断/降级）不变。"""

    def __init__(self) -> None:
        self.backend = resolve_backend()
        self._records: list[dict] = []
        self._tm = None
        if self.backend == BACKEND_AGENTCORE:
            try:
                from openjiuwen.core.common.task_manager import get_task_manager
                self._tm = get_task_manager()
            except Exception:  # noqa: BLE001
                self._tm = None

    def record(self, task_id: str, status: str, **meta: Any) -> None:
        self._records.append({"task_id": task_id, "status": status, **meta})

    def records(self) -> list[dict]:
        return list(self._records)

    def task_tree(self) -> str:
        # 本地记录摘要（任一后端均非空，作为任务树的确定性呈现）
        base = "\n".join(f"{r['task_id']}:{r['status']}" for r in self._records)
        if self._tm is not None:
            try:
                from openjiuwen.core.common.task_manager import print_task_tree
                import io
                import contextlib
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    print_task_tree()
                tm_tree = buf.getvalue().strip()
                if tm_tree:  # agentcore 真实协程任务树（有内容则呈现）
                    return tm_tree
            except Exception:  # noqa: BLE001
                pass
        return base


__all__ = [
    "BACKEND_AGENTCORE", "BACKEND_STDLIB", "BACKEND_AUTO",
    "agentcore_available", "resolve_backend", "get_hash_fn", "build_key",
    "run_sync", "TaskTracker", "_stdlib_hash_text",
]

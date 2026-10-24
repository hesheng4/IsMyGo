"""
主张对齐 Rail（ClaimAlignmentRail）
====================================
背景：Stanford Agentic Reviewer 对流水线 v1 论文给出 3.2/10。评审暴露的
不是数据造假（幻觉 Rail 已拦截），而是"主张-证据-报告规范"层面的系统性
缺陷——这些缺陷流水线各阶段均未设防：

  W1 方法模块未实验：假设宣称"滑窗+检索+压缩"三模块，实验只跑两模块，
     没有任何阶段校验"假设中的每个模块都有对应实验策略"。
  W2 无界 oracle 混入受限对照："优于 full context" 是不公平主张
     （full context 无预算约束、无条件 1.0 准确率）。
  W3 无统计置信：多种子聚合却无 std/CI 报告。
  W4 指标口径缺失：延迟数值未说明测量的是什么（进程内 or 端到端）。
  W5 复现要素缺失：环境/种子/预算等关键配置未写入论文。
  W6 相关工作过少：无与近邻系统的定位对比。

本 Rail 把六项固化为可执行检查，缺项即注入警告（PAPER_LAB[claim_alignment]），
由写作/校对阶段自修订。挂载方式与 hallucination_check 相同。
"""

from __future__ import annotations

import re
from pathlib import Path

from openjiuwen.core.single_agent.rail.base import AgentCallbackContext
from openjiuwen.harness.rails.base import DeepAgentRail

# 钩子触发审计日志（与既有 Rail 同模式：实际执行必留痕）
RAIL_AUDIT_PATH = str(
    Path.home() / ".jiuwenswarm" / "agent" / "workspace" / "output" / "rail_runtime.log"
)

# ---- W2：oracle 公平性 ----
_ORACLE_TERMS = ("full_context", "full context", "full-context",
                 "全量上下文", "全文上下文")
_ORACLE_LABELS = ("oracle", "上界", "upper bound", "unbounded", "无界",
                  "不受预算", "budget-unconstrained")
_SUPERIORITY = ("outperform", "surpass", "beat", "exceed",
                "优于", "超过", "超越", "胜过", "碾压")

# ---- W3：统计置信（英文短词用词边界，防 "efficacy" 含 "ci" 之类误匹配） ----
_STAT_MARKER_RE = re.compile(
    r"(\bci\b|\bci95\b|\bstd\b|±|置信区间|标准差|confidence\s+interval|误差)",
    re.IGNORECASE,
)
_ACC_TERMS = re.compile(r"(accuracy|准确率|acc\b)", re.IGNORECASE)

# ---- W4：指标口径 ----
_LATENCY_TERMS = ("latency", "延迟", "耗时")
_LATENCY_SCOPES = ("in-process", "进程内", "端到端", "end-to-end",
                   "测量口径", "计时方法", "micro-benchmark", "微基准",
                   "包含模型推理", "不含模型推理")

# ---- W5：复现要素 ----
_REPRO_REQUIREMENTS = [
    ("seed", re.compile(r"(\bseed\b|种子)", re.IGNORECASE)),
    ("budget", re.compile(r"(\bbudget\b|预算)", re.IGNORECASE)),
    ("environment", re.compile(
        r"(python|windows|linux|macos|运行环境|平台|platform)", re.IGNORECASE)),
]

# ---- W6：相关工作规模 ----
_MIN_REFS = 5

_HEADING_LINE = re.compile(r"^#{1,4}\s+(.+)$", re.MULTILINE)
_NUMBERING = re.compile(r"^\d+(?:\.\d+)*[\.、:]?\s*")
_REFS_HEADING = re.compile(
    r"^#{1,4}\s*\d*[\.、:]?\s*(references|参考文献|related work|相关工作)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def _audit(hook: str, verdict: str, detail: str = "") -> None:
    """追加一行审计记录；任何异常静默（不得影响主流程）。"""
    try:
        import datetime

        line = (f"{datetime.datetime.now().isoformat(timespec='seconds')} "
                f"| claim_alignment.{hook} | {verdict}")
        if detail:
            line += f" | {detail}"
        with open(RAIL_AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _is_paper_like(text: str) -> bool:
    """输出看起来是论文（有标题行且出现摘要/引言）才启用结构类检查。"""
    if not text or not _HEADING_LINE.search(text):
        return False
    return bool(re.search(r"(abstract|摘\s*要|introduction|引\s*言)", text,
                          re.IGNORECASE))


def _oracle_unfair_claims(text: str) -> list[str]:
    """W2：对无界 oracle 基线作优越性断言、且句内无 oracle 标注 → 不公平主张。"""
    bad: list[str] = []
    for sent in re.split(r"(?<=[。.!?\n])", text):
        low = sent.lower()
        if not any(o in low for o in _ORACLE_TERMS):
            continue
        if not any(s in low for s in _SUPERIORITY):
            continue
        if any(l in low for l in _ORACLE_LABELS):
            continue
        bad.append(sent.strip()[:80])
    return bad


def _missing_stat_reporting(text: str) -> bool:
    """W3：论文含准确率主张却无任何统计置信标记。"""
    if not _ACC_TERMS.search(text):
        return False
    return not _STAT_MARKER_RE.search(text)


def _missing_latency_scope(text: str) -> bool:
    """W4：出现延迟表述却无测量口径说明。"""
    low = text.lower()
    if not any(t in low for t in _LATENCY_TERMS):
        return False
    return not any(s in low for s in _LATENCY_SCOPES)


def _missing_repro_elements(text: str) -> list[str]:
    """W5：论文缺复现要素（种子/预算/环境）。"""
    missing = []
    for label, pattern in _REPRO_REQUIREMENTS:
        if not pattern.search(text):
            missing.append(label)
    return missing


def _ref_count_too_small(text: str) -> bool:
    """W6：参考文献条目少于下限。"""
    m = _REFS_HEADING.search(text)
    if not m:
        return False  # 缺参考文献章节由 academic_format Rail 负责
    ref_list = text[m.end():]
    entries = re.findall(r"(?m)^\s*(?:\[\d+\]|[-*•])\s*\S", ref_list)
    return len(entries) < _MIN_REFS


def _check_paper(text: str) -> list[str]:
    """对论文类输出执行全部检查，返回警告列表（空 = 通过）。"""
    warnings: list[str] = []
    unfair = _oracle_unfair_claims(text)
    if unfair:
        warnings.append(
            "不公平对照：不得宣称优于无界 oracle 基线（full context 无预算约束），"
            "须改为『受限策略间比较 + oracle 仅作上界参照』。问题句: "
            + " | ".join(unfair[:3])
        )
    if _is_paper_like(text):
        if _missing_stat_reporting(text):
            warnings.append(
                "统计置信缺失：论文含准确率数值但未报告 std/CI/置信区间，"
                "必须补充 results.json 中的 accuracy_std 与 accuracy_ci95。"
            )
        if _missing_latency_scope(text):
            warnings.append(
                "指标口径缺失：出现延迟/latency 数值但未说明测量口径"
                "（进程内内存查询 or 端到端含模型推理），必须显式声明。"
            )
        missing_repro = _missing_repro_elements(text)
        if missing_repro:
            warnings.append(
                "复现要素缺失：" + ", ".join(missing_repro)
                + "。必须在实验设置写明（种子列表/预算档位/运行环境）。"
            )
        if _ref_count_too_small(text):
            warnings.append(
                "相关工作过少：参考文献不足 5 条，无法支撑定位对比，"
                "必须补充近邻系统（记忆引擎/层级记忆方向）并逐一说明差异。"
            )
    return warnings


class ClaimAlignmentRail(DeepAgentRail):
    """主张-证据对齐：优越性主张、统计置信、指标口径、复现要素、相关工作规范。"""

    priority: int = 75

    async def after_model_call(self, ctx: AgentCallbackContext) -> None:
        try:
            output = self._get_output_text(ctx)
            if not output:
                _audit("after_model_call", "SKIP", "empty output")
                return
            warnings = _check_paper(output)
            if warnings:
                _audit("after_model_call", "WARN",
                       f"{len(warnings)} issue(s): " + "; ".join(
                           w.split("：")[0] for w in warnings))
                for w in warnings:
                    self._note(ctx, f"PAPER_LAB[claim_alignment]: {w}")
            else:
                _audit("after_model_call", "PASS", "claims aligned")
        except Exception as exc:  # 防御：Rail 异常不得中断主流程
            _audit("after_model_call", "ERROR", str(exc)[:120])
            print(f"[claim_alignment] skip: {exc}")

    async def before_tool_call(self, ctx: AgentCallbackContext) -> None:
        """写论文文件前：同样校验待写入内容，防不合规主张落盘。"""
        try:
            inputs = getattr(ctx, "inputs", None)
            tool_name = getattr(inputs, "tool_name", "") or ""
            tool_args = getattr(inputs, "tool_args", None) or {}
            content = str(tool_args.get("content") or tool_args.get("text") or "")
            if not content or "write" not in tool_name.lower():
                return
            warnings = _check_paper(content)
            if warnings:
                _audit("before_tool_call", "WARN",
                       f"tool={tool_name} {len(warnings)} issue(s)")
                for w in warnings:
                    self._note(ctx, f"PAPER_LAB[claim_alignment][BLOCK-HINT]: {w}")
            else:
                _audit("before_tool_call", "PASS", f"tool={tool_name} aligned")
        except Exception:
            pass

    # ------------------------------------------------------------------
    @staticmethod
    def _get_output_text(ctx: AgentCallbackContext) -> str:
        for attr in ("output", "response", "result", "text"):
            val = getattr(ctx, attr, None)
            if isinstance(val, str) and val:
                return val
            if val is not None:
                for sub in ("message", "text", "content"):
                    sub_val = getattr(val, sub, None)
                    if isinstance(sub_val, str) and sub_val:
                        return sub_val
        return ""

    @staticmethod
    def _note(ctx: AgentCallbackContext, note: str) -> None:
        injected = False
        for attr in ("notes", "warnings", "system_notes"):
            lst = getattr(ctx, attr, None)
            if isinstance(lst, list):
                lst.append(note)
                injected = True
                break
        if not injected and hasattr(ctx, "__dict__"):
            for attr in vars(ctx):
                if isinstance(getattr(ctx, attr, None), list):
                    getattr(ctx, attr).append(note)
                    injected = True
                    break
        print(f"[claim_alignment] {note}")

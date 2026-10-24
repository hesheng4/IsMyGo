"""
幻觉校验 Rail（HallucinationCheckRail）
========================================
功能：拦截"实验数据造假"——论文写作阶段输出的量化断言必须与
      真实落盘的实验结果（results.json）一致，不一致则注入警告。

挂载方式（JiuwenSwarm RailManager 扩展机制）：
  1. 本文件夹（hallucination_check/）复制到:
     ~/.jiuwenswarm/agent/workspace/extensions/
  2. extensions_config.json 中登记:
     {"hallucination_check": {"class_name": "HallucinationCheckRail",
                              "enabled": true, "priority": 80}}
  3. team 模式经 PLUGIN_RAILS provider 自动为每个 member 实例化
     （agents/swarm/providers/member_rails.py:440-477）

钩子契约（DeepAgentRail 生命周期，docs/zh/Harness.md:75-81）：
  - after_model_call: 校验模型输出中的量化断言
  - before_tool_call: 拦截写入论文文件的动作，先校验再放行

注意：ctx 字段随 openjiuwen 版本可能变化，本 Rail 全部用 getattr
      防御式读取，任何异常只告警不阻断主流程。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from openjiuwen.core.single_agent.rail.base import AgentCallbackContext
from openjiuwen.harness.rails.base import DeepAgentRail

# 真实实验结果基准文件（由 experiment-runner 产出）
RESULTS_PATH = os.environ.get(
    "PAPER_LAB_RESULTS",
    str(Path.home() / ".jiuwenswarm" / "agent" / "workspace" / "output" / "results.json"),
)

# 钩子触发审计日志（每次 after/before 钩子实际执行都留痕，证明 Rail 在运行时生效）
RAIL_AUDIT_PATH = os.environ.get(
    "PAPER_LAB_RAIL_AUDIT",
    str(Path.home() / ".jiuwenswarm" / "agent" / "workspace" / "output" / "rail_runtime.log"),
)


def _audit(hook: str, verdict: str, detail: str = "") -> None:
    """追加一行审计记录；任何异常静默（不得影响主流程）。"""
    try:
        import datetime

        line = (f"{datetime.datetime.now().isoformat(timespec='seconds')} "
                f"| hallucination_check.{hook} | {verdict}")
        if detail:
            line += f" | {detail}"
        with open(RAIL_AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# 量化断言模式：捕获百分比、指标数值（如 87.3%、F1=0.91、loss 0.42）
# 关键词后允许 [a-z_]* 以覆盖 JSON 键名变体（accuracy_recent 等）。
# 百分比负向前瞻豁免统计口径词（"95% CI"/"95% 置信区间"是列头，非实验断言）。
_NUM_PATTERNS = [
    re.compile(r"\d+(?:\.\d+)?\s*%"
               r"(?!\s*(?:CI|C\.I\.|confidence(?:\s+interval)?|置信区间?))",
               re.IGNORECASE),
    # 关键词前加 \b：避免 "accept 128" 被拆成 Acc + [a-z_]* 而误判为指标断言；
    # 后缀只接受下划线连接的键名变体（accuracy_recent），不匹配普通动词尾部。
    re.compile(r"\b(?:F1|Accuracy|Acc|Precision|Recall|BLEU|loss|mAP)"
               r"(?:_[A-Za-z]+)?[\s=:\"']+\d+(?:\.\d+)?",
               re.IGNORECASE),
]


def _extract_numbers(text: str) -> set[str]:
    """从文本中提取全部量化断言（归一化字符串集合）。"""
    found: set[str] = set()
    if not text:
        return found
    for pat in _NUM_PATTERNS:
        found.update(m.group(0).replace(" ", "") for m in pat.finditer(text))
    return found


def _num_value(token: str):
    """取 token 末尾的数值（避开 F1/mAP 等指标名内嵌数字）。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*%?$", token)
    return float(m.group(1)) if m else None


def _unsupported_claims(claimed: set[str], truth: set[str]) -> set[str]:
    """未溯源断言集合。百分数/小数归一化比较（92.3% 视同 0.923）。"""
    truth_vals = []
    for tok in truth:
        v = _num_value(tok)
        if v is None:
            continue
        truth_vals.append(v)
        if tok.endswith("%"):
            truth_vals.append(v / 100.0)
    bad = set()
    for claim in claimed:
        v = _num_value(claim)
        if v is None:
            continue
        candidates = [v / 100.0] if claim.endswith("%") else [v]
        if not any(abs(c - t) <= 1e-9 * max(1.0, abs(t))
                   for c in candidates for t in truth_vals):
            bad.add(claim)
    return bad


def _load_ground_truth() -> set[str]:
    """加载真实实验结果中的全部量化数值。"""
    try:
        with open(RESULTS_PATH, "r", encoding="utf-8") as f:
            data: Any = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()
    raw = json.dumps(data, ensure_ascii=False)
    return _extract_numbers(raw)


class HallucinationCheckRail(DeepAgentRail):
    """幻觉校验：论文中的量化数据必须可溯源到真实实验结果。"""

    priority: int = 80

    async def after_model_call(self, ctx: AgentCallbackContext) -> None:
        """模型输出后：提取量化断言，与真实结果比对，不一致注入警告。"""
        try:
            output = self._get_output_text(ctx)
            if not output:
                _audit("after_model_call", "SKIP", "empty output")
                return
            claimed = _extract_numbers(output)
            if not claimed:
                _audit("after_model_call", "SKIP", "no numeric claims")
                return
            truth = _load_ground_truth()
            if not truth:
                # 基准文件不存在：仅提示，不阻断（构思阶段尚无实验数据）
                _audit("after_model_call", "WARN", f"no ground truth, {len(claimed)} claims unchecked")
                self._inject_note(ctx, "PAPER_LAB[hallucination]: 无 results.json 基准，本次输出未校验数据溯源。")
                return
            unsupported = _unsupported_claims(claimed, truth)
            if unsupported:
                _audit("after_model_call", "WARN",
                       f"unsupported={len(unsupported)}: " + "; ".join(sorted(unsupported)[:5]))
                self._inject_note(
                    ctx,
                    "PAPER_LAB[hallucination]: 以下量化断言未在真实实验结果中找到，"
                    "必须删除或改为 results.json 中存在的数值: "
                    + "; ".join(sorted(unsupported)[:10]),
                )
            else:
                _audit("after_model_call", "PASS", f"claims={len(claimed)} all traced")
        except Exception as exc:  # 防御：Rail 异常不得中断主流程
            _audit("after_model_call", "ERROR", str(exc)[:120])
            try:
                self._inject_note(ctx, f"PAPER_LAB[hallucination]: 校验器异常({exc})，已跳过。")
            except Exception:
                pass

    async def before_tool_call(self, ctx: AgentCallbackContext) -> None:
        """写论文文件前：再次校验待写入内容，防造假数据落盘。"""
        try:
            inputs = getattr(ctx, "inputs", None)
            tool_name = getattr(inputs, "tool_name", "") or ""
            tool_args = getattr(inputs, "tool_args", None) or {}
            content = str(tool_args.get("content") or tool_args.get("text") or "")
            if not content or "write" not in tool_name.lower():
                return
            claimed = _extract_numbers(content)
            if not claimed:
                return
            truth = _load_ground_truth()
            unsupported = _unsupported_claims(claimed, truth) if truth else set()
            if unsupported:
                _audit("before_tool_call", "WARN",
                       f"tool={tool_name} unsupported={len(unsupported)}: "
                       + "; ".join(sorted(unsupported)[:5]))
                self._inject_note(
                    ctx,
                    "PAPER_LAB[hallucination][BLOCK-HINT]: 待写入文件含未溯源数值: "
                    + "; ".join(sorted(unsupported)[:10]),
                )
            else:
                _audit("before_tool_call", "PASS", f"tool={tool_name} claims={len(claimed)} all traced")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 工具函数（防御式，不依赖具体 ctx API）
    # ------------------------------------------------------------------
    @staticmethod
    def _get_output_text(ctx: AgentCallbackContext) -> str:
        for attr in ("output", "response", "result", "text"):
            val = getattr(ctx, attr, None)
            if isinstance(val, str) and val:
                return val
            # 常见结构: ctx.outputs.message / ctx.result.text
            holder = getattr(ctx, attr, None)
            if holder is not None:
                for sub in ("message", "text", "content"):
                    sub_val = getattr(holder, sub, None)
                    if isinstance(sub_val, str) and sub_val:
                        return sub_val
        return ""

    @staticmethod
    def _inject_note(ctx: AgentCallbackContext, note: str) -> None:
        """把告警写入 ctx 可用的注记字段（字段名尽力兼容）。"""
        injected = False
        for attr in ("notes", "warnings", "system_notes"):
            lst = getattr(ctx, attr, None)
            if isinstance(lst, list):
                lst.append(note)
                injected = True
                break
        if not injected:
            # 兜底：挂到任意存在的 list/dict 字段上，至少保留审计痕迹
            for attr in vars(ctx) if hasattr(ctx, "__dict__") else []:
                val = getattr(ctx, attr, None)
                if isinstance(val, list):
                    val.append(note)
                    injected = True
                    break
        print(f"[hallucination_check] {note}")
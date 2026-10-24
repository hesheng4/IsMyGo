"""
学术规范 Rail（AcademicFormatRail）
====================================
功能：强制论文输出符合学术结构规范——章节完整、含参考文献。
      缺章节则在模型输出后注入"必须补齐"的约束提示。

挂载方式：与 hallucination_check 相同（复制到 extensions/，
          team 模式经 PLUGIN_RAILS 自动实例化）。
"""

from __future__ import annotations

import re
from pathlib import Path

from openjiuwen.core.single_agent.rail.base import AgentCallbackContext
from openjiuwen.harness.rails.base import DeepAgentRail

# 钩子触发审计日志（每次 after_model_call 实际执行都留痕，证明 Rail 在运行时生效）
RAIL_AUDIT_PATH = str(
    Path.home() / ".jiuwenswarm" / "agent" / "workspace" / "output" / "rail_runtime.log"
)


def _audit(verdict: str, detail: str = "") -> None:
    """追加一行审计记录；任何异常静默（不得影响主流程）。"""
    try:
        import datetime

        line = (f"{datetime.datetime.now().isoformat(timespec='seconds')} "
                f"| academic_format.after_model_call | {verdict}")
        if detail:
            line += f" | {detail}"
        with open(RAIL_AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# 论文必需章节（在标题行内做关键词包含匹配，中英兼容；
# 标题允许带编号，如 "## 1 引言"、"### 2.3 本文方法"）
_REQUIRED_SECTIONS = [
    ("abstract", ("abstract", "摘要")),
    ("introduction", ("introduction", "引言")),
    ("method", ("method", "方法")),
    ("experiment", ("experiment", "实验")),
    ("conclusion", ("conclusion", "结论")),
    ("references", ("references", "参考文献")),
]

_HEADING_LINE = re.compile(r"^#{1,4}\s+(.+)$", re.MULTILINE)
_NUMBERING = re.compile(r"^\d+(?:\.\d+)*[\.、:]?\s*")
_REFS_HEADING = re.compile(
    r"^#{1,4}\s*\d*[\.、:]?\s*(references|参考文献)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def _heading_texts(text: str) -> list[str]:
    """提取全部标题行文本，去掉前导编号后小写化。"""
    return [
        _NUMBERING.sub("", m.group(1).strip()).lower()
        for m in _HEADING_LINE.finditer(text)
    ]


def _missing_sections(text: str) -> list[str]:
    headings = " || ".join(_heading_texts(text))
    missing = []
    for label, keywords in _REQUIRED_SECTIONS:
        if not any(kw in headings for kw in keywords):
            missing.append(label)
    return missing


class AcademicFormatRail(DeepAgentRail):
    """学术结构规范：论文章节完整 + 引用可对齐。"""

    priority: int = 70

    async def after_model_call(self, ctx: AgentCallbackContext) -> None:
        try:
            output = self._get_output_text(ctx)
            # 仅当输出看起来是论文（有标题行且出现摘要/引言）才校验结构
            if not output or not _HEADING_LINE.search(output):
                _audit("SKIP", "no heading lines")
                return
            if not re.search(r"(abstract|摘\s*要|introduction|引\s*言)",
                             output, re.IGNORECASE):
                _audit("SKIP", "not paper-like (no abstract/introduction)")
                return
            missing = _missing_sections(output)
            if missing:
                _audit("WARN", "missing sections: " + ", ".join(missing))
                self._note(
                    ctx,
                    "PAPER_LAB[academic]: 论文缺少必需章节: "
                    + ", ".join(missing)
                    + "。必须补齐后再定稿（abstract/introduction/method/experiment/conclusion/references）。",
                )
            # 引用对齐检查：正文 [N] 引用必须在参考文献列表中有对应条目
            refs = _REFS_HEADING.search(output)
            dangling: set[str] = set()
            if refs:
                body, ref_list = output[:refs.start()], output[refs.end():]
                cited = set(re.findall(r"\[(\d+)\]", body))
                defined = set(re.findall(r"(?m)^\s*\[(\d+)\]", ref_list))
                dangling = cited - defined
                if dangling:
                    _audit("WARN", "dangling citations: "
                           + ", ".join(f"[{n}]" for n in sorted(dangling, key=int)))
                    self._note(
                        ctx,
                        "PAPER_LAB[academic]: 正文引用 "
                        + ", ".join(f"[{n}]" for n in sorted(dangling, key=int))
                        + " 未在参考文献列表中定义。",
                    )
            if not missing and not dangling:
                _audit("PASS", "sections complete, citations aligned")
        except Exception as exc:
            _audit("ERROR", str(exc)[:120])
            print(f"[academic_format] skip: {exc}")

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
        print(f"[academic_format] {note}")
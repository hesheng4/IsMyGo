# -*- coding: utf-8 -*-
"""评审回应补充实验 -> 论文附录表格生成 (写入 output/final/tables/).

15 页版式约束: 三张表合并为单表双面板 (a) 探针臂 (b) 片段审计;
reranker 延迟三数字改在正文 §5.2 以散文呈现, 不再单独出表。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import load_questions  # noqa: E402
from score import paired_bootstrap, mcnemar_exact  # noqa: E402

CODE_OUT = HERE.parents[1] / "output" / "longmemeval"
FINAL_TAB = HERE.parents[2] / "output" / "final" / "tables"
CANON = {q.question_id for q in load_questions()}


def load_probe() -> dict[str, dict[str, dict]]:
    by_arm: dict[str, dict[str, dict]] = {}
    for line in (CODE_OUT / "results_rebuttal_probe.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("model") == "glm-4.7-flash" and r["question_id"] in CANON:
            by_arm.setdefault(r["policy"], {})[r["question_id"]] = r
    return by_arm


def paired_delta(by_arm, a: str, b: str) -> tuple[float, list[float], float]:
    ra, rb = by_arm[f"retrieval{a}"], by_arm[f"retrieval{b}"]
    ids = sorted((set(ra) & set(rb)) & CANON)
    xa = [ra[i]["relaxed_em"] for i in ids]
    xb = [rb[i]["relaxed_em"] for i in ids]
    (_, _, _), (lo, hi) = paired_bootstrap(xa, xb)
    mc = mcnemar_exact(xa, xb)
    return (sum(xa) / len(xa) - sum(xb) / len(xb), [lo, hi], mc["p_value"])


def main() -> None:
    by_arm = load_probe()
    arms = [("@chrono", "chronological (protocol, T1)"),
            ("@shuf", "shuffled order (same turns, T1)"),
            ("@rel", "BM25 relevance order (T1)"),
            ("@nat", "chronological + relaxed template (T2)"),
            ("@con", "chronological + chain-of-note (T3)")]
    L = ["\\begin{tabular}{@{}lcccc@{}}", "\\toprule",
         "Arm & EM$_{\\text{rel}}$ & EM & F1 & $\\Delta$EM$_{\\text{rel}}$ [95\\% CI], $p$ \\\\"]
    for suf, label in arms:
        recs = list(by_arm[f"retrieval{suf}"].values())
        n = len(recs)
        rel = sum(r["relaxed_em"] for r in recs) / n
        em = sum(r["em"] for r in recs) / n
        f1 = sum(r["f1"] for r in recs) / n
        if suf == "@chrono":
            d = "--"
        else:
            delta, ci, p = paired_delta(by_arm, suf, "@chrono")
            d = f"${delta:+.3f}$ [{ci[0]:+.3f},{ci[1]:+.3f}], $p{{=}}{p:.2f}$"
        L.append(f"{label} & {rel:.4f} & {em:.4f} & {f1:.4f} & {d} \\\\")
    L += ["\\bottomrule", "\\end{tabular}"]
    (FINAL_TAB / "rebuttal_probe.tex").write_text("\n".join(L), encoding="utf-8")
    print("[tab] rebuttal_probe.tex written (5-arm panel only)")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""judge_type.py —— E4 语义 judge 结果的按题型 / 按预算翻转率表。

数据源: tables/judge_full.json (E4 全量 judge: 1,746 条 read-fail 判定 + 210 对照,
judge=GLM-4.7-Flash thinking off); 题型经 results.jsonl 的 mimo 120 题记录按 qid 关联。
口径: flip = read-fail 被判为语义 CORRECT 的比例 (对 relaxed EM 的低估修正)。
输出: output/final/tables/judge_type.tex (论文 Table tab:judgetype 的表体)。
用法: python judge_type.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

RESULTS = HERE.parents[1] / "output" / "longmemeval" / "results.jsonl"
JUDGE = HERE.parents[1] / "output" / "longmemeval" / "tables" / "judge_full.json"
OUT_TEX = HERE.parents[2] / "output" / "final" / "tables" / "judge_type.tex"

TYPE_LABELS = [
    ("single-session-assistant", "single-assistant"),
    ("single-session-user", "single-user"),
    ("single-session-preference", "single-preference"),
    ("knowledge-update", "knowledge-update"),
    ("temporal-reasoning", "temporal"),
    ("multi-session", "multi-session"),
]
BUDGETS = [512, 1024, 2048, 4096]


def main() -> None:
    qtype: dict = {}
    for line in open(RESULTS, encoding="utf-8"):
        r = json.loads(line)
        if r["model"] == "mimo-v2.6-flash":
            qtype[r["question_id"]] = r["question_type"]

    d = json.load(open(JUDGE, encoding="utf-8"))
    by_type = {t: [0, 0] for t, _ in TYPE_LABELS}
    by_budget = {b: [0, 0] for b in BUDGETS}
    for r in d["rows"]:
        if r["kind"] != "read_fail":
            continue
        ok = r["verdict"] == "CORRECT"
        t = qtype.get(r["qid"])
        if t in by_type:
            by_type[t][0] += 1
            by_type[t][1] += ok
        by_budget[r["budget"]][0] += 1
        by_budget[r["budget"]][1] += ok

    lines = ["\\begin{tabular}{lccc}", "\\toprule",
             "Group & judged & flip to correct & rate \\\\", "\\midrule"]
    for t, label in TYPE_LABELS:
        n, c = by_type[t]
        lines.append("%s & %d & %d & $%.2f$ \\\\" % (label, n, c, c / n))
    lines.append("\\midrule")
    for b in BUDGETS:
        n, c = by_budget[b]
        lines.append("$B{=}%d$ (all types) & %d & %d & $%.2f$ \\\\" % (b, n, c, c / n))
    ctrl = d["controls_total"]
    lines.append("controls (already correct) & %d & incorrect: %d & $0.00$ \\\\"
                 % (ctrl["n"], ctrl["incorrect"]))
    lines += ["\\bottomrule", "\\end{tabular}"]
    tex = "\n".join(lines) + "\n"
    OUT_TEX.write_text(tex, encoding="utf-8")
    print("written:", OUT_TEX)
    print(tex)


if __name__ == "__main__":
    main()

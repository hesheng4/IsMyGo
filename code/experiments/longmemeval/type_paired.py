# -*- coding: utf-8 -*-
"""type_paired.py —— per-type × per-budget 的 retrieval vs hierarchical 配对比较表。

数据源: code/output/longmemeval/results.jsonl (主读者 deepseek-v4.1-flash, 全量 500 题)。
口径: relaxed EM, 按题配对, 精确 McNemar (** p<0.01, * p<0.05);
      Δ = hierarchical − retrieval (按题型家族聚合, single-* = 三个 single-session 型合并)。
输出: output/final/tables500/type_paired.tex (论文 Table tab:typepaired 的表体)。
用法: python type_paired.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from score import mcnemar_exact  # noqa: E402

RESULTS = HERE.parents[1] / "output" / "longmemeval" / "results.jsonl"
OUT_TEX = HERE.parents[2] / "output" / "final" / "tables500" / "type_paired.tex"

BUDGETS = [512, 1024, 2048, 4096]
FAMILIES = [("single-*", "single-* ($n{=}156$/budget)"),
            ("multi", "multi-session ($n{=}133$)"),
            ("temporal", "temporal ($n{=}133$)"),
            ("update", "knowledge-update ($n{=}78$)"),
            ("overall", "overall ($n{=}500$)")]


def fam(t: str) -> str:
    if t.startswith("single-session"):
        return "single-*"
    if t == "multi-session":
        return "multi"
    if t == "temporal-reasoning":
        return "temporal"
    if t == "knowledge-update":
        return "update"
    return t


def main() -> None:
    recs: dict = defaultdict(dict)
    types: dict = {}
    for line in open(RESULTS, encoding="utf-8"):
        r = json.loads(line)
        if r.get("model") != "deepseek-v4.1-flash":
            continue
        if r["policy"] in ("retrieval", "hierarchical") and r["budget"] in BUDGETS:
            recs[(r["question_id"], r["budget"])][r["policy"]] = r["relaxed_em"]
            types[r["question_id"]] = r["question_type"]

    def cells(budgets, key):
        r_list, h_list = [], []
        for (q, b), d in recs.items():
            if b in budgets and len(d) == 2 and (key == "overall" or fam(types[q]) == key):
                r_list.append(d["retrieval"])
                h_list.append(d["hierarchical"])
        return r_list, h_list

    rows = []
    for key, label in FAMILIES:
        cells_row = []
        for b in BUDGETS:
            a, c = cells([b], key)
            n = len(a)
            delta = sum(c) / n - sum(a) / n
            p = mcnemar_exact(a, c)["p_value"]
            star = "**" if p < 0.01 else ("*" if p < 0.05 else "")
            cells_row.append("$%+.3f$%s" % (delta, star))
        a, c = cells(BUDGETS, key)                     # pooled 列
        delta = sum(c) / len(c) - sum(a) / len(a)
        p = mcnemar_exact(a, c)["p_value"]
        star = "**" if p < 0.01 else ("*" if p < 0.05 else "")
        cells_row.append("$%+.3f$%s" % (delta, star))
        rows.append("%s & %s" % (label, " & ".join(cells_row)))

    tex = ("\\begin{tabular}{lccccc}\n\\toprule\n"
           "Family & $B{=}512$ & $B{=}1024$ & $B{=}2048$ & $B{=}4096$ & pooled \\\\\n"
           "\\midrule\n" + " \\\\\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n")
    OUT_TEX.write_text(tex, encoding="utf-8")
    print("written:", OUT_TEX)
    print(tex)


if __name__ == "__main__":
    main()

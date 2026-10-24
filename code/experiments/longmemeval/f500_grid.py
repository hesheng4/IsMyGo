# -*- coding: utf-8 -*-
"""全量 500 题主网格聚合 (第八轮评审: 主网格升级为 n=500)。

产出:
  code/output/longmemeval/f500_summary.json   -- 所有数字 + 配对检验
  output/final/tables500/*.tex                -- 论文 \\input 片段 (main/latency/bytype/stats/consolidated/headline)

口径与 analyze.py 一致: relaxed EM 为主线, 配对 bootstrap (10k, seed 42) + exact McNemar。
只读 results.jsonl 中指定读者的记录, 按 question_id 对齐。
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

from common import load_questions
from score import mcnemar_exact, paired_bootstrap

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "output" / "longmemeval"
TAB = Path(__file__).resolve().parents[3] / "output" / "final" / "tables500"
TAB.mkdir(parents=True, exist_ok=True)

READER = "deepseek-v4.1-flash"
POLICIES = ["full_context", "sliding_window", "retrieval",
            "retrieval_recency", "compression", "hierarchical"]
POLICY_TEX = {
    "full_context": r"full-context (verbatim)$^{\dagger}$",
    "sliding_window": r"sliding window",
    "retrieval": r"retrieval (BM25)",
    "retrieval_recency": r"retrieval+recency",
    "compression": r"compression (window+summ.)",
    "hierarchical": r"hierarchical (3-tier)",
}
BUDGETS = [512, 1024, 2048, 4096]
TYPE_ORDER = ["single-session-user", "single-session-assistant",
              "single-session-preference", "multi-session",
              "temporal-reasoning", "knowledge-update"]
TYPE_TEX = {"single-session-user": "single-user", "single-session-assistant": "single-assist.",
            "single-session-preference": "single-pref.", "multi-session": "multi-session",
            "temporal-reasoning": "temporal", "knowledge-update": "update"}

q500 = {q.question_id: q for q in load_questions(full=True)}
sample120 = {q.question_id for q in load_questions()}

recs: dict[tuple, dict[str, dict]] = defaultdict(dict)
for line in (OUT / "results.jsonl").read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    r = json.loads(line)
    if r.get("model") != READER:
        continue
    if r["question_id"] not in q500:
        continue
    key = (r["policy"], r.get("budget"))
    recs[key][r["question_id"]] = r

summary = {"reader": READER, "n": len(q500), "cells": {}, "tests": {}}
missing = []
for p in POLICIES:
    budgets = [None] if p == "full_context" else BUDGETS
    for b in budgets:
        rs = recs.get((p, b), {})
        if len(rs) != len(q500):
            missing.append([p, b, len(rs)])
        ids = [qid for qid in q500 if qid in rs]
        cell = {
            "n": len(ids),
            "em": statistics.mean(rs[q]["em"] for q in ids),
            "em_rel": statistics.mean(rs[q]["relaxed_em"] for q in ids),
            "f1": statistics.mean(rs[q]["f1"] for q in ids),
            "footprint": statistics.mean(rs[q].get("memory_footprint_tokens", 0) for q in ids),
            "access_ms": statistics.mean(rs[q].get("access_ms", 0) for q in ids),
            "e2e_s": statistics.mean(rs[q].get("e2e_ms", 0) / 1000 for q in ids),
            "empty_pred": sum(1 for q in ids if not (rs[q].get("pred") or "").strip()),
        }
        summary["cells"][f"{p}|{b}"] = cell

# ---------------- 配对检验 ----------------
def paired(p1, b1, p2, b2, metric="relaxed_em"):
    a = recs[(p1, b1)]
    b = recs[(p2, b2)]
    ids = sorted(set(a) & set(b))
    x = [a[q][metric] for q in ids]
    y = [b[q][metric] for q in ids]
    (ma, mb, _), ci = paired_bootstrap(x, y)
    mcn = mcnemar_exact([a[q]["em"] for q in ids], [b[q]["em"] for q in ids])
    return {"n": len(ids), "a": round(ma, 4), "b": round(mb, 4),
            "delta": round(ma - mb, 4), "ci": [round(ci[0], 4), round(ci[1], 4)],
            "p": round(mcn["p_value"], 4), "flips": [mcn["n10"], mcn["n01"]]}

for b in BUDGETS:
    summary["tests"][f"compression_vs_retrieval|{b}"] = paired("compression", b, "retrieval", b)
summary["tests"]["compression_vs_hier|4096"] = paired("compression", 4096, "hierarchical", 4096)
summary["tests"]["retrieval_vs_hier|4096"] = paired("retrieval", 4096, "hierarchical", 4096)
summary["tests"]["fc_vs_hier|4096"] = paired("full_context", None, "hierarchical", 4096)
summary["tests"]["fc_vs_retrieval|4096"] = paired("full_context", None, "retrieval", 4096)
summary["tests"]["hier_4096_vs_2048"] = paired("hierarchical", 4096, "hierarchical", 2048)
summary["tests"]["retr_4096_vs_2048"] = paired("retrieval", 4096, "retrieval", 2048)

# 120 子集 vs 500 全量 (逐格偏差)
sub = {q: True for q in sample120}
bias = {}
for p in POLICIES:
    for b in ([None] if p == "full_context" else BUDGETS):
        rs = recs.get((p, b), {})
        ids = [q for q in q500 if q in rs]
        ids120 = [q for q in ids if q in sub]
        bias[f"{p}|{b}"] = {
            "em500": round(statistics.mean(rs[q]["em"] for q in ids), 4),
            "em120": round(statistics.mean(rs[q]["em"] for q in ids120), 4),
            "delta": round(statistics.mean(rs[q]["em"] for q in ids)
                           - statistics.mean(rs[q]["em"] for q in ids120), 4),
        }
summary["subset_bias"] = bias
summary["max_abs_bias"] = max(abs(v["delta"]) for v in bias.values())
summary["missing_cells"] = missing

# ---------------- 分题型 (pooled budget) + 逐型 CI ----------------
bytype = {}
for p in POLICIES:
    per_type = {}
    for t in TYPE_ORDER:
        vals = []
        for b in ([None] if p == "full_context" else BUDGETS):
            rs = recs.get((p, b), {})
            vals += [rs[q]["em"] for q in rs if q500[q].question_type == t]
        per_type[t] = {"n": len(vals), "em": round(statistics.mean(vals), 4) if vals else None}
    bytype[p] = per_type
summary["bytype"] = bytype

# 题型级配对差 (retrieval vs hierarchical @4096), 每型 n 与 CI
type_tests = {}
a = recs[("retrieval", 4096)]
bb = recs[("hierarchical", 4096)]
for t in TYPE_ORDER:
    ids = [q for q in a if q in bb and q500[q].question_type == t]
    if len(ids) < 2:
        continue
    x = [a[q]["relaxed_em"] for q in ids]
    y = [bb[q]["relaxed_em"] for q in ids]
    (ma, mb, _), ci = paired_bootstrap(x, y)
    mcn = mcnemar_exact([a[q]["em"] for q in ids], [bb[q]["em"] for q in ids])
    type_tests[t] = {"n": len(ids), "retrieval": round(ma, 3), "hier": round(mb, 3),
                     "delta": round(ma - mb, 3), "ci": [round(ci[0], 3), round(ci[1], 3)],
                     "p": round(mcn["p_value"], 4)}
summary["type_tests_rh_4096"] = type_tests

(OUT / "f500_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

# ---------------- TeX ----------------
def f4(x):
    return f"{x:.4f}"

lines = [r"\begin{tabular}{llcccc}", r"\toprule",
         r"Policy & Budget & $n$ & EM & EM$_{\text{rel}}$ & token-F1 \\", r"\midrule"]
for p in POLICIES:
    for b in ([None] if p == "full_context" else BUDGETS):
        c = summary["cells"][f"{p}|{b}"]
        lines.append(f"{POLICY_TEX[p]} & {('--' if b is None else b)} & {c['n']} & "
                     f"{f4(c['em'])} & {f4(c['em_rel'])} & {f4(c['f1'])} \\\\")
lines += [r"\bottomrule", r"\end{tabular}"]
(TAB / "main.tex").write_text("\n".join(lines), encoding="utf-8")

lines = [r"\begin{tabular}{llcccc}", r"\toprule",
         r"Policy & Budget & access (ms) & e2e (s) & mem.\ tokens \\", r"\midrule"]
for p in POLICIES:
    for b in ([None] if p == "full_context" else BUDGETS):
        c = summary["cells"][f"{p}|{b}"]
        lines.append(f"{POLICY_TEX[p]} & {('--' if b is None else b)} & "
                     f"{c['access_ms']:.3f} & {c['e2e_s']:.2f} & {c['footprint']:.0f} \\\\")
lines += [r"\bottomrule", r"\end{tabular}"]
(TAB / "latency.tex").write_text("\n".join(lines), encoding="utf-8")

lines = [r"\begin{tabular}{lcccccc}", r"\toprule",
         r"Policy & single-* & multi & temporal & update & overall \\",
         r"\midrule"]
for p in POLICIES:
    row = [POLICY_TEX[p]]
    for grp in (["single-session-user", "single-session-assistant", "single-session-preference"],
                ["multi-session"], ["temporal-reasoning"], ["knowledge-update"]):
        vals = []
        for t in grp:
            for b in ([None] if p == "full_context" else BUDGETS):
                rs = recs.get((p, b), {})
                vals += [rs[q]["em"] for q in rs if q500[q].question_type == t]
        row.append(f"{statistics.mean(vals):.3f}")
    vals = []
    for b in ([None] if p == "full_context" else BUDGETS):
        rs = recs.get((p, b), {})
        vals += [rs[q]["em"] for q in rs]
    row.append(f"{statistics.mean(vals):.3f}")
    lines.append(" & ".join(row) + r" \\")
lines += [r"\bottomrule", r"\end{tabular}"]
(TAB / "bytype.tex").write_text("\n".join(lines), encoding="utf-8")

lines = [r"\begin{tabular}{llcccc}", r"\toprule",
         r"Budget & Baseline & $\Delta$EM & 95\% CI & McNemar $p$ \\", r"\midrule"]
for b in BUDGETS:
    t = summary["tests"][f"compression_vs_retrieval|{b}"]
    lines.append(f"{b} & retrieval (BM25) & {t['delta']:+.4f} & "
                 f"[{t['ci'][0]:+.4f}, {t['ci'][1]:+.4f}] & {t['p']:.4f} \\\\")
t = summary["tests"]["compression_vs_hier|4096"]
lines.append(f"4096 & hierarchical (3-tier) & {t['delta']:+.4f} & "
             f"[{t['ci'][0]:+.4f}, {t['ci'][1]:+.4f}] & {t['p']:.4f} \\\\")
lines += [r"\bottomrule", r"\end{tabular}"]
(TAB / "stats.tex").write_text("\n".join(lines), encoding="utf-8")

# consolidated (relaxed EM with cell CI)
def cell_ci(p, b):
    rs = recs[(p, b)]
    ids = [q for q in q500 if q in rs]
    x = [rs[q]["relaxed_em"] for q in ids]
    (m, _, _), ci = paired_bootstrap(x, [0.0] * len(x))
    return m, ci

lines = [r"\begin{tabular}{lcccc}", r"\toprule",
         r"Policy & $B{=}512$ & $B{=}1024$ & $B{=}2048$ & $B{=}4096$ \\", r"\midrule"]
for p in POLICIES[1:]:
    row = [POLICY_TEX[p]]
    for b in BUDGETS:
        m, ci = cell_ci(p, b)
        row.append(f"{m:.3f} [{ci[0]:.2f}, {ci[1]:.2f}]")
    lines.append(" & ".join(row) + r" \\")
m, ci = cell_ci("full_context", None)
lines += [r"\midrule", r"full-context (this run, $n{=}500$) & \multicolumn{4}{c}{"
          f"{m:.3f} [{ci[0]:.2f}, {ci[1]:.2f}]" + r"} \\", r"\bottomrule", r"\end{tabular}"]
(TAB / "consolidated_emrel.tex").write_text("\n".join(lines), encoding="utf-8")

# headline macros
fc = summary["cells"]["full_context|None"]
h = ["% auto-generated by f500_grid.py -- do not edit", r"\newcommand{\longmemN}{500}",
     r"\newcommand{\fcDoneN}{500}", r"\newcommand{\fcDoneEM}{" + f"{fc['em_rel']:.4f}" + "}",
     r"\newcommand{\fcEmptyN}{0}", r"\newcommand{\fcDoneEtwoE}{" + f"{fc['e2e_s']:.0f}" + "}",
     r"\newcommand{\eTwoETypical}{" + f"{summary['cells']['retrieval|4096']['e2e_s']:.0f}" + "}",
     r"\newcommand{\fcFoot}{" + f"{fc['footprint']:.0f}".replace("000", r"\,000") + "}",
     r"\newcommand{\fcAtLarge}{" + f"{100 * 4096 / fc['footprint']:.1f}" + "}",
     r"\newcommand{\compLargeEM}{" + f"{summary['cells']['compression|4096']['em_rel']:.4f}" + "}",
     r"\newcommand{\compLargeBaseEM}{" + f"{summary['cells']['retrieval|4096']['em_rel']:.4f}" + "}"]
(TAB / "headline.tex").write_text("\n".join(h), encoding="utf-8")

print(json.dumps({k: summary["cells"][k] for k in summary["cells"]}, indent=0)[:2000])
print("\nTESTS")
for k, v in summary["tests"].items():
    print(k, v)
print("\nMAXBIAS", summary["max_abs_bias"], "MISSING", missing)
print("\nBYTYPE")
for p in POLICIES:
    print(p, {t: bytype[p][t]["em"] for t in TYPE_ORDER})
print("\nTYPETESTS")
for t, v in type_tests.items():
    print(t, v)

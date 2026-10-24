# -*- coding: utf-8 -*-
"""Round-8 probe analysis: tight budgets, hierarchy variants, digest selection.

Reads results_r8.jsonl plus the main grid (results.jsonl, DeepSeek), writes
r8_summary.json and three LaTeX fragments in output/final/tables500/.
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
READER = "deepseek-v4.1-flash"

R8 = [json.loads(x) for x in (OUT / "results_r8.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
GRID = {}
for line in (OUT / "results.jsonl").read_text(encoding="utf-8").splitlines():
    if line.strip():
        r = json.loads(line)
        if r.get("model") == READER:
            GRID[(r["policy"], r.get("budget"), r["question_id"])] = r
Q120 = {q.question_id for q in load_questions()}

cells = defaultdict(dict)
for r in R8:
    cells[(r["policy"], r["budget"])][r["question_id"]] = r


def stats(rs: dict) -> dict:
    v = list(rs.values())
    return {"n": len(v), "em": statistics.mean(x["em"] for x in v),
            "rel": statistics.mean(x["relaxed_em"] for x in v),
            "f1": statistics.mean(x["f1"] for x in v),
            "fp": statistics.mean(x["memory_footprint_tokens"] for x in v)}


def cmp_arm(pol, b, opp_pol, opp_b, restrict120=True):
    a = cells[(pol, b)]
    if opp_pol in ("retrieval", "compression", "hierarchical"):
        bset = {q: GRID[(opp_pol, opp_b, q)] for q in a if (opp_pol, opp_b, q) in GRID}
    else:
        bset = cells[(opp_pol, opp_b)]
    ids = [q for q in a if q in bset and (q in Q120 or not restrict120)]
    x = [a[q]["relaxed_em"] for q in ids]
    y = [bset[q]["relaxed_em"] for q in ids]
    (ma, mb, _), ci = paired_bootstrap(x, y)
    m = mcnemar_exact(x, y)
    return {"n": len(ids), "a": round(ma, 4), "b": round(mb, 4),
            "delta": round(ma - mb, 4), "ci": [round(ci[0], 4), round(ci[1], 4)],
            "p": round(m["p_value"], 5), "flips": [m["n10"], m["n01"]]}


summ = {"reader": READER, "cells": {f"{p}|{b}": stats(rs) for (p, b), rs in cells.items()},
        "tests": {}}


def cell_rel(pol, b):
    """relaxed EM for a cell, from the probe file or (for baselines) the main grid on 120."""
    if (pol, b) in cells:
        return summ["cells"][f"{pol}|{b}"]["rel"]
    v = [GRID[(pol, b, q)]["relaxed_em"] for q in Q120 if (pol, b, q) in GRID]
    return statistics.mean(v)
for b in (1024, 4096):
    for pol in ("hier_multiindex", "hier_traverse"):
        summ["tests"][f"{pol}_vs_hier|{b}"] = cmp_arm(pol, b, "hierarchical", b)
        summ["tests"][f"{pol}_vs_retr|{b}"] = cmp_arm(pol, b, "retrieval", b)
for b in (1024, 4096):
    summ["tests"][f"compselect_vs_compression|{b}"] = cmp_arm("compression_select", b, "compression", b, False)
    summ["tests"][f"compselect_vs_retrieval|{b}"] = cmp_arm("compression_select", b, "retrieval", b, False)

(OUT / "r8_summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")

for k, v in summ["tests"].items():
    print(k, v)
print({k: v for k, v in summ["cells"].items() if "_" in k and k.split("|")[1] in ("64", "128", "256")})

BS = chr(92)
# tight budget table
lines = [BS + "begin{tabular}{lcccc}", BS + "toprule",
         "Policy & $B{=}64$ & $B{=}128$ & $B{=}256$ & $B{=}512$ " + BS + BS,
         BS + "midrule"]
for pol, label in (("retrieval", "retrieval (BM25)"), ("compression", "compression"),
                   ("hierarchical", "hierarchical")):
    row = [label]
    for b in (64, 128, 256):
        row.append(f"{summ['cells'][f'{pol}|{b}']['rel']:.3f}")
    v512 = [GRID[(pol, 512, q)]["relaxed_em"] for q in Q120 if (pol, 512, q) in GRID]
    row.append(f"{statistics.mean(v512):.3f}")
    lines.append(" & ".join(row) + BS + BS)
lines += [BS + "bottomrule", BS + "end{tabular}"]
(TAB / "tight.tex").write_text("\n".join(lines), encoding="utf-8")

# hierarchy variants
lines = [BS + "begin{tabular}{lcccc}", BS + "toprule",
         "Variant & $B{=}1024$ & $B{=}4096$ & $\\Delta$ vs.\\ base & $p$ " + BS + BS,
         BS + "midrule"]
for pol, label in (("hierarchical", "3-tier (take-newest digests)"),
                   ("hier_multiindex", "+ relevance-ranked digest index"),
                   ("hier_traverse", "+ 1-hop session-neighbour expansion")):
    b1 = cell_rel(pol, 1024)
    b4 = cell_rel(pol, 4096)
    if pol == "hierarchical":
        d, p = "--", "--"
    else:
        t = summ["tests"][f"{pol}_vs_hier|4096"]
        d, p = f"{t['delta']:+.3f}", f"{t['p']:.3f}"
    lines.append(f"{label} & {b1:.3f} & {b4:.3f} & {d} & {p} " + BS + BS)
lines += [BS + "bottomrule", BS + "end{tabular}"]
(TAB / "hiervar.tex").write_text("\n".join(lines), encoding="utf-8")

# compression-select
lines = [BS + "begin{tabular}{lcccc}", BS + "toprule",
         "Compression variant & $B{=}1024$ & $B{=}4096$ & $\\Delta$@1024 vs.\\ retr. & "
         "$\\Delta$@4096 vs.\\ retr. " + BS + BS, BS + "midrule"]
for pol, label in (("compression", "write-time only (take-newest)"),
                   ("compression_select", "+ query-time digest selection")):
    row = [label, f"{cell_rel(pol, 1024):.3f}", f"{cell_rel(pol, 4096):.3f}"]
    if pol == "compression":
        for b in (1024, 4096):
            ids = [q for q in Q120 if (("compression", b, q) in GRID
                                       and ("retrieval", b, q) in GRID)]
            d = statistics.mean(GRID[("compression", b, q)]["relaxed_em"]
                                - GRID[("retrieval", b, q)]["relaxed_em"] for q in ids)
            row.append(f"{d:+.3f}")
    else:
        row.append(f"{summ['tests']['compselect_vs_retrieval|1024']['delta']:+.3f} "
                   f"(p={summ['tests']['compselect_vs_retrieval|1024']['p']:.2f})")
        row.append(f"{summ['tests']['compselect_vs_retrieval|4096']['delta']:+.3f} "
                   f"(p={summ['tests']['compselect_vs_retrieval|4096']['p']:.3f})")
    lines.append(" & ".join(row) + BS + BS)
lines += [BS + "bottomrule", BS + "end{tabular}"]
(TAB / "compselect.tex").write_text("\n".join(lines), encoding="utf-8")

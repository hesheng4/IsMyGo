# -*- coding: utf-8 -*-
"""Round-9 memory-access timing pass (no LLM calls).

Re-measures context-assembly latency for every main-grid variant, including the
read-time compression variant, with one identical procedure so that Table 4 stays
internally consistent after the promotion of compression_select.

Per (policy, budget): assemble for all 500 questions, 3 repeats, take the per-question
median across repeats, then the median over questions; footprint is the mean over the
first repeat. Writes access_timing_r9.json and tables500/latency.tex.

Usage: python r9_timing.py [--write]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import load_questions  # noqa: E402
from f500_diag import load_summaries60  # noqa: E402
from policies import build_memory  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
TAB = OUT.parents[2] / "output" / "final" / "tables500"

POLICIES = ["full_context", "sliding_window", "retrieval", "retrieval_recency",
            "compression", "compression_select", "hierarchical"]
LABEL = {
    "full_context": r"full-context (verbatim)$^{\dagger}$",
    "sliding_window": "sliding window",
    "retrieval": "retrieval (BM25)",
    "retrieval_recency": "retrieval+recency",
    "compression": "compression (write-time)",
    "compression_select": "compression$+$read-time sel.",
    "hierarchical": "hierarchical (3-tier)",
}
BUDGETS = [512, 1024, 2048, 4096]
REPEATS = 3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    qs = load_questions(full=True)
    sums = load_summaries60()
    out = {}
    print(f"[timing] questions={len(qs)} summaries={len(sums)}", flush=True)

    for pol in POLICIES:
        budgets = [None] if pol == "full_context" else BUDGETS
        for b in budgets:
            t0 = time.time()
            per_q, foot = [], []
            for q in qs:
                samples = []
                for _ in range(REPEATS):
                    plan = build_memory(pol, q, b, sums)
                    samples.append(plan.access_ms)
                per_q.append(statistics.median(samples))
                foot.append(plan.footprint_tokens)
            key = f"{pol}|{b}"
            out[key] = {
                "median_ms": round(statistics.median(per_q), 2),
                "mean_ms": round(statistics.mean(per_q), 2),
                "p90_ms": round(sorted(per_q)[int(0.9 * len(per_q))], 2),
                "footprint": round(statistics.mean(foot)),
            }
            print(f"[timing] {key:32s} {out[key]}  ({time.time()-t0:.0f}s)", flush=True)

    (OUT / "access_timing_r9.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

    if args.write:
        rows = []
        for pol in POLICIES:
            budgets = [None] if pol == "full_context" else BUDGETS
            for b in budgets:
                c = out[f"{pol}|{b}"]
                bt = "--" if b is None else str(b)
                rows.append(f"{LABEL[pol]} & {bt} & {c['median_ms']:.2f} & {c['footprint']:.0f} \\\\")
        tex = (
            "\\begin{tabular}{llcc}\n\\toprule\n"
            "Policy & Budget & access (ms) & mem.\\ tokens \\\\\n\\midrule\n"
            + "\n".join(rows) +
            "\n\\bottomrule\n\\end{tabular}"
        )
        (TAB / "latency.tex").write_text(tex, encoding="utf-8")
        print("wrote", TAB / "latency.tex")


if __name__ == "__main__":
    main()

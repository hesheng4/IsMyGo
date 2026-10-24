"""LoCoMo cross-dataset probe: aggregate cells + paired tests.

Reads code/output/locomeval/results_locomo.jsonl (deepseek-v4.1-flash reader),
writes code/output/locomeval/locomo_summary.json.

Usage: python locomo_analyze.py
"""
from __future__ import annotations

import collections
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from score import mcnemar_exact, paired_bootstrap  # noqa: E402

RESULTS = Path(os.environ.get("ISMYGO_ROOT", str(Path(__file__).resolve().parents[3]))) / "code/output/locomeval/results_locomo.jsonl"
OUT = RESULTS.parent / "locomo_summary.json"

POLICIES = ["retrieval", "compression", "hierarchical"]
BUDGETS = [1024, 2048, 4096]


def main() -> None:
    recs = [json.loads(line) for line in RESULTS.read_text(encoding="utf-8").splitlines() if line.strip()]
    by = collections.defaultdict(dict)
    for r in recs:
        by[(r["policy"], r["budget"])][r["question_id"]] = r

    summary: dict = {"dataset": "LoCoMo (5 of 10 conversations; jsDelivr-truncated public file)",
                     "reader": recs[0]["model"] if recs else "?", "cells": {}}

    print(f"{'cell':26s} {'n':>5s} {'EM':>7s} {'F1':>7s}")
    for pol in POLICIES:
        for b in BUDGETS:
            cell = by.get((pol, b), {})
            if not cell:
                print(f"{pol}|{b:<16d} {'--':>5s}   missing")
                continue
            v = list(cell.values())
            n = len(v)
            em = sum(x["relaxed_em"] for x in v) / n
            f1 = sum(x["f1"] for x in v) / n
            summary["cells"][f"{pol}|{b}"] = {"n": n, "relaxed_em": round(em, 4), "f1": round(f1, 4)}
            print(f"{pol}|{b:<16d} {n:>5d} {em:>7.4f} {f1:>7.4f}")

    print("\nordering per budget (relaxed EM):")
    summary["ordering"] = {}
    for b in BUDGETS:
        sc = {p: summary["cells"].get(f"{p}|{b}", {}).get("relaxed_em") for p in POLICIES}
        avail = {p: s for p, s in sc.items() if s is not None}
        if not avail:
            continue
        order = sorted(avail, key=avail.get, reverse=True)
        summary["ordering"][str(b)] = order
        print(f"  B={b}: " + "  ".join(f"{p}={avail[p]:.4f}" for p in order))

    print("\npaired tests (retrieval as anchor):")
    summary["paired"] = {}
    for b in BUDGETS:
        base = by.get(("retrieval", b), {})
        if not base:
            continue
        for pol in ["compression", "hierarchical"]:
            other = by.get((pol, b), {})
            ids = sorted(set(base) & set(other))
            if len(ids) < 30:
                continue
            xa = [base[i]["relaxed_em"] for i in ids]
            xb = [other[i]["relaxed_em"] for i in ids]
            ma, mb = sum(xa) / len(xa), sum(xb) / len(xb)
            (_, _, _), (lo, hi) = paired_bootstrap(xa, xb)
            mc = mcnemar_exact(xa, xb)
            key = f"retrieval_vs_{pol}@{b}"
            summary["paired"][key] = {
                "n": len(ids), "retrieval": round(ma, 4), pol: round(mb, 4),
                "delta": round(ma - mb, 4), "ci": [round(lo, 4), round(hi, 4)],
                "p": mc["p_value"], "n10": mc["n10"], "n01": mc["n01"],
            }
            print(f"  retr {ma:.4f} vs {pol:13s} {mb:.4f} @{b}: "
                  f"delta={ma-mb:+.4f} [{lo:+.4f},{hi:+.4f}] p={mc['p_value']:.3f} "
                  f"(n10={mc['n10']},n01={mc['n01']})")

    print("\nbudget monotonicity (relaxed EM by budget):")
    summary["monotone"] = {}
    for pol in POLICIES:
        seq = [summary["cells"].get(f"{pol}|{b}", {}).get("relaxed_em") for b in BUDGETS]
        if None in seq or len(seq) != 3:
            continue
        mono = all(seq[i] <= seq[i + 1] + 1e-9 for i in range(2))
        summary["monotone"][pol] = {"em_by_budget": seq, "monotone_nondecreasing": mono}
        print(f"  {pol:13s} {seq[0]:.4f} -> {seq[1]:.4f} -> {seq[2]:.4f}  monotone={mono}")

    OUT.write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nwritten: {OUT}")


if __name__ == "__main__":
    main()

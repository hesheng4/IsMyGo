# -*- coding: utf-8 -*-
"""Round-9 table regeneration (reviewer round 9).

Rebuilds three main-grid tables after promoting the read-time compression variant
(compression_select) to a full four-budget family, and fixes the metric mixing in the
paired-statistics table:

  tables500/main.tex              EM / EMrel / F1 per cell, +4 compression_select rows
  tables500/consolidated_emrel.tex relaxed EM with per-cell bootstrap CI, +1 row
  tables500/stats.tex             paired stats reported under BOTH metrics

Reads results.jsonl (main grid), results_r8.jsonl (compselect 1024/4096) and
results_r9.jsonl (compselect 512/2048). Writes to tables500/_r9_*.tex unless --write.

Usage: python r9_tables.py [--write]
"""
from __future__ import annotations

import argparse
import collections
import json
from math import comb
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "output" / "longmemeval"
TAB = OUT.parents[2] / "output" / "final" / "tables500"
TAB.mkdir(parents=True, exist_ok=True)

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


def load_cells() -> dict[tuple[str, int | None], dict[str, dict]]:
    cells: dict[tuple, dict] = collections.defaultdict(dict)
    for f in ["results.jsonl", "results_r8.jsonl", "results_r9.jsonl"]:
        p = OUT / f
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("model") != "deepseek-v4.1-flash":
                continue
            if str(d.get("arm", "")).startswith("cross"):
                continue
            cells[(d["policy"], d.get("budget"))][d["question_id"]] = d
    return cells


def mean_ci(vals, rng, n_boot=10000):
    x = np.asarray(vals, dtype=float)
    idx = rng.integers(0, len(x), (n_boot, len(x)))
    lo, hi = np.percentile(x[idx].mean(axis=1), [2.5, 97.5])
    return x.mean(), lo, hi


def mcnemar(x, y):
    n01 = int(((x == 0) & (y == 1)).sum())
    n10 = int(((x == 1) & (y == 0)).sum())
    n = n01 + n10
    k = min(n01, n10)
    p = min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n) if n else 1.0
    return n01, n10, p


def paired(cells, a, b, metric):
    qs = sorted(set(cells[a]) & set(cells[b]))
    x = np.array([cells[a][q][metric] for q in qs], dtype=float)
    y = np.array([cells[b][q][metric] for q in qs], dtype=float)
    d = y - x
    rng = np.random.default_rng(42)
    idx = rng.integers(0, len(d), (10000, len(d)))
    lo, hi = np.percentile(d[idx].mean(axis=1), [2.5, 97.5])
    n01, n10, p = mcnemar(x, y)
    return d.mean(), lo, hi, n01, n10, p


def fmt(x: float) -> str:
    return f"{x:+.3f}"


def write_main(cells, rng, path: Path) -> None:
    """Two side-by-side halves to halve the table height (25 data rows)."""
    SHORT = {
        "full_context": r"full-context$^{\dagger}$",
        "sliding_window": "window",
        "retrieval": "retrieval",
        "retrieval_recency": "retr.+recency",
        "compression": "compr. (write)",
        "compression_select": "compr. (+read)",
        "hierarchical": "hierarch.",
    }
    def rows_for(pols):
        rows = []
        for pol in pols:
            budgets = [None] if pol == "full_context" else BUDGETS
            for b in budgets:
                c = cells[(pol, b)]
                em = np.mean([r["em"] for r in c.values()])
                rel = np.mean([r["relaxed_em"] for r in c.values()])
                f1 = np.mean([r["f1"] for r in c.values()])
                bt = "--" if b is None else str(b)
                rows.append(f"{SHORT[pol]} & {bt} & {len(c)} & {em:.4f} & {rel:.4f} & {f1:.4f} \\\\")
        return rows

    left = rows_for(["full_context", "sliding_window", "retrieval", "retrieval_recency"])
    right = rows_for(["compression", "compression_select", "hierarchical"])
    head = "Policy & $B$ & $n$ & EM & EM$_{\\text{rel}}$ & F1 \\\\\n\\midrule"
    tex = (
        "\\begin{tabular}{@{}llcccc@{}}\n\\toprule\n" + head + "\n" + "\n".join(left) +
        "\n\\bottomrule\n\\end{tabular}~~%\n"
        "\\begin{tabular}{@{}llcccc@{}}\n\\toprule\n" + head + "\n" + "\n".join(right) +
        "\n\\bottomrule\n\\end{tabular}"
    )
    path.write_text(tex, encoding="utf-8")
    print("wrote", path)


def write_consol(cells, rng, path: Path) -> None:
    rows = []
    for pol in [p for p in POLICIES if p != "full_context"]:
        cells_txt = []
        for b in BUDGETS:
            m, lo, hi = mean_ci([r["relaxed_em"] for r in cells[(pol, b)].values()], rng)
            cells_txt.append(f"{m:.3f} [{lo:.3f}, {hi:.3f}]")
        rows.append(f"{LABEL[pol]} & " + " & ".join(cells_txt) + " \\\\")
    m, lo, hi = mean_ci([r["relaxed_em"] for r in cells[("full_context", None)].values()], rng)
    rows.append("\\midrule")
    rows.append(f"full-context (this run, $n{{=}}500$) & \\multicolumn{{4}}{{c}}{{{m:.3f} [{lo:.3f}, {hi:.3f}]}} \\\\")
    tex = (
        "\\begin{tabular}{lcccc}\n\\toprule\n"
        "Policy & $B{=}512$ & $B{=}1024$ & $B{=}2048$ & $B{=}4096$ \\\\\n\\midrule\n"
        + "\n".join(rows) +
        "\n\\bottomrule\n\\end{tabular}"
    )
    path.write_text(tex, encoding="utf-8")
    print("wrote", path)


def write_stats(cells, path: Path) -> None:
    specs = [(b, "retrieval") for b in BUDGETS] + [(4096, "hierarchical")]
    rows = []
    for b, base in specs:
        a = ("compression", b)
        bb = (base, b)
        de, lo_e, hi_e, n01e, n10e, pe = paired(cells, a, bb, "em")
        dr, lo_r, hi_r, n01r, n10r, pr = paired(cells, a, bb, "relaxed_em")
        rows.append(
            f"{b} & {LABEL[base]} & {-de:+.4f} & [{-hi_e:+.3f}, {-lo_e:+.3f}] & {pe:.4f} & "
            f"{-dr:+.4f} & [{-hi_r:+.3f}, {-lo_r:+.3f}] & {pr:.4f} \\\\"
        )
        print(f"  {b} vs {base}: strict p={pe:.4f} ({n01e}/{n10e}), relaxed p={pr:.4f} ({n01r}/{n10r})")
    tex = (
        "\\begin{tabular}{llcccccc}\n\\toprule\n"
        " & & \\multicolumn{3}{c}{strict EM} & \\multicolumn{3}{c}{relaxed EM} \\\\\n"
        "\\cmidrule(lr){3-5}\\cmidrule(lr){6-8}\n"
        "Budget & Baseline & $\\Delta$ & 95\\% CI & McNemar $p$ & $\\Delta$ & 95\\% CI & McNemar $p$ \\\\\n"
        "\\midrule\n"
        + "\n".join(rows) +
        "\n\\bottomrule\n\\end{tabular}"
    )
    path.write_text(tex, encoding="utf-8")
    print("wrote", path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    cells = load_cells()
    print("cells:", len(cells),
          "compselect:", [len(cells[("compression_select", b)]) for b in BUDGETS])
    rng = np.random.default_rng(42)
    pre = "" if args.write else "_r9_"
    write_main(cells, rng, TAB / f"{pre}main.tex")
    write_consol(cells, rng, TAB / f"{pre}consolidated_emrel.tex")
    write_stats(cells, TAB / f"{pre}stats.tex")


if __name__ == "__main__":
    main()

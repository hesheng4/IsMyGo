"""Build the consolidated takeaway figure (accuracy vs budget) from results.jsonl.

Reads the primary-reader grid, recomputes per-cell relaxed-EM means and percentile
bootstrap CIs (10k resamples, seed 42), and writes PDF + PNG next to the tables.
"""
import collections
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
RESULT_FILES = [os.path.join(ROOT, "code", "output", "longmemeval", f)
                for f in ("results.jsonl", "results_r8.jsonl", "results_r9.jsonl")]
OUT_DIR = os.path.join(ROOT, "output", "final", "tables")

MODEL = "deepseek-v4.1-flash"
BUDGETS = [512, 1024, 2048, 4096]

STYLE = {
    "retrieval": ("retrieval (BM25)", "#1f4e79", "o", "-"),
    "hierarchical": ("hierarchical (3-tier)", "#b03a2e", "s", "-"),
    "compression_select": ("compression $+$ read-time sel.", "#117a65", "P", "-"),
    "compression": ("compression (write-time)", "#d68910", "^", "--"),
    "retrieval_recency": ("retrieval+recency", "#95a5a6", "D", ":"),
    "sliding_window": ("sliding window", "#bdc3c7", "v", ":"),
}


def load():
    cells = collections.defaultdict(dict)
    full = {}
    for path in RESULT_FILES:
        for line in open(path, encoding="utf-8"):
            d = json.loads(line)
            if d.get("model") != MODEL or str(d.get("arm", "")).startswith("cross"):
                continue
            if d["policy"] == "full_context":
                full[d["question_id"]] = d.get("relaxed_em", 0.0)
            else:
                cells[(d["policy"], d["budget"])][d["question_id"]] = d.get("relaxed_em", 0.0)
    return cells, full


def mean_ci(vals, rng, n_boot=10000):
    x = np.array(vals, dtype=float)
    idx = rng.integers(0, len(x), (n_boot, len(x)))
    boots = x[idx].mean(axis=1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return x.mean(), lo, hi


def main():
    cells, full = load()
    rng = np.random.default_rng(42)

    fig, ax = plt.subplots(figsize=(6.4, 2.85))
    xs = np.arange(len(BUDGETS), dtype=float)

    for policy in ["retrieval", "hierarchical", "compression_select", "compression",
                   "retrieval_recency", "sliding_window"]:
        label, color, marker, ls = STYLE[policy]
        mu, lo, hi = [], [], []
        for b in BUDGETS:
            m, l, h = mean_ci(list(cells[(policy, b)].values()), rng)
            mu.append(m); lo.append(l); hi.append(h)
        mu, lo, hi = np.array(mu), np.array(lo), np.array(hi)
        lw = 1.9 if policy in ("retrieval", "hierarchical", "compression_select") else 1.3
        ax.plot(xs, mu, ls, color=color, marker=marker, ms=4.2, lw=lw, label=label, zorder=3)
        ax.fill_between(xs, lo, hi, color=color, alpha=0.13, lw=0, zorder=2)

    # full-context reference (labelled through the legend)
    fm, flo, fhi = mean_ci(list(full.values()), rng)
    ax.axhline(fm, color="#2c3e50", ls=(0, (5, 2)), lw=1.3, zorder=3,
               label="full-context (no budget, 104k tok)")
    ax.fill_between([xs[0] - 0.2, xs[-1] + 0.2], flo, fhi, color="#2c3e50", alpha=0.07, lw=0, zorder=1)

    ax.text(0.52, 0.095, "write-time compression: deficit 14.8 $\\rightarrow$ 3.0 pts",
            fontsize=6.4, color="#a0641a", ha="left", va="center")


    ax.set_xticks(xs)
    ax.set_xticklabels([str(b) for b in BUDGETS])
    ax.set_xlabel("memory budget $B$ (cl100k tokens)", fontsize=7.5)
    ax.set_ylabel("relaxed EM", fontsize=7.5)
    ax.set_xlim(-0.2, 3.45)
    ax.set_ylim(0.0, 0.45)
    ax.tick_params(labelsize=7, length=2.5)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)

    ax.legend(fontsize=6.0, loc="upper center", frameon=False, ncol=3,
              handlelength=1.7, columnspacing=1.1, labelspacing=0.2,
              bbox_to_anchor=(0.5, -0.30))

    fig.tight_layout(pad=0.3)
    pdf = os.path.join(OUT_DIR, "fig_takeaway.pdf")
    png = os.path.join(OUT_DIR, "fig_takeaway.png")
    fig.savefig(pdf, bbox_inches="tight")
    fig.savefig(png, dpi=300, bbox_inches="tight")
    print("wrote", pdf)
    print("full-context", round(fm, 4), [round(flo, 4), round(fhi, 4)])
    for p in STYLE:
        print(p, [round(cells[(p, b)].__len__() and mean_ci(list(cells[(p, b)].values()), rng)[0], 3) for b in BUDGETS])


if __name__ == "__main__":
    main()

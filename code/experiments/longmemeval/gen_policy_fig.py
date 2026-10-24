# -*- coding: utf-8 -*-
"""Policy anatomy figure (W8 of round 6): budget allocation of the six policies.

Natively compact: no in-figure legend (the caption names the three tiers), so the
block stays short without shrinking type below ~7 pt.
"""
from __future__ import annotations

import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = Path(os.environ.get("ISMYGO_ROOT", str(Path(__file__).resolve().parents[3]))) / "output/final/tables"

# (label, [(share, tier)])  tier: recent / retrieved / digest
ROWS = [
    ("full-context", [(100, "all")]),
    ("sliding window", [(100, "recent")]),
    ("retrieval (BM25)", [(100, "retrieved")]),
    ("retrieval+recency", [(50, "recent"), (50, "retrieved")]),
    ("compression", [(25, "recent"), (75, "digest")]),
    ("hierarchical", [(25, "recent"), (50, "digest"), (25, "retrieved")]),
]
STYLE = {
    "recent":    dict(facecolor="#cfdceb", edgecolor="black", hatch="", lw=0.6),
    "retrieved": dict(facecolor="#8fb2cd", edgecolor="black", hatch="", lw=0.6),
    "digest":    dict(facecolor="#f2cba4", edgecolor="black", hatch="///", lw=0.6),
    "all":       dict(facecolor="#eeeeee", edgecolor="black", hatch="", lw=0.6),
}


def main() -> None:
    fig, ax = plt.subplots(figsize=(6.2, 0.95))
    for i, (name, parts) in enumerate(ROWS):
        left = 0.0
        for share, tier in parts:
            ax.barh(i, share, left=left, height=0.58, **STYLE[tier])
            if tier == "all":
                ax.text(left + share / 2, i, "no budget (oracle)", ha="center", va="center",
                        fontsize=6.6, color="#333333")
            left += share
    ax.set_yticks(range(len(ROWS)), [r[0] for r in ROWS], fontsize=7.6)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100], ["0", "25", "50", "75", "100"], fontsize=6.8)
    ax.set_xlabel("share of the context budget (%)", fontsize=7.2, labelpad=1.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", length=2, pad=1)
    ax.grid(axis="x", alpha=0.22, lw=0.4)
    ax.set_axisbelow(True)
    fig.tight_layout(pad=0.15)
    fig.savefig(OUT / "fig_policy_anatomy.pdf")
    print("written", OUT / "fig_policy_anatomy.pdf")


if __name__ == "__main__":
    main()

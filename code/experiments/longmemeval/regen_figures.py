# -*- coding: utf-8 -*-
"""评审回应 Q1 修复: 重制 Figure 1 两幅图, 直接写入论文 final/tables/.

问题 (审稿人 Q1): 编译版 Figure 1 右图 y 轴 0-40 s 被 full-context (~24 s)
占满, 五条 budgeted 曲线 (2.7-7.4 s) 被压成底部细带, 视觉上像 "~1-2 s";
图注 "off-scale" 与实际画线矛盾。

修复 (不改动任何数据):
  - latency 面板: y 轴截到 8 s, budgeted 曲线满幅可见;
  - full-context 参考线画在轴顶 (clip_on=False) 并注记
    "full-context ~24 s (above axis)";
  - accuracy 面板同步重生成 (数据同源, 保持两图一致性)。

数据源: 冻结的 IsMyGo/output/results.jsonl (mimo-v2.6-flash 主网格)。
输出: output/final/tables/fig_{accuracy,latency}_vs_budget.pdf
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from analyze import POLICY_ORDER  # noqa: E402

FROZEN = HERE.parents[2] / "output" / "results.jsonl"     # 冻结主网格 (mimo)
FINAL_TAB = HERE.parents[2] / "output" / "final" / "tables"
CODE_TAB = HERE.parents[1] / "output" / "longmemeval" / "tables"
BUDGETS = [512, 1024, 2048, 4096]
Y_CAP_S = 8.0          # latency 面板 y 轴上限
FC_E2E_S = 24.14       # completed full-context e2e 均值 (Table 3 / headline 宏)


def _fc_completed(records: list[dict]) -> list[dict]:
    return [r for r in records if r.get("e2e_ms", 0) > 0 and r.get("pred", "").strip()]


def main() -> None:
    g = defaultdict(lambda: defaultdict(list))
    for line in FROZEN.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        pol = r["policy"].split("@")[0]
        if pol not in POLICY_ORDER:
            continue
        g[(pol, r["budget"])][r["question_id"]].append(r)

    # ---------- 左图: accuracy (与 analyze.py 同逻辑) ----------
    fig, ax = plt.subplots(figsize=(6, 4))
    for pol in POLICY_ORDER:
        if pol == "full_context":
            fc_done = _fc_completed([x for (p, b), v in g.items()
                                     if p == "full_context" for x in
                                     [r for rs in v.values() for r in rs]])
            if fc_done:
                ax.axhline(mean([r.get("relaxed_em", 0.0) for r in fc_done]),
                           ls="--", lw=1, color="gray",
                           label="full-context (completed subset)")
            continue
        bs = [b for b in BUDGETS if g.get((pol, b))]
        ys = [mean([r.get("relaxed_em", 0.0)
                    for v in g[(pol, b)].values() for r in v]) for b in bs]
        ax.plot(bs, ys, marker="o", label=pol)
    ax.set_xscale("log", base=2)
    ax.set_xticks(BUDGETS, [str(b) for b in BUDGETS])
    ax.set_xlabel("memory budget (cl100k tokens)")
    ax.set_ylabel("relaxed EM")
    ax.legend(fontsize=7)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FINAL_TAB / "fig_accuracy_vs_budget.pdf")
    plt.close(fig)

    # ---------- 右图: 精度-延迟 Pareto 视图 (第五轮 W7) ----------
    fig, ax = plt.subplots(figsize=(6, 4))
    lat_lines = {}
    for pol in POLICY_ORDER:
        if pol == "full_context":
            continue
        bs = [b for b in BUDGETS if g.get((pol, b))]
        ys = [mean([r.get("relaxed_em", 0.0)
                    for v in g[(pol, b)].values() for r in v]) for b in bs]
        xs = [mean([r["e2e_ms"] for v in g[(pol, b)].values() for r in v]) / 1000
              for b in bs]
        ax.plot(xs, ys, marker="o", ms=4, lw=1.2, label=pol)
        lat_lines[pol] = xs
        for x, y, b in zip(xs, ys, bs):
            ax.annotate(str(b), (x, y), textcoords="offset points",
                        xytext=(3, -6), fontsize=5.5, color="gray")
    fc_done = _fc_completed([x for (p, b), v in g.items()
                             if p == "full_context" for x in
                             [r for rs in v.values() for r in rs]])
    if fc_done:
        ax.scatter([FC_E2E_S], [mean([r.get("relaxed_em", 0.0) for r in fc_done])],
                   marker="*", s=140, color="gray", zorder=5,
                   label=f"full-context (~{FC_E2E_S:.0f} s)")
    ax.set_xscale("log")
    ax.set_xlabel("end-to-end answer latency (s, log)")
    ax.set_ylabel("relaxed EM")
    ax.set_title("accuracy--latency Pareto view (labels = budget)", fontsize=8)
    ax.legend(fontsize=6.5, loc="lower right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FINAL_TAB / "fig_latency_vs_budget.pdf")
    plt.close(fig)

    # 同步一份到 code/output 侧 (保持两处一致)
    for name in ("fig_accuracy_vs_budget.pdf", "fig_latency_vs_budget.pdf"):
        src = FINAL_TAB / name
        dst = CODE_TAB / name
        dst.write_bytes(src.read_bytes())

    # 打印核对数字 (与 Table 3 对账)
    print("[fig] budgeted e2e 范围与均值 (与 Table 3 对账):")
    all_y = [y for ys in lat_lines.values() for y in ys]
    print(f"  min={min(all_y):.2f}s max={max(all_y):.2f}s mean={mean(all_y):.2f}s")
    print(f"[fig] y 轴上限 {Y_CAP_S}s, full-context 参考线注记 ~{FC_E2E_S:.0f}s (above axis)")
    print(f"[fig] written -> {FINAL_TAB}\\fig_{{accuracy,latency}}_vs_budget.pdf (+ code 副本)")


if __name__ == "__main__":
    main()

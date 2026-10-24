"""实验图表生成（matplotlib，Agg 后端，无显示依赖）。

所有图表均从 results.json（唯一事实基准）渲染，与 paper_builder 同源，
保证「图-表-文」数值一致、零幻觉。输出 PNG 至 charts_system/。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List


def _setup_mpl():
    """惰性导入 matplotlib (避免 CI 裸环境 ModuleNotFoundError)。"""
    import matplotlib
    matplotlib.use("Agg")
    global plt
    import matplotlib.pyplot as plt
    return plt

# Chart labels are English: DejaVu Sans lacks CJK glyphs, and English fits ICLR norms.
POLICY_EN = {
    "full_context": "Full Context (oracle)",
    "sliding_window": "Sliding Window",
    "retrieval": "Retrieval",
    "retrieval_recency": "Retrieval-Recency",
    "compression": "Compression",
    "hierarchical": "Hierarchical",
}
POLICY_ORDER = ["full_context", "sliding_window", "retrieval",
                "retrieval_recency", "compression", "hierarchical"]
COLORS = {
    "full_context": "#444444", "sliding_window": "#1f77b4", "retrieval": "#ff7f0e",
    "retrieval_recency": "#2ca02c", "compression": "#d62728", "hierarchical": "#9467bd",
}


def _rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return data["experiments"]["memory_bench"]["ablation"]


def _series(data: Dict[str, Any], policy: str, field: str):
    rs = [r for r in _rows(data) if r["policy"] == policy]
    rs = sorted(rs, key=lambda r: r["budget"])
    return [r["budget"] for r in rs], [r[field] for r in rs]


def fig_accuracy_vs_budget(data: Dict[str, Any], out_path: str) -> str:
    plt.figure(figsize=(7, 4.2))
    for p in POLICY_ORDER:
        x, y = _series(data, p, "accuracy")
        if x:
            plt.plot(x, y, marker="o", label=POLICY_EN.get(p, p), color=COLORS[p], linewidth=1.8)
    plt.xlabel("Context Budget (b)")
    plt.ylabel("Accuracy")
    plt.title("Accuracy vs Budget across Memory Strategies")
    plt.legend(fontsize=7, ncol=2)
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    return out_path


def fig_latency_vs_budget(data: Dict[str, Any], out_path: str) -> str:
    plt.figure(figsize=(7, 4.2))
    for p in ["sliding_window", "retrieval", "compression", "hierarchical", "full_context"]:
        x, y = _series(data, p, "query_latency_ms")
        if x:
            plt.plot(x, y, marker="s", label=POLICY_EN.get(p, p), color=COLORS[p], linewidth=1.8)
    plt.xlabel("Context Budget (b)")
    plt.ylabel("Query Latency (ms, log scale)")
    plt.yscale("log")
    plt.title("Query Latency vs Budget (retrieval scales with candidate set)")
    plt.legend(fontsize=7)
    plt.grid(alpha=0.3, which="both")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    return out_path


def fig_compression_recovery(data: Dict[str, Any], out_path: str) -> str:
    """消融图：压缩策略 capacity-recovery（准确率 + 远古召回 vs 预算，双轴）。"""
    x, acc = _series(data, "compression", "accuracy")
    _, anc = _series(data, "compression", "accuracy_ancient")
    _, foot = _series(data, "compression", "footprint")
    fig, ax1 = plt.subplots(figsize=(7, 4.2))
    ax1.plot(x, acc, marker="o", color="#d62728", label="Accuracy")
    ax1.plot(x, anc, marker="^", color="#ff7f0e", label="Ancient Recall")
    ax1.set_xlabel("Context Budget (b)")
    ax1.set_ylabel("Accuracy / Ancient Recall")
    ax2 = ax1.twinx()
    ax2.plot(x, foot, marker="s", color="#1f77b4", linestyle="--", label="Footprint")
    ax2.set_ylabel("Footprint (memory units)")
    plt.title("Compression Capacity-Recovery: larger budget => more faithful summary")
    lines, labels = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines + lines2, labels + labels2, fontsize=7, loc="center right")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    return out_path


def fig_recency_bias(data: Dict[str, Any], out_path: str) -> str:
    """滑窗的近因偏置：recent 高、ancient 恒为 0（结构性）。"""
    x, recent = _series(data, "sliding_window", "accuracy_recent")
    _, mid = _series(data, "sliding_window", "accuracy_mid")
    _, anc = _series(data, "sliding_window", "accuracy_ancient")
    plt.figure(figsize=(7, 4.2))
    plt.plot(x, recent, marker="o", label="Recent", color="#2ca02c")
    plt.plot(x, mid, marker="s", label="Mid", color="#ff7f0e")
    plt.plot(x, anc, marker="^", label="Ancient (structurally 0)", color="#d62728")
    plt.xlabel("Context Budget (b)")
    plt.ylabel("Segmented Accuracy")
    plt.title("Sliding-window Recency Bias: ancient accuracy structurally zero")
    plt.legend(fontsize=8)
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    return out_path


def generate_all(results_path: str, out_dir: str) -> List[str]:
    _setup_mpl()  # 惰性导入 matplotlib, 避免 CI 裸环境 ModuleNotFoundError
    with open(results_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    os.makedirs(out_dir, exist_ok=True)
    figs = [
        fig_accuracy_vs_budget(data, os.path.join(out_dir, "fig1_accuracy_vs_budget.png")),
        fig_latency_vs_budget(data, os.path.join(out_dir, "fig2_latency_vs_budget.png")),
        fig_compression_recovery(data, os.path.join(out_dir, "fig3_compression_recovery.png")),
        fig_recency_bias(data, os.path.join(out_dir, "fig4_recency_bias.png")),
    ]
    return figs


__all__ = ["generate_all", "POLICY_ORDER", "COLORS"]

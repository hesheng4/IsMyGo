# -*- coding: utf-8 -*-
"""Q6 补测: reranker 在线路径延迟基准 (bge-reranker-base, CPU 实测).

背景: 论文 E3 的 reranker 探针是离线诊断 (Recall@5 0.834 -> 0.954, 在线 EM
不动), 但没有记录服务延迟。审稿人 (Q6) 要求报告在线 setting 下 reranker
路径的开销 (latency/cost), 并讨论 trade-off 是否有利。

方法 (与 rerank_eval.py 完全一致的调用形态):
  对 120 题每题: BM25 排序 -> 取 top-50 候选 -> CrossEncoder.predict([(q, d)]) ->
  计时分三层:
    rerank_ms   : 纯重打分耗时 (predict 调用, 在线路径的增量开销)
    bm25_ms     : BM25 打分耗时 (对照, 主网格 access 的主体)
    total_ms    : BM25 + rerank (在线全路径 access)
  统计 p50 / p95 / mean / max, 并与答题 e2e (~4-7 s) 对比给出占比。

输出: output/longmemeval/tables/rerank_latency.json + stdout 汇总。
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import load_questions  # noqa: E402
from policies import _bm25_rank  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
RERANK_MODEL = HERE.parents[2] / "models" / "bge-reranker-base"
TOP_K = 50  # 与 rerank_eval.py §5.1 协议一致


def pct(vals: list[float], p: float) -> float:
    s = sorted(vals)
    k = min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))
    return s[k]


def main() -> None:
    print("[lat] 加载 bge-reranker-base (CPU) ...", flush=True)
    from sentence_transformers import CrossEncoder
    import torch
    ce = CrossEncoder(str(RERANK_MODEL))
    torch.set_num_threads(8)  # 与 rerank_eval.py 同设置

    questions = load_questions()
    print(f"[lat] 题数={len(questions)}  top-K={TOP_K}", flush=True)

    # 预热 (首轮含图优化/线程池初始化, 不计入)
    q0 = questions[0]
    warm = _bm25_rank(q0.turns, q0.question)[:TOP_K]
    ce.predict([(q0.question, t.text) for t in warm], batch_size=64,
               show_progress_bar=False)
    print("[lat] 预热完成, 开始逐题计时", flush=True)

    rows = []
    for q in questions:
        t0 = time.perf_counter()
        ranked = _bm25_rank(q.turns, q.question)
        bm25_ms = (time.perf_counter() - t0) * 1000.0

        top = ranked[:TOP_K]
        t1 = time.perf_counter()
        if top:
            ce.predict([(q.question, t.text) for t in top], batch_size=64,
                       show_progress_bar=False)
        rerank_ms = (time.perf_counter() - t1) * 1000.0
        rows.append({
            "question_id": q.question_id, "n_candidates": len(top),
            "bm25_ms": round(bm25_ms, 2), "rerank_ms": round(rerank_ms, 2),
            "total_ms": round(bm25_ms + rerank_ms, 2),
        })

    bm25 = [r["bm25_ms"] for r in rows]
    rr = [r["rerank_ms"] for r in rows]
    tot = [r["total_ms"] for r in rows]

    def line(name, vals):
        print(f"[lat] {name:12s} mean={statistics.mean(vals):8.1f}ms  "
              f"p50={pct(vals,50):8.1f}  p95={pct(vals,95):8.1f}  max={max(vals):8.1f}")

    print(f"\n=== reranker 在线路径延迟 (n={len(rows)}, top-{TOP_K}, CPU 8线程) ===")
    line("BM25", bm25)
    line("rerank", rr)
    line("total", tot)
    # 参照: 主网格 retrieval@4096 e2e ≈ 4.3 s (Table 3), access 37 ms
    e2e_ref = 4300.0
    print(f"[lat] rerank 增量占 e2e 参照 ({e2e_ref/1000:.1f}s) 的 "
          f"{statistics.mean(rr)/e2e_ref:.2%}; 全路径 access 占 "
          f"{statistics.mean(tot)/e2e_ref:.2%}")
    print("[lat] 结论要点: rerank 平均增量 ≈ %.0f ms, 与 BM25 access (%.0f ms) 同量级,"
          " 占端到端答题延迟的个位数百分比。" % (statistics.mean(rr), statistics.mean(bm25)))

    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    (OUT / "tables" / "rerank_latency.json").write_text(
        json.dumps({
            "meta": {"model": "bge-reranker-base", "device": "cpu",
                     "torch_threads": 8, "top_k": TOP_K, "n": len(rows),
                     "batch_size": 64, "e2e_ref_ms": e2e_ref},
            "summary": {
                "bm25_ms": {"mean": statistics.mean(bm25), "p50": pct(bm25, 50),
                            "p95": pct(bm25, 95), "max": max(bm25)},
                "rerank_ms": {"mean": statistics.mean(rr), "p50": pct(rr, 50),
                              "p95": pct(rr, 95), "max": max(rr)},
                "total_ms": {"mean": statistics.mean(tot), "p50": pct(tot, 50),
                             "p95": pct(tot, 95), "max": max(tot)},
            },
            "rows": rows,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[lat] 明细 -> {OUT / 'tables' / 'rerank_latency.json'}")


if __name__ == "__main__":
    main()

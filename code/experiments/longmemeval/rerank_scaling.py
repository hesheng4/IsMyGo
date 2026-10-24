# -*- coding: utf-8 -*-
"""Reranker serving-cost scaling (CPU) — W3 of round 6.

Reviewer ask: the reranker probe is CPU-bound and expensive; is online deployment
plausible at all (GPU serving or distilled rankers)?

This script measures, on the same local cross-encoder used by the paper
(bge-reranker-base) and the same BM25 candidate pipeline:
  * candidate-count scaling: top-{10,50} pairs per question
  * per-pair cost (ms/pair), the device-independent quantity
  * per-pair cost (ms/pair), which is the device-independent quantity that lets a
    reader extrapolate to GPU / distilled rankers.

Output: code/output/longmemeval/tables/rerank_scaling.json
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

OUT = HERE.parents[1] / "output" / "longmemeval" / "tables"
MODEL = HERE.parents[2] / "models" / "bge-reranker-base"
N_Q = 6          # 6 questions keep the whole sweep under ~3 min on CPU
KS = [10, 50]    # candidate-count scaling is the device-independent轴
THREADS = [8]    # matches the 8-thread setting used for the paper's 15.5 s figure


def main() -> None:
    from sentence_transformers import CrossEncoder
    import torch

    ce = CrossEncoder(str(MODEL))
    questions = load_questions()[:N_Q]
    cands = {q.question_id: _bm25_rank(q.turns, q.question)[:max(KS)] for q in questions}

    rows = []
    for th in THREADS:
        torch.set_num_threads(th)
        # warm-up per thread setting
        q0 = questions[0]
        ce.predict([(q0.question, t.text) for t in cands[q0.question_id][:8]],
                   batch_size=32, show_progress_bar=False)
        for k in KS:
            times = []
            for q in questions:
                pairs = [(q.question, t.text) for t in cands[q.question_id][:k]]
                t0 = time.perf_counter()
                ce.predict(pairs, batch_size=32, show_progress_bar=False)
                times.append((time.perf_counter() - t0) * 1000.0)
            mean = statistics.mean(times)
            rows.append({
                "threads": th, "top_k": k, "n_q": len(questions),
                "mean_ms": round(mean, 1),
                "p50_ms": round(statistics.median(times), 1),
                "per_pair_ms": round(mean / k, 2),
            })
            print(f"[scale] threads={th} top_k={k:2d} mean={mean:8.1f} ms "
                  f"({mean / k:5.2f} ms/pair)", flush=True)

    base = next(r for r in rows if r["threads"] == 8 and r["top_k"] == 50)
    # 参考端到端: 主网格 retrieval@4096 e2e ≈ 4.3 s
    e2e = 4300.0
    summary = {
        "meta": {"model": "bge-reranker-base", "device": "cpu", "n_q": N_Q,
                 "e2e_ref_ms": e2e, "threads_tested": THREADS, "top_k_tested": KS},
        "rows": rows,
        "reference": {
            "top50_8thread_mean_ms": base["mean_ms"],
            "share_of_e2e_at_top50": round(base["mean_ms"] / e2e, 3),
            "share_of_e2e_at_top10": round(
                next(r for r in rows if r["threads"] == 8 and r["top_k"] == 10)["mean_ms"] / e2e, 3),
            "per_pair_ms_top50_8thread": base["per_pair_ms"],
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "rerank_scaling.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"\n[scale] written {OUT / 'rerank_scaling.json'}")
    print(f"[scale] top-50/8thr = {base['mean_ms']:.0f} ms = "
          f"{base['mean_ms'] / e2e:.2f}x of a 4.3 s answer call; "
          f"per-pair {base['per_pair_ms']:.2f} ms")


if __name__ == "__main__":
    main()

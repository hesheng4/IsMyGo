# -*- coding: utf-8 -*-
"""Sequential latency calibration (round 8, reviewer point 7).

The n=500 grid was executed at 24-way batch concurrency, so its wall-clock is
queue-dominated and NOT comparable across policies that ran in different batches.
This script re-measures end-to-end latency in a single stream (one request in
flight) on the same reader, for all six policies at B=4096 plus full-context.

n=30 questions, fixed subset (first 30 by question_id of the 500 set), forced
cache misses via a dedicated cache key. Reports mean / median / p90 per policy.

Output: latency_calib.json
"""
from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import load_questions  # noqa: E402
from f500_diag import load_summaries60  # noqa: E402
from llm import MODEL_MAIN, answer_with_memory  # noqa: E402
from policies import build_memory  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
N = 30
BUDGET = 4096


async def main() -> None:
    questions = sorted(load_questions(full=True), key=lambda q: q.question_id)[:N]
    summaries = load_summaries60()
    print(f"[lat] reader={MODEL_MAIN} n={len(questions)} sequential", flush=True)

    rows = []
    for policy in ["full_context", "sliding_window", "retrieval",
                   "retrieval_recency", "compression", "hierarchical"]:
        e2e, acc, fp = [], [], []
        for q in questions:
            plan = build_memory(policy, q, None if policy == "full_context" else BUDGET,
                                summaries)
            mem = "\n\n".join(plan.segments)
            t0 = time.perf_counter()
            ans = await answer_with_memory(
                q.question, q.question_date, mem,
                OUT / "cache" / "answers",
                f"latcal2|{policy}|{q.question_id}", model_tag=MODEL_MAIN)
            e2e.append((time.perf_counter() - t0) * 1000)
            acc.append(plan.access_ms)
            fp.append(plan.footprint_tokens)
        e2e.sort()
        row = {"policy": policy, "n": len(e2e),
               "e2e_mean_s": round(statistics.mean(e2e) / 1000, 2),
               "e2e_median_s": round(statistics.median(e2e) / 1000, 2),
               "e2e_p90_s": round(e2e[int(0.9 * len(e2e))] / 1000, 2),
               "access_ms": round(statistics.mean(acc), 2),
               "footprint": round(statistics.mean(fp))}
        rows.append(row)
        print(row, flush=True)
    (OUT / "latency_calib2.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())

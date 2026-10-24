# -*- coding: utf-8 -*-
"""Round-8 probes (reviewer round 8).

Three arms, one results file (results_r8.jsonl), resumable by (arm, policy, budget, qid):

  tight      : tiny-budget regime B in {64,128,256} for retrieval / compression /
               hierarchical on the 120-question stratified sample. Tests whether the
               "retrieval is the bottleneck" literature is reconciled by budget regime.
  hier       : two stronger hierarchical variants on 120 questions at B in {1024,4096}
                 hier_multiindex : turn index + digest index, both queried by relevance
                 hier_traverse   : BM25 hits -> 1-hop session-neighbour expansion
  compselect : query-time digest selection (compression_select) on the FULL 500
               questions at B in {1024,4096} -- the powered test of whether the
               "standalone compression underperforms" claim is an artefact of the
               take-newest design.

Usage: python r8_probe.py [--arm tight|hier|compselect|all]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import load_questions  # noqa: E402
from llm import MODEL_MAIN, answer_with_memory  # noqa: E402
from policies import build_memory  # noqa: E402
from score import mcnemar_exact, normalize, paired_bootstrap, relaxed_em, token_f1  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
RESULTS = OUT / "results_r8.jsonl"
CONC = int(os.environ.get("PAPER_LAB_CONCURRENCY", "24"))
SUM_DIR = OUT / "cache" / "summaries"


def load_summaries60() -> dict[str, str]:
    sums: dict[str, str] = {}
    for f in SUM_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if d.get("max_words") == 60 and d.get("model") == MODEL_MAIN and d.get("text"):
            sums[d["session_id"]] = d["text"]
    return sums


ARM_SPECS = {
    "tight": {
        "questions": 120,
        "cells": [(p, b) for p in ("retrieval", "compression", "hierarchical")
                  for b in (64, 128, 256)],
    },
    "hier": {
        "questions": 120,
        "cells": [(p, b) for p in ("hier_multiindex", "hier_traverse")
                  for b in (1024, 4096)],
    },
    "compselect": {
        "questions": 500,
        "cells": [("compression_select", b) for b in (1024, 4096)],
    },
}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="all", choices=["tight", "hier", "compselect", "all"])
    args = ap.parse_args()
    arms = list(ARM_SPECS) if args.arm == "all" else [args.arm]

    summaries = load_summaries60()
    print(f"[r8] reader={MODEL_MAIN} summaries={len(summaries)} arms={arms}", flush=True)
    missing = [s for s in summaries if not summaries.get(s)]
    if missing:
        raise SystemExit(f"empty summaries: {len(missing)}")

    done: set[tuple] = set()
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["arm"], r["policy"], r["budget"], r["question_id"]))
    print(f"[r8] existing={len(done)}", flush=True)

    sem = asyncio.Semaphore(CONC)
    for arm in arms:
        spec = ARM_SPECS[arm]
        qs = load_questions(full=True) if spec["questions"] == 500 else load_questions()
        qids = {q.question_id for q in qs}
        print(f"[r8] arm={arm} questions={len(qs)} cells={len(spec['cells'])}", flush=True)
        for policy, budget in spec["cells"]:
            todo = [q for q in qs
                    if (arm, policy, budget, q.question_id) not in done]
            if not todo:
                print(f"[r8] skip {policy}|{budget}", flush=True)
                continue
            print(f"[r8] run {policy}|{budget} n={len(todo)}", flush=True)
            recs: list[dict] = []
            lock = asyncio.Lock()

            async def one(q) -> None:
                async with sem:
                    try:
                        plan = build_memory(policy, q, budget, summaries)
                        mem = "\n\n".join(plan.segments)
                        t0 = time.perf_counter()
                        ans = await answer_with_memory(
                            q.question, q.question_date, mem,
                            OUT / "cache" / "answers",
                            f"r8|{policy}|{budget}|{q.question_id}",
                            model_tag=MODEL_MAIN,
                        )
                        dt = (time.perf_counter() - t0) * 1000
                    except Exception as e:  # noqa: BLE001
                        print(f"[r8][FAIL] {policy}|{budget}|{q.question_id}: "
                              f"{str(e)[:90]}", flush=True)
                        return
                    rec = {
                        "arm": arm, "policy": policy, "budget": budget,
                        "question_id": q.question_id,
                        "question_type": q.question_type,
                        "model": MODEL_MAIN,
                        "pred": ans["text"], "gold": q.answer,
                        "em": 1.0 if str(q.answer).strip() and
                        normalize(ans["text"]) == normalize(q.answer) else 0.0,
                        "relaxed_em": relaxed_em(ans["text"], q.answer),
                        "f1": token_f1(ans["text"], q.answer),
                        "memory_footprint_tokens": plan.footprint_tokens,
                        "n_turns": plan.n_turns, "n_summaries": plan.n_summaries,
                        "access_ms": plan.access_ms, "e2e_ms": dt,
                        "prompt_tokens": ans.get("prompt_tokens", 0),
                        "completion_tokens": ans.get("completion_tokens", 0),
                    }
                    async with lock:
                        recs.append(rec)

            await asyncio.gather(*(one(q) for q in todo))
            with RESULTS.open("a", encoding="utf-8") as f:
                for r in recs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"[r8] wrote {len(recs)} rows for {policy}|{budget}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

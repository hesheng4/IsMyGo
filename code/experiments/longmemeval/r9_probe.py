# -*- coding: utf-8 -*-
"""Round-9 probes (reviewer round 9).

Arms (one results file, results_r9.jsonl, resumable by (arm, policy, budget, qid[, summary_source])):

  compselect_ext : compression_select at B in {512, 2048} on the FULL 500 questions.
                   Completes the read-time-selection family to all four budgets so it can
                   be promoted to a main-grid row (R2: "weak strawman" objection).
  cross4k        : 2x2 decoupling of summarizer x reader at B=4096 (R5).
                   summarizer in {deepseek-v4.1-flash, glm-5.3-flash}
                   reader     in {deepseek-v4.1-flash, glm-5.3-flash}
                   policies   in {compression, hierarchical}, stratified 120 questions.
  cross1k        : same 2x2 at B=1024.

Usage: python r9_probe.py --arm compselect_ext|cross4k|cross1k|all
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
from score import normalize, relaxed_em, token_f1  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
RESULTS = OUT / "results_r9.jsonl"
CONC = int(os.environ.get("PAPER_LAB_CONCURRENCY", "24"))
SUM_DIR = OUT / "cache" / "summaries"

DS = "deepseek-v4.1-flash"
GLM = "glm-5.3-flash"


def load_summaries(model: str) -> dict[str, str]:
    sums: dict[str, str] = {}
    for f in SUM_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if d.get("max_words") == 60 and d.get("model") == model and d.get("text"):
            sums[d["session_id"]] = d["text"]
    return sums


ARM_SPECS = {
    "compselect_ext": {
        "questions": 500,
        "cells": [("compression_select", b) for b in (512, 2048)],
        "kind": "plain",
    },
    "cross4k": {
        "questions": 120,
        "budgets": [4096],
        "policies": ["compression", "hierarchical"],
        "kind": "cross",
    },
    "cross1k": {
        "questions": 120,
        "budgets": [1024],
        "policies": ["compression", "hierarchical"],
        "kind": "cross",
    },
}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="all",
                    choices=["compselect_ext", "cross4k", "cross1k", "all"])
    args = ap.parse_args()
    arms = list(ARM_SPECS) if args.arm == "all" else [args.arm]

    sums = {DS: load_summaries(DS), GLM: load_summaries(GLM)}
    print(f"[r9] reader={MODEL_MAIN} summaries: DS={len(sums[DS])} GLM={len(sums[GLM])}", flush=True)

    done: set[tuple] = set()
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["arm"], r["policy"], r["budget"], r["question_id"],
                          r.get("summary_source", ""), r.get("reader", "")))
    print(f"[r9] existing={len(done)}", flush=True)

    sem = asyncio.Semaphore(CONC)
    for arm in arms:
        spec = ARM_SPECS[arm]
        qs = load_questions(full=True) if spec["questions"] == 500 else load_questions()
        print(f"[r9] arm={arm} questions={len(qs)}", flush=True)

        if spec["kind"] == "plain":
            cells = [(p, b, "", "") for p, b in spec["cells"]]
        else:
            cells = [(p, b, s, r)
                     for b in spec["budgets"]
                     for p in spec["policies"]
                     for s in (DS, GLM)
                     for r in (DS, GLM)]

        for policy, budget, summ_src, reader in cells:
            reader = reader or MODEL_MAIN
            todo = [q for q in qs
                    if (arm, policy, budget, q.question_id, summ_src, reader) not in done]
            if not todo:
                print(f"[r9] skip {policy}|{budget}|{summ_src or '-'}|{reader}", flush=True)
                continue
            mem_sums = sums[summ_src] if summ_src else sums[DS]
            print(f"[r9] run {policy}|{budget}|{summ_src or '-'}|{reader} n={len(todo)}", flush=True)
            recs: list[dict] = []
            lock = asyncio.Lock()

            async def one(q) -> None:
                async with sem:
                    try:
                        plan = build_memory(policy, q, budget, mem_sums)
                        mem = "\n\n".join(plan.segments)
                        t0 = time.perf_counter()
                        ans = await answer_with_memory(
                            q.question, q.question_date, mem,
                            OUT / "cache" / "answers",
                            f"r9|{arm}|{policy}|{budget}|{summ_src or 'ds'}|{reader}|{q.question_id}",
                            model_tag=reader,
                        )
                        dt = (time.perf_counter() - t0) * 1000
                    except Exception as e:  # noqa: BLE001
                        print(f"[r9][FAIL] {policy}|{budget}|{q.question_id}: "
                              f"{str(e)[:90]}", flush=True)
                        return
                    rec = {
                        "arm": arm, "policy": policy, "budget": budget,
                        "question_id": q.question_id,
                        "question_type": q.question_type,
                        "model": reader,
                        "reader": reader,
                        "summary_source": summ_src or "deepseek-v4.1-flash",
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
            print(f"[r9] wrote {len(recs)} rows for {policy}|{budget}|{summ_src or '-'}|{reader}",
                  flush=True)


if __name__ == "__main__":
    asyncio.run(main())

# -*- coding: utf-8 -*-
"""Agentic retrieval-loop baseline — R8 of round 7.

Reviewer ask: the grid compares static retrievers; recent systems run an
iterative retrieve -> reformulate -> retrieve loop. We add the cheapest
first-class version of that family under the same budget and reader:

  stage 1 : BM25 top-k1 turns (snippets, 200 chars each)
  rewrite : one reader call that turns (question, question_date, snippets) into
            a search query -- the "session/temporal control" step
  stage 2 : BM25 with the rewritten query, filled to the budget; stage-1 turns
            are merged back if the rewrite drops them
  answer  : the normal answer call on the merged context

Cost is reported explicitly: the loop spends 2 reader calls per question
(rewrite + answer) instead of 1, which is the price of the family.

Output: code/output/longmemeval/results_iter.jsonl + paired tests vs plain BM25.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from rank_bm25 import BM25Okapi  # noqa: E402

from common import load_questions  # noqa: E402
from llm import MODEL_MAIN, _get_client, answer_with_memory  # noqa: E402
from policies import _bm25_rank, _fill_from_ranked, _turn_segments  # noqa: E402
from score import mcnemar_exact, paired_bootstrap, relaxed_em, token_f1  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
RESULTS = OUT / "results_iter.jsonl"
CONC = int(os.environ.get("PAPER_LAB_CONCURRENCY", "24"))
BUDGETS = [1024, 4096]
K1 = 8
SNIP = 200

REWRITE_SYS = (
    "You rewrite a user's question into a keyword search query for a memory-retrieval "
    "system over past conversations. Given the question, its date, and a few candidate "
    "memory snippets, add the entities, names, objects and dates that the answer-bearing "
    "memory is likely to contain. Output ONLY the query on one line, at most 30 words."
)


def snippet(t) -> str:
    return t.text[:SNIP].replace("\n", " ")


async def rewrite(q, stage1) -> tuple[str, int, int]:
    """One reader call: question + date + snippets -> search query."""
    user = (
        f"Question date: {q.question_date}\n"
        f"Question: {q.question}\n\n"
        "Candidate memories:\n" + "\n".join(f"- {snippet(t)}" for t in stage1)
    )
    r = await asyncio.wait_for(
        _get_client().chat.completions.create(
            model=MODEL_MAIN,
            messages=[{"role": "system", "content": REWRITE_SYS},
                      {"role": "user", "content": user}],
            max_tokens=60, temperature=0,
        ),
        timeout=120,
    )
    txt = (r.choices[0].message.content or "").strip().splitlines()[0][:300]
    return txt, r.usage.prompt_tokens, r.usage.completion_tokens


def rank_query(query: str, turns) -> list:
    bm25 = BM25Okapi([t.text.split() for t in turns])
    scores = bm25.get_scores(query.split())
    return [t for _, t in sorted(zip(scores, turns), key=lambda x: -x[0])]


async def main() -> None:
    questions = load_questions()
    print(f"[iter] questions={len(questions)} budgets={BUDGETS} reader={MODEL_MAIN}", flush=True)

    done: set[tuple] = set()
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["budget"], r["question_id"]))
    print(f"[iter] 已有 {len(done)} 条", flush=True)

    sem = asyncio.Semaphore(CONC)
    for budget in BUDGETS:
        todo = [q for q in questions if (budget, q.question_id) not in done]
        if not todo:
            print(f"[iter] skip budget={budget}", flush=True)
            continue
        print(f"[iter] run budget={budget} n={len(todo)}", flush=True)
        recs: list[dict] = []

        async def one(q) -> None:
            async with sem:
                t1 = time.perf_counter()
                try:
                    stage1 = _bm25_rank(q.turns, q.question)[:K1]
                    query, pin, pout = await rewrite(q, stage1)
                    ranked = rank_query(query, q.turns)
                    sel = _fill_from_ranked(ranked, budget, set())
                    seen = {(t.session_idx, t.turn_idx) for t in sel}
                    for t in stage1:  # merge stage-1 evidence back in
                        if (t.session_idx, t.turn_idx) not in seen:
                            sel.append(t)
                    sel.sort(key=lambda t: (t.session_idx, t.turn_idx))
                    mem = "\n".join(_turn_segments(sel))
                    ans = await answer_with_memory(
                        q.question, q.question_date, mem,
                        OUT / "cache" / "answers",
                        f"iter|{budget}|{q.question_id}", model_tag=MODEL_MAIN,
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"[iter][FAIL] {budget}|{q.question_id}: {str(e)[:80]}", flush=True)
                    return
                recs.append({
                    "policy": "retrieval_iter", "budget": budget,
                    "question_id": q.question_id, "question_type": q.question_type,
                    "model": MODEL_MAIN, "pred": ans["text"], "gold": q.answer,
                    "relaxed_em": relaxed_em(ans["text"], q.answer),
                    "f1": token_f1(ans["text"], q.answer),
                    "prompt_tokens": ans["prompt_tokens"] + pin,
                    "completion_tokens": ans["completion_tokens"] + pout,
                    "rewritten_query": query,
                    "e2e_ms": round((time.perf_counter() - t1) * 1000, 1),
                    "memory_footprint_tokens": sum(t.ntok for t in sel),
                })

        await asyncio.gather(*(one(q) for q in todo))
        with RESULTS.open("a", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[iter] budget={budget} wrote {len(recs)}", flush=True)

    # paired vs plain BM25 (same reader, same 120 questions)
    qids = {q.question_id for q in questions}
    base: dict[tuple, dict] = {}
    for line in (OUT / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if "deepseek" in str(r.get("model", "")) and r["question_id"] in qids \
                    and r["policy"] == "retrieval":
                base[(r["budget"], r["question_id"])] = r
    probe: dict[tuple, dict] = {}
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            probe[(r["budget"], r["question_id"])] = r

    print("\n=== iterative loop vs plain BM25 (same reader, 120 questions) ===")
    for b in BUDGETS:
        ids = sorted(i for (bb, i) in probe if bb == b and (b, i) in base)
        if not ids:
            continue
        xa = [base[(b, i)]["relaxed_em"] for i in ids]
        xb = [probe[(b, i)]["relaxed_em"] for i in ids]
        ma, mb = sum(xa) / len(xa), sum(xb) / len(xb)
        (_, _, _), (lo, hi) = paired_bootstrap(xa, xb)
        mc = mcnemar_exact(xa, xb)
        print(f"B={b}: plain {ma:.4f} -> iter {mb:.4f}  delta={mb-ma:+.4f} "
              f"[{lo:+.4f},{hi:+.4f}]  McNemar p={mc['p_value']:.3f} "
              f"(n10={mc['n10']},n01={mc['n01']})")


if __name__ == "__main__":
    asyncio.run(main())

# -*- coding: utf-8 -*-
"""Time-aware query expansion probe — W5/W10 of round 6.

Reviewer ask: the retrieval configuration is basic (whitespace-tokenised BM25,
fixed granularity, no temporal reasoning); does a stronger, time-aware retrieval
baseline close part of the gap at small/mid budgets?

Instantiation (deliberately simple and fully disclosed):
  * index side : every turn is indexed with its session date tokens
                 (year, month name, day, weekday) appended to its text;
  * query side : the question is expanded with the question date tokens.
This gives BM25 a temporal anchor without any learned component, so a null
result is attributable to the retrieval family rather than to tuning effort.

Reader: DeepSeek-V4.1-Flash (the only live reader), paired within-reader against
the same reader's plain-BM25 cells on the same 120 questions
(retrieval@1024 = 0.3167, retrieval@4096 = 0.3750).

Output: code/output/longmemeval/results_qexp.jsonl (+ stdout paired tests).
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from rank_bm25 import BM25Okapi  # noqa: E402

from common import load_questions  # noqa: E402
from llm import MODEL_MAIN, answer_with_memory  # noqa: E402
from policies import _fill_from_ranked, _turn_segments  # noqa: E402
from score import mcnemar_exact, paired_bootstrap, relaxed_em, token_f1  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
RESULTS = OUT / "results_qexp.jsonl"
CONC = int(__import__("os").environ.get("PAPER_LAB_CONCURRENCY", "24"))
BUDGETS = [1024, 4096]
MONTHS = {m: n for n, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTH_NAMES = ["", "january", "february", "march", "april", "may", "june", "july",
               "august", "september", "october", "november", "december"]


def date_tokens(stamp: str) -> str:
    """'2023/05/20 (Sat) 15:08' -> '2023 may 20 saturday'."""
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})\s*\((\w{3})\)", stamp or "")
    if not m:
        return ""
    y, mo, d, wd = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
    return f"{y} {MONTH_NAMES[mo] if 1 <= mo <= 12 else ''} {d} {wd}".strip()


def rank_timeaware(qerms: str, turns, session_dates: dict[str, str]):
    corpus = [f"{t.text} {date_tokens(session_dates.get(t.session_id, ''))}".split() for t in turns]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(qerms.split())
    return [t for _, t in sorted(zip(scores, turns), key=lambda x: -x[0])]


async def main() -> None:
    questions = load_questions()
    print(f"[qexp] questions={len(questions)} budgets={BUDGETS} reader={MODEL_MAIN}", flush=True)

    done: set[tuple] = set()
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["budget"], r["question_id"]))
    print(f"[qexp] 已有 {len(done)} 条", flush=True)

    sem = asyncio.Semaphore(CONC)
    for budget in BUDGETS:
        todo = [q for q in questions if (budget, q.question_id) not in done]
        if not todo:
            print(f"[qexp] skip budget={budget}", flush=True)
            continue
        print(f"[qexp] run budget={budget} n={len(todo)}", flush=True)
        recs: list[dict] = []

        async def one(q) -> None:
            async with sem:
                t1 = time.perf_counter()
                try:
                    qt = q.question + " " + date_tokens(q.question_date)
                    ranked = rank_timeaware(qt, q.turns, q.session_dates)
                    sel = _fill_from_ranked(ranked, budget, set())
                    sel.sort(key=lambda t: (t.session_idx, t.turn_idx))
                    mem = "\n".join(_turn_segments(sel))
                    ans = await answer_with_memory(
                        q.question, q.question_date, mem,
                        OUT / "cache" / "answers",
                        f"qexp|{budget}|{q.question_id}", model_tag=MODEL_MAIN,
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"[qexp][FAIL] {budget}|{q.question_id}: {str(e)[:80]}", flush=True)
                    return
                recs.append({
                    "policy": "retrieval_qexp", "budget": budget,
                    "question_id": q.question_id, "question_type": q.question_type,
                    "model": MODEL_MAIN, "pred": ans["text"], "gold": q.answer,
                    "relaxed_em": relaxed_em(ans["text"], q.answer),
                    "f1": token_f1(ans["text"], q.answer),
                    "prompt_tokens": ans["prompt_tokens"],
                    "completion_tokens": ans["completion_tokens"],
                    "e2e_ms": round((time.perf_counter() - t1) * 1000, 1),
                    "memory_footprint_tokens": sum(t.ntok for t in sel),
                })

        await asyncio.gather(*(one(q) for q in todo))
        with RESULTS.open("a", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[qexp] budget={budget} wrote {len(recs)}", flush=True)

    # ---------- paired tests vs same-reader plain BM25 ----------
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

    print("\n=== qexp vs plain BM25 (same reader, 120 questions) ===")
    for b in BUDGETS:
        ids = sorted(i for (bb, i) in probe if bb == b and (b, i) in base)
        if not ids:
            continue
        xa = [base[(b, i)]["relaxed_em"] for i in ids]
        xb = [probe[(b, i)]["relaxed_em"] for i in ids]
        ma, mb = sum(xa) / len(xa), sum(xb) / len(xb)
        (_, _, _), (lo, hi) = paired_bootstrap(xa, xb)
        mc = mcnemar_exact(xa, xb)
        fa = sum(base[(b, i)]["f1"] for i in ids) / len(ids)
        fb = sum(probe[(b, i)]["f1"] for i in ids) / len(ids)
        print(f"B={b}: plain {ma:.4f} -> qexp {mb:.4f}  delta={mb-ma:+.4f} "
              f"[{lo:+.4f},{hi:+.4f}]  McNemar p={mc['p_value']:.3f} "
              f"(n10={mc['n10']},n01={mc['n01']})  F1 {fa:.3f}->{fb:.3f}")


if __name__ == "__main__":
    asyncio.run(main())

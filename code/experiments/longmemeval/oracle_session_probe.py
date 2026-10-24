# -*- coding: utf-8 -*-
"""Gold-session-only oracle (round 8): how much of the "read failure" is dilution?

For every covered-but-wrong question of the n=500 retrieval@4096 cell we rebuild a
context that contains *only the gold sessions* (all their turns, chronological,
truncated to 4096 cl100k tokens) and re-ask the same question with the same reader.

  - If the answer flips, the evidence was readable but lost among distractors:
    a read-side failure of attention/dilution, still a read failure.
  - If it does not flip, the reader cannot extract the answer even from a clean,
    distractor-free evidence context: a genuine extraction limit (or a gold that
    requires aggregation the metric does not credit).

Output: results_oracle_session.jsonl + oracle_session_summary.json + tables500/oracle_session.tex
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import load_questions, ntokens, truncate_to_budget  # noqa: E402
from f500_diag import READER, load_records, load_summaries60  # noqa: E402
from llm import answer_with_memory  # noqa: E402
from policies import build_memory  # noqa: E402
from score import mcnemar_exact, normalize, paired_bootstrap, relaxed_em, token_f1  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
TAB = Path(__file__).resolve().parents[3] / "output" / "final" / "tables500"
CAP = int(os.environ.get("OSESS_CAP", "4096"))
RESULTS = OUT / f"results_oracle_session_true{CAP}.jsonl"
CONC = int(os.environ.get("PAPER_LAB_CONCURRENCY", "24"))
BUDGET = 4096


async def main() -> None:
    questions = {q.question_id: q for q in load_questions(full=True)}
    summaries = load_summaries60()
    records = load_records(READER)
    done = set()
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["question_id"])

    tasks = []
    for qid, q in questions.items():
        rec = records.get(("retrieval", 4096, qid))
        if rec is None or rec["relaxed_em"] > 0.5 or qid in done:
            continue
        plan = build_memory("retrieval", q, BUDGET, summaries)
        if not ((plan.covered_turn_sessions | plan.covered_summary_sessions)
                & set(q.answer_session_ids)):
            continue
        gold = set(q.answer_session_ids)
        turns = [t for t in q.turns if t.session_id in gold]
        mem = truncate_to_budget("\n".join(t.text for t in turns), CAP)
        tasks.append((q, mem, rec))
    print(f"[osess] to run={len(tasks)}", flush=True)

    sem = asyncio.Semaphore(CONC)
    recs, lock = [], asyncio.Lock()

    async def one(q, mem, base) -> None:
        async with sem:
            try:
                ans = await answer_with_memory(q.question, q.question_date, mem,
                                               OUT / "cache" / "answers",
                                               f"osess_true{CAP}|{q.question_id}",
                                               model_tag=READER)
            except Exception as e:  # noqa: BLE001
                print(f"[osess][FAIL] {q.question_id}: {str(e)[:80]}", flush=True)
                return
            async with lock:
                recs.append({
                    "question_id": q.question_id, "policy": "oracle_gold_session",
                    "budget": BUDGET, "question_type": q.question_type, "model": READER,
                    "pred": ans["text"], "gold": q.answer,
                    "em": 1.0 if normalize(ans["text"]) == normalize(q.answer) else 0.0,
                    "relaxed_em": relaxed_em(ans["text"], q.answer),
                    "f1": token_f1(ans["text"], q.answer),
                    "baseline_rel": base["relaxed_em"],
                    "context_tokens": ntokens(mem),
                })

    await asyncio.gather(*(one(*t) for t in tasks))
    with RESULTS.open("a", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[osess] wrote {len(recs)}", flush=True)

    allr = [json.loads(x) for x in RESULTS.read_text(encoding="utf-8").splitlines() if x.strip()]
    base = [r["baseline_rel"] for r in allr]
    orc = [r["relaxed_em"] for r in allr]
    (mo, mb, _), ci = paired_bootstrap(orc, base)
    m = mcnemar_exact([1.0 if x > 0.5 else 0.0 for x in orc],
                      [1.0 if x > 0.5 else 0.0 for x in base])
    summ = {"n": len(allr), "baseline": round(mb, 4), "oracle": round(mo, 4),
            "delta": round(mo - mb, 4), "ci": [round(ci[0], 4), round(ci[1], 4)],
            "p": round(m["p_value"], 6),
            "fixed": sum(1 for x in orc if x > 0.5),
            "by_type": {}}
    for t in sorted({r["question_type"] for r in allr}):
        sub = [r for r in allr if r["question_type"] == t]
        summ["by_type"][t] = {"n": len(sub), "fixed": sum(1 for r in sub if r["relaxed_em"] > 0.5)}
    (OUT / f"oracle_session_summary_true{CAP}.json").write_text(json.dumps(summ, indent=1), encoding="utf-8")
    print(json.dumps(summ, indent=1), flush=True)

    BS = chr(92)
    lines = [BS + "begin{tabular}{lccc}", BS + "toprule",
             "Question type & $n$ & fixed by oracle & share " + BS + BS, BS + "midrule"]
    for t, v in summ["by_type"].items():
        lines.append(f"{t.replace('-', ' ')} & {v['n']} & {v['fixed']} & "
                     f"{v['fixed'] / v['n']:.3f} " + BS + BS)
    lines.append(BS + "midrule")
    lines.append(f"all & {summ['n']} & {summ['fixed']} & {summ['oracle']:.3f} " + BS + BS)
    lines += [BS + "bottomrule", BS + "end{tabular}"]
    (TAB / f"oracle_session_true{CAP}.tex").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())

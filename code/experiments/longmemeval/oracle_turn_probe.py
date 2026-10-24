# -*- coding: utf-8 -*-
"""Oracle bearing-turn injection (round 8, reviewer point 1).

The session-level failure decomposition cannot tell whether a covered-but-wrong
question failed at *reading* or because the answer-bearing turn inside the gold
session was never selected. We test that directly, with an intervention:

  for every covered-but-wrong question at B=4096 (retrieval, n=500 grid):
      locate the answer-bearing turn (content-word overlap >= 0.5)
      build a minimal oracle context = that turn +- 1 turn in the same session
      (<= 400 cl100k tokens), and re-ask the same question with the same reader

Outcomes are split by where the bearing turn was in the original assembly:

  in_context  : the turn was already injected -> oracle removes DISTRACTORS.
                If the answer flips, the failure was context dilution (still a
                read-side failure, but of "which evidence to attend to").
                If not, it is a genuine extraction/scoring limit.
  in_history  : the turn was in the unconsumed history -> oracle removes the
                SELECTION error. Flips here are exactly the residual ambiguity the
                reviewer worries about: session-level labels called them read
                failures, turn-level evidence says they were retrieval misses.

Output: results_oracle.jsonl + oracle_summary.json + tables500/oracle.tex
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import load_questions, ntokens  # noqa: E402
from f500_diag import (READER, best_turn, content_set, load_records,  # noqa: E402
                       load_summaries60, selected_turns)
from llm import answer_with_memory  # noqa: E402
from policies import build_memory  # noqa: E402
from score import mcnemar_exact, normalize, paired_bootstrap, relaxed_em, token_f1  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
TAB = Path(__file__).resolve().parents[3] / "output" / "final" / "tables500"
RESULTS = OUT / "results_oracle.jsonl"
CONC = int(os.environ.get("PAPER_LAB_CONCURRENCY", "24"))
THRESH = 0.5
CTX_CAP = 400


def oracle_context(q, bt) -> str:
    """bearing turn +-1 turn in the same session, capped at CTX_CAP tokens."""
    same = [t for t in q.turns if t.session_id == bt.session_id]
    i = same.index(bt)
    window = same[max(0, i - 1): i + 2]
    segs, used = [], 0
    for t in window:
        if used + t.ntok > CTX_CAP:
            break
        segs.append(t.text)
        used += t.ntok
    return "\n".join(segs)


async def main() -> None:
    questions = {q.question_id: q for q in load_questions(full=True)}
    summaries = load_summaries60()
    records = load_records(READER)
    print(f"[oracle] questions={len(questions)} summaries={len(summaries)}", flush=True)

    done: set[str] = set()
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["question_id"])
    print(f"[oracle] existing={len(done)}", flush=True)

    tasks = []
    for qid, q in questions.items():
        rec = records.get(("retrieval", 4096, qid))
        if rec is None or rec["relaxed_em"] > 0.5 or qid in done:
            continue
        plan = build_memory("retrieval", q, 4096, summaries)
        if not ((plan.covered_turn_sessions | plan.covered_summary_sessions)
                & set(q.answer_session_ids)):
            continue
        gold_cw = content_set(q.answer)
        if not gold_cw:
            continue
        bt, ov = best_turn(gold_cw, q.turns)
        if bt is None or ov < THRESH:
            continue
        sel, _ = selected_turns("retrieval", q, 4096, summaries)
        status = "in_context" if (bt.session_idx, bt.turn_idx) in sel else "in_history"
        tasks.append((q, bt, status, rec))
    print(f"[oracle] to run={len(tasks)} "
          f"({Counter(t[2] for t in tasks)})", flush=True)

    sem = asyncio.Semaphore(CONC)
    recs: list[dict] = []
    lock = asyncio.Lock()

    async def one(q, bt, status, base) -> None:
        async with sem:
            try:
                mem = oracle_context(q, bt)
                t0 = time.perf_counter()
                ans = await answer_with_memory(
                    q.question, q.question_date, mem,
                    OUT / "cache" / "answers", f"oracle|{q.question_id}",
                    model_tag=READER)
                dt = (time.perf_counter() - t0) * 1000
            except Exception as e:  # noqa: BLE001
                print(f"[oracle][FAIL] {q.question_id}: {str(e)[:90]}", flush=True)
                return
            async with lock:
                recs.append({
                    "question_id": q.question_id, "policy": "oracle_turn",
                    "budget": 4096, "question_type": q.question_type,
                    "model": READER, "status": status,
                    "pred": ans["text"], "gold": q.answer,
                    "em": 1.0 if normalize(ans["text"]) == normalize(q.answer) else 0.0,
                    "relaxed_em": relaxed_em(ans["text"], q.answer),
                    "f1": token_f1(ans["text"], q.answer),
                    "baseline_pred": base["pred"], "baseline_rel": base["relaxed_em"],
                    "context_tokens": ntokens(mem),
                    "e2e_ms": dt,
                    "prompt_tokens": ans.get("prompt_tokens", 0),
                })

    await asyncio.gather(*(one(*t) for t in tasks))
    with RESULTS.open("a", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[oracle] wrote {len(recs)}", flush=True)

    # ---------------- summary ----------------
    allr = [json.loads(x) for x in RESULTS.read_text(encoding="utf-8").splitlines() if x.strip()]
    summ = {"n": len(allr)}
    for st in ("in_context", "in_history"):
        sub = [r for r in allr if r["status"] == st]
        if not sub:
            continue
        base = [r["baseline_rel"] for r in sub]
        orc = [r["relaxed_em"] for r in sub]
        (mo, mb, _), ci = paired_bootstrap(orc, base)
        mcn = mcnemar_exact([1.0 if r["relaxed_em"] > 0.5 else 0.0 for r in sub],
                            [1.0 if r["baseline_rel"] > 0.5 else 0.0 for r in sub])
        summ[st] = {"n": len(sub), "baseline": round(mb, 4), "oracle": round(mo, 4),
                    "delta": round(mo - mb, 4), "ci": [round(ci[0], 4), round(ci[1], 4)],
                    "p": round(mcn["p_value"], 6),
                    "fixed": sum(1 for r in sub if r["relaxed_em"] > 0.5)}
        # by type
        summ[st]["by_type"] = {
            t: {"n": len([r for r in sub if r["question_type"] == t]),
                "fixed": sum(1 for r in sub if r["question_type"] == t
                             and r["relaxed_em"] > 0.5)}
            for t in {r["question_type"] for r in sub}}
    base = [r["baseline_rel"] for r in allr]
    orc = [r["relaxed_em"] for r in allr]
    (mo, mb, _), ci = paired_bootstrap(orc, base)
    summ["all"] = {"n": len(allr), "baseline": round(mb, 4), "oracle": round(mo, 4),
                   "delta": round(mo - mb, 4), "ci": [round(ci[0], 4), round(ci[1], 4)],
                   "fixed": sum(1 for r in allr if r["relaxed_em"] > 0.5)}
    (OUT / "oracle_summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    print(json.dumps(summ, ensure_ascii=False, indent=1)[:2000], flush=True)

    BS = chr(92)
    tex = [BS + "begin{tabular}{lccccc}", BS + "toprule",
           "Bearing turn & $n$ & baseline & oracle & $\\Delta$ & fixed " + BS + BS,
           BS + "midrule"]
    for st, label in (("in_context", "in context (distractors removed)"),
                      ("in_history", "in history (selection error)")):
        if st in summ:
            s = summ[st]
            tex.append(f"{label} & {s['n']} & {s['baseline']:.3f} & {s['oracle']:.3f} & "
                       f"{s['delta']:+.3f} & {s['fixed']} " + BS + BS)
    tex += [BS + "bottomrule", BS + "end{tabular}"]
    (TAB / "oracle.tex").write_text("\n".join(tex), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())

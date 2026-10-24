# -*- coding: utf-8 -*-
"""Full-500 failure decomposition + turn-level bearing audit (round 8, zero LLM cost).

For every (policy, budget) cell of the n=500 primary grid we rebuild the memory
assembly, check whether a gold session (answer_session_ids) reaches the context,
and join this with the reader's correctness:

    read-fail      : gold session in context, answer wrong
    retrieval-fail : gold session absent, answer wrong

The turn-level audit then locates the *answer-bearing turn* for covered-but-wrong
questions (content-word overlap >= 0.5, same rule as bearing_turn_audit.py) and
splits it into:
    in-context  : the bearing turn itself is in the injected context
    in-history  : only an un-injected turn reaches the threshold
    none        : no turn reaches it (paraphrastic / aggregate gold)

Output: code/output/longmemeval/f500_diag.json (+ tables500/diag.tex)
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import BUDGETS, load_questions  # noqa: E402
from policies import (POLICIES, _bm25_rank, _fill_from_ranked, _tail_turns,  # noqa: E402
                      build_memory)
from score import normalize  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
TAB = Path(__file__).resolve().parents[3] / "output" / "final" / "tables500"
READER = "deepseek-v4.1-flash"
THRESH = 0.5
STOP = set("""a an the and or but if then else of to in on at by for with about as is are was
were be been being do does did doing have has had having i you he she it we they me him her them
my your his its our their this that these those there here what which who whom when where why how
not no nor so too very can will just would should could may might must shall""".split())


def content_set(s: str) -> set:
    return {w for w in normalize(s).split() if w not in STOP}


def load_summaries60() -> dict[str, str]:
    sums = {}
    for f in (OUT / "cache" / "summaries").glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if d.get("max_words") == 60 and d.get("model") == READER and d.get("text"):
            sums[d["session_id"]] = d["text"]
    return sums


def load_records(model: str) -> dict[tuple, dict]:
    recs = {}
    for line in (OUT / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("model") == model:
                recs[(r["policy"], r.get("budget"), r["question_id"])] = r
    return recs


def best_turn(gold_cw: set, turns) -> tuple[object | None, float]:
    best, best_ov = None, 0.0
    for t in turns:
        tc = content_set(t.text)
        if not tc:
            continue
        ov = len(gold_cw & tc) / len(gold_cw) if gold_cw else 0.0
        if ov > best_ov:
            best, best_ov = t, ov
    return best, best_ov


def selected_turns(policy: str, q, b: int, summaries) -> tuple[set, set]:
    """Rebuild the exact turn/summary selection (mirrors build_memory)."""
    if policy == "retrieval":
        sel = _fill_from_ranked(_bm25_rank(q.turns, q.question), b, set())
        return {(t.session_idx, t.turn_idx) for t in sel}, set()
    if policy == "retrieval_recency":
        half = b // 2
        tail = _tail_turns(q.turns, half)
        skip = {(t.session_idx, t.turn_idx) for t in tail}
        rest = _fill_from_ranked(_bm25_rank(q.turns, q.question),
                                 b - sum(t.ntok for t in tail), skip)
        return ({(t.session_idx, t.turn_idx) for t in tail + rest},
                {t.session_id for t in tail})
    if policy == "sliding_window":
        sel = _tail_turns(q.turns, b)
        return {(t.session_idx, t.turn_idx) for t in sel}, set()
    if policy == "full_context":
        return {(t.session_idx, t.turn_idx) for t in q.turns}, set()
    return set(), set()


def main() -> None:
    questions = load_questions(full=True)
    summaries = load_summaries60()
    records = load_records(READER)
    print(f"questions={len(questions)} summaries={len(summaries)} records={len(records)}",
          flush=True)

    rows = []
    per_q = []
    for pol in ["sliding_window", "retrieval", "retrieval_recency",
                "compression", "hierarchical", "full_context"]:
        for b in ([None] if pol == "full_context" else BUDGETS):
            covered_n = read_fail = retrieve_fail = correct = total = 0
            correct_covered = 0
            for q in questions:
                rec = records.get((pol, b, q.question_id))
                if rec is None or not (rec.get("pred") or "").strip():
                    continue
                plan = build_memory(pol, q, b, summaries)
                cov = plan.covered_turn_sessions | plan.covered_summary_sessions
                gold_hit = bool(cov & set(q.answer_session_ids))
                total += 1
                ok = rec["relaxed_em"] > 0.5
                if ok:
                    correct += 1
                    if gold_hit:
                        correct_covered += 1
                elif gold_hit:
                    read_fail += 1
                else:
                    retrieve_fail += 1
                if gold_hit:
                    covered_n += 1
                per_q.append({"policy": pol, "budget": b, "qid": q.question_id,
                              "gold_hit": gold_hit, "correct": ok})
            if total:
                rows.append({
                    "policy": pol, "budget": b, "n": total,
                    "gold_recall": round(covered_n / total, 4),
                    "acc_covered": round(correct_covered / max(covered_n, 1), 4),
                    "read_fail_share": round(read_fail / total, 4),
                    "retrieve_fail_share": round(retrieve_fail / total, 4),
                    "acc": round(correct / total, 4),
                })
                print(f"{pol:18s} B={str(b):5s} n={total} gold={rows[-1]['gold_recall']:.3f} "
                      f"acc|cov={rows[-1]['acc_covered']:.3f} read={rows[-1]['read_fail_share']:.3f} "
                      f"retr={rows[-1]['retrieve_fail_share']:.3f}", flush=True)

    # ---------- session-level BM25 ranking quality (no truncation) ----------
    rank_rows = []
    for name, ranker in [("BM25", lambda q: _bm25_rank(q.turns, q.question))]:
        for k in (1, 5, 10):
            hit = 0
            n = 0
            for q in questions:
                if not q.answer_session_ids:
                    continue
                order = []
                for t in ranker(q):
                    if t.session_id not in order:
                        order.append(t.session_id)
                n += 1
                hit += bool(set(order[:k]) & set(q.answer_session_ids))
            rank_rows.append({"retriever": name, "k": k, "recall": round(hit / max(n, 1), 4),
                              "n": n})
    print("rank", rank_rows, flush=True)

    # ---------- turn-level bearing audit (retrieval@4096, 500) ----------
    audit = []
    for q in questions:
        rec = records.get(("retrieval", 4096, q.question_id))
        if rec is None or rec["relaxed_em"] > 0.5:
            continue
        plan = build_memory("retrieval", q, 4096, summaries)
        if not ((plan.covered_turn_sessions | plan.covered_summary_sessions)
                & set(q.answer_session_ids)):
            continue
        sel, _ = selected_turns("retrieval", q, 4096, summaries)
        gold_cw = content_set(q.answer)
        if not gold_cw:
            continue
        bt, ov = best_turn(gold_cw, q.turns)
        if bt is None or ov < THRESH:
            status = "none"
        elif (bt.session_idx, bt.turn_idx) in sel:
            status = "in_context"
        else:
            status = "in_history"
        audit.append({"qid": q.question_id, "status": status, "overlap": round(ov, 3),
                      "type": q.question_type})
    c = Counter(a["status"] for a in audit)
    tot = len(audit)
    print("audit", tot, dict(c), flush=True)

    out = {"reader": READER, "n": len(questions), "cells": rows, "ranking": rank_rows,
           "bearing_audit": {"n": tot, "counts": dict(c),
                             "shares": {k: round(v / max(tot, 1), 4) for k, v in c.items()},
                             "by_type": {t: dict(Counter(a["status"] for a in audit
                                                         if a["type"] == t))
                                         for t in {a["type"] for a in audit}}}}
    (OUT / "f500_diag.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                        encoding="utf-8")

    BS = chr(92)
    tex = [BS + "begin{tabular}{llccccc}", BS + "toprule",
           "Policy & Budget & gold recall & acc" + BS + "$_{" + BS + "mathrm{covered}}$ & "
           "read-fail & retr.-fail " + BS + BS, BS + "midrule"]
    for r in rows:
        tex.append(f"{r['policy'].replace('_', BS + '_')} & "
                   f"{('--' if r['budget'] is None else r['budget'])} & "
                   f"{r['gold_recall']:.3f} & {r['acc_covered']:.3f} & "
                   f"{r['read_fail_share']:.3f} & {r['retrieve_fail_share']:.3f} "
                   + BS + BS)
    tex += [BS + "bottomrule", BS + "end{tabular}"]
    (TAB / "diag.tex").write_text("\n".join(tex), encoding="utf-8")


if __name__ == "__main__":
    main()

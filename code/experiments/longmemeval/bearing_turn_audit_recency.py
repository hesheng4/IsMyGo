# -*- coding: utf-8 -*-
"""Turn-level audit for a second policy (retrieval_recency@4096) — R2 of round 7.

Same classifier as bearing_turn_audit.py (content-word overlap >= 0.5 locates the
answer-bearing turn), but the context is reconstructed for retrieval+recency
(half-budget tail + BM25 over the remainder) instead of plain retrieval. Purpose:
show that the session-level -> turn-level correction is not an artefact of one
policy family.

Zero LLM calls. Output: code/output/longmemeval/tables/bearing_turn_audit_recency.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import load_questions  # noqa: E402
from policies import _bm25_rank, _fill_from_ranked, _tail_turns  # noqa: E402
from score import normalize  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
POLICY = "retrieval_recency"
BUDGET = 4096
THRESH = 0.5


def content_set(s: str) -> set:
    stop = set("""a an the and or but if then else of to in on at by for with about as is are was
were be been being do does did doing have has had having i you he she it we they me him her them
my your his its our their this that these those there here what which who whom when where why how
not no nor so too very can will just would should could may might must shall""".split())
    return {w for w in normalize(s).split() if w not in stop}


def best_turn(gold_cw: set, turns) -> tuple[object, float]:
    best, best_ov = None, 0.0
    for t in turns:
        tc = content_set(t.text)
        if not tc:
            continue
        ov = len(gold_cw & tc) / len(gold_cw) if gold_cw else 0.0
        if ov > best_ov:
            best, best_ov = t, ov
    return best, best_ov


def main() -> None:
    res_path = HERE.parents[2] / "output" / "results.jsonl"
    res = {}
    for line in res_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if (r["policy"] == POLICY and r.get("budget") == BUDGET
                and str(r.get("model", "mimo-v2.6-flash")) == "mimo-v2.6-flash"):
            res[r["question_id"]] = r
    print(f"[bearing2] {POLICY}@{BUDGET} records: {len(res)}")

    questions = load_questions()
    rows = []
    for q in questions:
        r = res.get(q.question_id)
        if r is None or r["relaxed_em"] >= 0.5:
            continue
        half = BUDGET // 2
        tail = _tail_turns(q.turns, half)
        skip = {(t.session_idx, t.turn_idx) for t in tail}
        ranked = _bm25_rank(q.turns, q.question)
        retr = _fill_from_ranked(ranked, BUDGET - sum(t.ntok for t in tail), skip)
        sel = sorted(tail + retr, key=lambda t: (t.session_idx, t.turn_idx))
        covered = {t.session_id for t in sel}
        if not (covered & set(q.answer_session_ids)):
            continue

        gold_cw = content_set(q.answer)
        b_ctx, ov_ctx = best_turn(gold_cw, sel)
        b_all, ov_all = best_turn(gold_cw, q.turns)
        if ov_ctx >= THRESH:
            cls = "bearing-in-context"
        elif ov_all >= THRESH:
            cls = "bearing-in-history"
        else:
            cls = "none"
        rows.append({"question_id": q.question_id, "question_type": q.question_type,
                     "class": cls, "best_ctx_overlap": round(ov_ctx, 3),
                     "best_all_overlap": round(ov_all, 3)})

    cc = Counter(r["class"] for r in rows)
    n = len(rows)
    print(f"[bearing2] covered-but-wrong={n}")
    for k in ("bearing-in-context", "bearing-in-history", "none"):
        print(f"  {k:20s} {cc[k]:3d}  ({cc[k]/n:.1%})")

    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    p = OUT / "tables" / "bearing_turn_audit_recency.json"
    p.write_text(json.dumps({"meta": {"policy": POLICY, "budget": BUDGET,
                                      "reader": "mimo-v2.6-flash", "n": n,
                                      "threshold": THRESH, "class_counts": dict(cc)},
                             "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[bearing2] -> {p}")

    # 与 session 级口径对照
    diag = json.loads((OUT / "tables" / "retrieval_diagnosis.json").read_text(encoding="utf-8"))
    for c in diag["cells"]:
        if c["policy"] == POLICY and c["budget"] == BUDGET:
            print(f"[bearing2] session-level read-fail share: {c['read_fail_share']:.3f} "
                  f"(n={c['n']}), turn-level in-context share: {cc['bearing-in-context']/n:.3f}")


if __name__ == "__main__":
    main()

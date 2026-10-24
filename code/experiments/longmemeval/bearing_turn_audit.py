# -*- coding: utf-8 -*-
"""Q3/W2 追加: turn 级代理覆盖 —— 答案承载 turn 定位 (snippet_audit 的扩展).

在 retrieval@4096 的 covered-but-wrong 题上, 把答案承载证据定位到具体 turn:
  对每题, 在 (a) 注入上下文的 turn 集与 (b) 全部历史 turn 集中, 找与 gold
  答案内容词重合率最高的 turn (归一化词集 Jaccard/重合率), 报告:
    bearing-in-context : 与 gold 重合率 >= 0.5 的 turn 已被注入上下文
    bearing-in-history : 只有历史中未注入的 turn 达到该重合率
    none               : 无任何 turn 达到 0.5 (gold 为概括性/改写型答案)
并报告 bearing turn 在上下文中的位置 (head/mid/tail)。
全部本地确定性, 零 LLM 调用。输出 tables/bearing_turn_audit.json + stdout。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import load_questions  # noqa: E402
from policies import _bm25_rank, _fill_from_ranked  # noqa: E402
from score import normalize  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
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
        if (r["policy"] == "retrieval" and r.get("budget") == BUDGET
                and str(r.get("model", "mimo-v2.6-flash")) == "mimo-v2.6-flash"):
            res[r["question_id"]] = r
    assert len(res) == 120

    questions = load_questions()
    rows = []
    n_cw = 0
    for q in questions:
        r = res.get(q.question_id)
        if r is None:
            continue
        ranked = _bm25_rank(q.turns, q.question)
        sel = _fill_from_ranked(ranked, BUDGET, set())
        sel.sort(key=lambda t: (t.session_idx, t.turn_idx))
        covered = {t.session_id for t in sel}
        if not (covered & set(q.answer_session_ids)):
            continue
        if r["relaxed_em"] >= 0.5:
            continue
        n_cw += 1
        gold_cw = content_set(q.answer)
        sel_keys = {(t.session_idx, t.turn_idx) for t in sel}
        b_ctx, ov_ctx = best_turn(gold_cw, sel)
        b_all, ov_all = best_turn(gold_cw, q.turns)
        if ov_ctx >= THRESH:
            cls = "bearing-in-context"
        elif ov_all >= THRESH:
            cls = "bearing-in-history"
        else:
            cls = "none"
        pos = None
        if cls == "bearing-in-context":
            order = sorted(sel_keys)
            pos = order.index((b_ctx.session_idx, b_ctx.turn_idx)) / max(len(order) - 1, 1)
        rows.append({
            "question_id": q.question_id, "question_type": q.question_type,
            "class": cls, "best_ctx_overlap": round(ov_ctx, 3),
            "best_all_overlap": round(ov_all, 3),
            "bearing_turn_rel_pos": round(pos, 3) if pos is not None else None,
        })

    cc = Counter(r["class"] for r in rows)
    n = len(rows)
    print(f"[bearing] covered-but-wrong={n}")
    for k in ("bearing-in-context", "bearing-in-history", "none"):
        print(f"  {k:20s} {cc[k]:3d}  ({cc[k]/n:.1%})")
    poses = [r["bearing_turn_rel_pos"] for r in rows if r["bearing_turn_rel_pos"] is not None]
    if poses:
        head = sum(1 for p in poses if p < 1/3); mid = sum(1 for p in poses if 1/3 <= p < 2/3)
        tail = sum(1 for p in poses if p >= 2/3)
        print(f"  bearing turn position (head/mid/tail): {head}/{mid}/{tail}")
    byt = {}
    for r in rows:
        byt.setdefault(r["question_type"], Counter())[r["class"]] += 1
    for t, c in sorted(byt.items()):
        print(f"  {t:28s} " + "  ".join(f"{k}={c[k]}" for k in ("bearing-in-context", "bearing-in-history", "none")))

    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    (OUT / "tables" / "bearing_turn_audit.json").write_text(
        json.dumps({"meta": {"policy": "retrieval", "budget": BUDGET, "reader": "mimo-v2.6-flash",
                             "n": n, "threshold": THRESH, "class_counts": dict(cc)},
                    "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[bearing] -> {OUT / 'tables' / 'bearing_turn_audit.json'}")


if __name__ == "__main__":
    main()

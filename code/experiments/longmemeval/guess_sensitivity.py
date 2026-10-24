"""W3 敏感性: "guess 指令 -> EM 假阳性" 上界估计 (第三轮审稿回应, 本地零 LLM).

对 deepseek full-500 的 relaxed_em=1 记录, 确定性重建注入上下文,
统计 normalized pred 是否为 normalized context 的子串:
  - 子串命中 -> 答案是从上下文提取的 (非猜测)
  - 未命中  -> 推理/改写/可能的猜测 (假阳性上界的构成部分)
策略: retrieval@4096 (预算受限主策略), full_context (全部历史),
      sliding_window@4096 (地板对照). 输出 JSON 落盘.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import load_questions  # noqa: E402
from policies import _bm25_rank, _fill_from_ranked  # noqa: E402
from score import normalize  # noqa: E402

RES = HERE.parents[1] / "output" / "longmemeval" / "results.jsonl"


def build_ctx_retrieval(q, budget: int) -> str:
    ranked = _bm25_rank(q.turns, q.question)
    sel = _fill_from_ranked(ranked, budget, set())
    sel.sort(key=lambda t: (t.session_idx, t.turn_idx))
    return "\n".join(t.content for t in sel)


def build_ctx_full(q) -> str:
    return "\n".join(t.content for t in q.turns)


def build_ctx_window(q, budget: int) -> str:
    sel = q.turns[-budget:] if len(q.turns) > budget else q.turns
    return "\n".join(t.content for t in sel)


def main() -> None:
    qs = {q.question_id: q for q in load_questions(full=True)}
    recs = {}
    for line in RES.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if "deepseek" in str(r.get("model", "")):
            recs[(r["policy"], r["budget"], r["question_id"])] = r

    out = {"reader": "deepseek-v4.1-flash", "cells": {}}
    builders = {
        ("retrieval", 4096): lambda q: build_ctx_retrieval(q, 4096),
        ("full_context", None): build_ctx_full,
        ("sliding_window", 4096): lambda q: build_ctx_window(q, 4096),
    }
    for (pol, b), build in builders.items():
        n = hit = miss = 0
        examples = []
        for qid, q in qs.items():
            r = recs.get((pol, b, qid))
            if not r or r.get("relaxed_em", 0) < 0.5:
                continue
            n += 1
            ctx = build(q)
            if normalize(r["pred"]) and normalize(r["pred"]) in normalize(ctx):
                hit += 1
            else:
                miss += 1
                if len(examples) < 5:
                    examples.append({"qid": qid, "pred": r["pred"][:60],
                                     "gold": r["gold"][:60]})
        out["cells"][f"{pol}|{b}"] = {
            "n_correct": n, "verbatim_in_ctx": hit, "not_in_ctx": miss,
            "extractive_rate": round(hit / max(n, 1), 4),
        }
        print(f"{pol}|{b}: EM=1 n={n}  逐字在场 {hit} ({hit/max(n,1)*100:.1f}%)  "
              f"不在场 {miss}")
        for e in examples:
            print(f"   [非提取] qid={e['qid'][:12]} pred={e['pred']!r} gold={e['gold']!r}")

    dst = HERE.parents[1] / "output" / "longmemeval" / "guess_sensitivity.json"
    dst.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("written:", dst)


if __name__ == "__main__":
    main()

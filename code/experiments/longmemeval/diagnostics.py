# -*- coding: utf-8 -*-
"""检索阶段诊断 + Token 核算对账 (评审回应, 零 LLM 成本)。

一、金证据覆盖诊断: 对每个 (策略, 预算) 重建记忆装配, 检查金会话
    (answer_session_ids) 是否进入上下文, 与答题正误联表分解失败来源:
      retrieve_fail: 金证据未进入上下文 且 答错
      read_fail:     金证据进入上下文   且 答错 (读取/意译/评分环节)
二、BM25 排名诊断: 金会话轮次在 BM25 排序中的位置 (Recall@k)。
三、Token 核算: cl100k 足迹与 API 报告 prompt_tokens 的线性关系
    (量化预算单位的跨 tokenizer 公平性)。
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from common import BUDGETS, load_questions, unique_sessions
from policies import POLICIES, build_memory

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "output" / "longmemeval"
DIAG = OUT / "tables"


def load_summaries60(questions) -> dict[str, str]:
    import glob

    sums: dict[str, str] = {}
    for f in glob.glob(str(OUT / "cache" / "summaries" / "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        if d.get("max_words", 60) == 60:
            sums[d["session_id"]] = d["text"]
    return sums


def load_records() -> dict[tuple, dict]:
    recs = {}
    for line in (OUT / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            recs[(r["policy"], r["budget"], r["question_id"])] = r
    return recs


def main() -> None:
    DIAG.mkdir(parents=True, exist_ok=True)
    questions = load_questions()
    summaries = load_summaries60(questions)
    records = load_records()
    qids = {q.question_id for q in questions}

    # ---------------- 一、金证据覆盖分解 ----------------
    diag_pols = ["sliding_window", "retrieval", "retrieval_recency",
                 "compression", "hierarchical", "dense_retrieval",
                 "hybrid_retrieval"]
    turn_embs = None
    if (OUT / "cache" / "embeddings_bge").exists():
        from local_embed import load as load_bge
        keys = {t.turn_key for q in questions for t in q.turns}
        turn_embs = load_bge(keys)

    rows = []
    per_q = []
    for pol in diag_pols:
        for b in BUDGETS:
            covered_n = read_fail = retrieve_fail = correct = total = 0
            correct_covered = 0
            for q in questions:
                qe = None
                if pol in ("dense_retrieval", "hybrid_retrieval"):
                    import hashlib
                    qk = hashlib.sha1(
                        ("Represent this sentence for searching relevant passages: "
                         + q.question).encode()).hexdigest()[:16]
                    fp = OUT / "cache" / "embeddings_bge" / f"{qk}.json"
                    if not fp.exists():
                        continue
                    qe = json.load(open(fp, encoding="utf-8"))["v"]
                plan = build_memory(pol, q, b, summaries, qe=qe,
                                    turn_embs=turn_embs)
                cov = plan.covered_turn_sessions | plan.covered_summary_sessions
                gold_hit = bool(cov & set(q.answer_session_ids))
                rec = records.get((pol, b, q.question_id))
                if rec is None or not rec["pred"].strip():
                    continue
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
                per_q.append({"policy": pol, "budget": b,
                              "qid": q.question_id, "gold_hit": gold_hit,
                              "correct": ok})
            if total:
                rows.append({
                    "policy": pol, "budget": b, "n": total,
                    "gold_recall": covered_n / total,
                    "acc_covered": correct_covered / max(covered_n, 1),
                    "read_fail_share": read_fail / total,
                    "retrieve_fail_share": retrieve_fail / total,
                })

    (DIAG / "retrieval_diagnosis.json").write_text(
        json.dumps({"cells": rows, "per_question": per_q}, ensure_ascii=False,
                   indent=1), encoding="utf-8")

    BS = chr(92)
    tex = [BS + "begin{tabular}{llccccc}", BS + "toprule",
           "Policy & Budget & $n$ & gold recall & acc$|_{\\mathrm{covered}}$ & "
           "read-fail & retr.-fail " + BS + BS, BS + "midrule"]
    for r in rows:
        tex.append(
            f"{r['policy'].replace('_', BS + '_')} & {r['budget']} & {r['n']} & "
            f"{r['gold_recall']:.3f} & {r['acc_covered']:.3f} & "
            f"{r['read_fail_share']:.3f} & {r['retrieve_fail_share']:.3f} "
            + BS + BS)
    tex += [BS + "bottomrule", BS + "end{tabular}"]
    (DIAG / "retrieval_diagnosis.tex").write_text("\n".join(tex),
                                                   encoding="utf-8")

    # ---------------- 三、Token 核算对账 ----------------
    xs, ys = [], []
    for (pol, b, qid), r in records.items():
        if pol.endswith("@m47") or pol == "full_context":
            continue
        if r["prompt_tokens"] and r["memory_footprint_tokens"]:
            xs.append(r["memory_footprint_tokens"])
            ys.append(r["prompt_tokens"])
    xs, ys = np.array(xs), np.array(ys)
    k, c = np.polyfit(xs, ys, 1)
    resid = ys - (k * xs + c)
    r2 = 1 - float((resid ** 2).sum()) / float(((ys - ys.mean()) ** 2).sum())
    ratio_ci = 1.96 * float(resid.std()) / float(np.sqrt(len(xs)))
    tok = {"n": int(len(xs)), "slope_glm_per_cl100k": float(k),
           "intercept_template_overhead": float(c), "r2": float(r2),
           "slope_ci95_halfwidth": float(ratio_ci)}
    (DIAG / "token_accounting.json").write_text(
        json.dumps(tok, ensure_ascii=False, indent=1), encoding="utf-8")

    print("=== 检索诊断 (节选) ===")
    for r in rows:
        if r["budget"] in (512, 4096):
            print(f"{r['policy']:20s} B={r['budget']:5d} gold_recall={r['gold_recall']:.3f} "
                  f"acc|covered={r['acc_covered']:.3f} read_fail={r['read_fail_share']:.3f} "
                  f"retr_fail={r['retrieve_fail_share']:.3f}")
    print(f"\n=== Token 核算 === slope={k:.4f} (GLM token / cl100k token) "
          f"截距={c:.0f} R²={r2:.4f} n={len(xs)}")


if __name__ == "__main__":
    main()

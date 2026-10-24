# -*- coding: utf-8 -*-
"""E3 重排器实验结果判读 (ANALYSIS_PROTOCOL.md §5.1).

输入: results.jsonl (policy=retrieval_rerank / dense_retrieval_rr /
      dense_retrieval_bb) + tables/rerank_ranking.json (离线 Recall@k)
输出: tables/rerank_eval.json —— 逐格 relaxed EM + @4096 配对 McNemar
      + 预注册判读 ("排名问题" vs "读取侧天花板")。

判读规则 (与用户确认的主判据, 2026-08-24):
  主判据 = retrieval_rerank vs retrieval @4096 逐题 relaxed EM 的精确 McNemar:
    p < 0.05 且 Δ > 0  -> "排名问题" (更好排序能把金证据顶进预算并改变答题)
    否则               -> "读取侧天花板" (2048 后平台非排序所致)
  佐证 (不用于判据): dense 腿 rr vs bb (重排效应), bb vs dense_retrieval
  (编码器升级效应, 回应"低估 dense")。
前置断言: 三条新 policy × 4 预算每格 n=120 且无空调用记录 (缺口重补契约)。
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from common import BUDGETS, load_questions
from score import mcnemar_exact, paired_bootstrap

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "output" / "longmemeval"
TAB = OUT / "tables"

NEW_POLS = ["retrieval_rerank", "dense_retrieval_rr", "dense_retrieval_bb"]
BASE_POLS = ["retrieval", "dense_retrieval", "hybrid_retrieval"]

# Addendum B: 确定性 contentFilter (Zhipu 1301) 拒答题 —— 主网格 62 条空记录
# 的真实失败模式 (非 429)。敏感性分析排除这 4 题 (n=116)。
FILTER_QIDS = {"8550ddae", "a06e4cfe", "3b6f954b", "gpt4_372c3eed"}


def _is_refusal(err: str) -> bool:
    return "1301" in err or "contentFilter" in err or "content filter" in err


def load_records() -> list[dict]:
    sample = {q.question_id for q in load_questions()}
    recs = []
    for line in (OUT / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r["question_id"] in sample:
                recs.append(r)
    return recs


def main() -> None:
    recs = load_records()
    g: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for r in recs:
        if r["policy"] in NEW_POLS + BASE_POLS:
            g[(r["policy"], r["budget"])][r["question_id"]] = r
    qids = sorted({q.question_id for q in load_questions()})

    # ---------- 前置断言: 完整性 ----------
    # 完整 = 每格 n=120 且空记录全部为 contentFilter 拒答 (确定性, 按 0 计分
    # 并披露); 429 等瞬态故障空记录不允许 (Addendum B)。
    completeness = {}
    complete = True
    for pol in NEW_POLS:
        for b in BUDGETS:
            cell = g.get((pol, b), {})
            missing = [q for q in qids if q not in cell]
            refusals = [q for q, r in cell.items()
                        if not r["pred"].strip() and _is_refusal(r.get("api_error", ""))]
            infra = [q for q, r in cell.items()
                     if not r["pred"].strip() and q not in refusals]
            completeness[f"{pol}@{b}"] = {
                "n": len(cell), "missing": len(missing),
                "filter_refusals": len(refusals), "infra_failures": len(infra)}
            if missing or infra:
                complete = False

    # ---------- 逐格 relaxed EM ----------
    def vec(pol: str, b: int) -> list[float]:
        cell = g.get((pol, b), {})
        return [cell[q]["relaxed_em"] if q in cell else 0.0 for q in qids]

    cells = {}
    for pol in NEW_POLS + BASE_POLS:
        for b in BUDGETS:
            cell = g.get((pol, b), {})
            if not cell:
                continue
            cells[f"{pol}@{b}"] = {
                "n": len(cell),
                "relaxed_em": sum(r["relaxed_em"] for r in cell.values()) / len(cell),
                "em": sum(r["em"] for r in cell.values()) / len(cell),
            }

    # ---------- @4096 配对检验 (主判据 + 佐证) ----------
    B = 4096
    comparisons = {}

    def compare(name: str, a_pol: str, b_pol: str) -> None:
        a, b = vec(a_pol, B), vec(b_pol, B)
        (ma, mb, p_gt), ci = paired_bootstrap(a, b)
        comparisons[name] = {
            "a": a_pol, "b": b_pol, "budget": B,
            "a_relaxed_em": ma, "b_relaxed_em": mb, "delta": ma - mb,
            "mcnemar": mcnemar_exact(a, b),
            "delta_ci95": ci,
        }

    compare("primary_bm25_rerank_vs_base", "retrieval_rerank", "retrieval")
    compare("dense_rerank_effect", "dense_retrieval_rr", "dense_retrieval_bb")
    compare("dense_encoder_effect", "dense_retrieval_bb", "dense_retrieval")

    # ---------- 敏感性分析: 排除 contentFilter 拒答题 (Addendum B) ----------
    sens_qids = [q for q in qids if q not in FILTER_QIDS]

    def vec_sens(pol: str, b: int) -> list[float]:
        cell = g.get((pol, b), {})
        return [cell[q]["relaxed_em"] if q in cell else 0.0 for q in sens_qids]

    comparisons_sens = {}

    def compare_sens(name: str, a_pol: str, b_pol: str) -> None:
        a, b = vec_sens(a_pol, B), vec_sens(b_pol, B)
        (ma, mb, _), ci = paired_bootstrap(a, b)
        comparisons_sens[name] = {
            "a": a_pol, "b": b_pol, "budget": B, "n": len(sens_qids),
            "a_relaxed_em": ma, "b_relaxed_em": mb, "delta": ma - mb,
            "mcnemar": mcnemar_exact(a, b), "delta_ci95": ci,
        }

    compare_sens("primary_bm25_rerank_vs_base", "retrieval_rerank", "retrieval")
    compare_sens("dense_rerank_effect", "dense_retrieval_rr", "dense_retrieval_bb")
    compare_sens("dense_encoder_effect", "dense_retrieval_bb", "dense_retrieval")

    # ---------- 预注册判读 (双口径, Addendum B) ----------
    pri = comparisons["primary_bm25_rerank_vs_base"]
    pris = comparisons_sens["primary_bm25_rerank_vs_base"]
    sig = lambda c: c["mcnemar"]["p_value"] < 0.05 and c["delta"] > 0  # noqa: E731
    if not complete:
        judgment = "INCOMPLETE"
    elif sig(pri) and sig(pris):
        judgment = "排名问题"
    elif not sig(pri) and not sig(pris):
        judgment = "读取侧天花板"
    else:
        judgment = ("MIXED: 主口径与排除过滤题口径不一致 "
                    "(contentFilter 伪影影响判读, 两种口径如实报告)")

    # ---------- 离线 Recall@k (rerank_ranking.json) ----------
    offline = None
    rr_path = TAB / "rerank_ranking.json"
    if rr_path.exists():
        rr = json.loads(rr_path.read_text(encoding="utf-8"))
        offline = {}
        for key in ("bm25_base", "bm25_rerank", "dense_base", "dense_rerank"):
            agg = defaultdict(list)
            for qd in rr.values():
                for m, v in qd[key].items():
                    agg[m].append(v)
            offline[key] = {m: sum(v) / len(v) for m, v in agg.items()}

    out = {
        "experiment": "E3 reranker (bge-reranker-base) + dense upgrade (bge-base)",
        "protocol": "ANALYSIS_PROTOCOL.md §5.1 + Addendum B; 判读口径: @4096 精确 "
                    "McNemar p<0.05 且 Δ>0, 主口径 n=120 / 敏感性口径排除 "
                    "contentFilter 拒答题 n=116, 两口径不一致时报 MIXED",
        "n_questions": len(qids),
        "filter_refusal_questions": sorted(FILTER_QIDS),
        "completeness": completeness,
        "complete": complete,
        "cells": cells,
        "comparisons_at_4096": comparisons,
        "comparisons_at_4096_excl_filter": comparisons_sens,
        "judgment": judgment,
        "judgment_rule": (
            "retrieval_rerank vs retrieval @4096: 主口径与敏感性口径均显著 "
            "=> 排名问题; 均不显著 => 读取侧天花板; 仅一口径显著 => MIXED "
            "(contentFilter 伪影, 两种口径如实报告)"
        ),
        "offline_session_recall": offline,
    }
    (TAB / "rerank_eval.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"complete={complete}  judgment={judgment}")
    for name, c in comparisons.items():
        print(f"{name}: {c['a']} {c['a_relaxed_em']:.4f} vs {c['b']} "
              f"{c['b_relaxed_em']:.4f}  Δ={c['delta']:+.4f}  "
              f"McNemar p={c['mcnemar']['p_value']:.4f}")
    print("--- 敏感性 (排除 contentFilter 拒答题) ---")
    for name, c in comparisons_sens.items():
        print(f"{name}: Δ={c['delta']:+.4f}  McNemar p={c['mcnemar']['p_value']:.4f}  (n={c['n']})")
    if offline:
        print("offline Recall@5:", {k: round(v["recall@5"], 3)
                                    for k, v in offline.items()})
    print(f"written -> {TAB / 'rerank_eval.json'}")


if __name__ == "__main__":
    main()

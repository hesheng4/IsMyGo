# -*- coding: utf-8 -*-
"""E1 结构化压缩器判读 (ANALYSIS_PROTOCOL.md §3, D2).

输入: results_kv.jsonl / results_edu.jsonl (compression@kv / compression@edu)
      + results.jsonl (compression=freeform w60, retrieval=BM25, hierarchical)
输出: tables/struct_eval.json —— 全 4 预算曲线 + @4096 gap-closed (主/第二对照)
      + KV vs freeform 配对 McNemar + 三档预注册判读 (双口径, Addendum B)
      + 三变体每会话 footprint 均值 (词数 + token)。

判读规则 (§3.3, KV 主点 @4096, relaxed EM, n=120):
  gap-closed = (struct - freeform) / (retrieval_BM25 - freeform)
  < 20%   -> "结构不救" (有损压缩普遍失败)
  20-60%  -> "结构部分救回" (需 KV vs freeform McNemar p<0.05, 否则降档措辞)
  >=60% 或 struct >= retrieval -> "自由形式才是主因" (负结果限缩, 触发 §3.4 全 500 题)
EDU 佐证, 不同档时如实报告不取有利者。第二对照 (最强替代, 含 hierarchical)
并报不用于判据。
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

STRUCT_POLS = {"kv": "compression@kv", "edu": "compression@edu"}
BASE_POLS = {"freeform": "compression", "retrieval": "retrieval",
             "hierarchical": "hierarchical"}
B = 4096  # 决策档 (压缩最有利)

# Addendum B: 确定性 contentFilter (Zhipu 1301) 拒答题, 敏感性口径排除 (n=116)
FILTER_QIDS = {"8550ddae", "a06e4cfe", "3b6f954b", "gpt4_372c3eed"}


def _is_refusal(err: str) -> bool:
    return "1301" in err or "contentFilter" in err or "content filter" in err


def load_all() -> dict[tuple, dict[str, dict]]:
    sample = {q.question_id for q in load_questions()}
    g: dict[tuple, dict[str, dict]] = defaultdict(dict)
    files = [OUT / "results_kv.jsonl", OUT / "results_edu.jsonl",
             OUT / "results.jsonl"]
    want = set(STRUCT_POLS.values()) | set(BASE_POLS.values())
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r["policy"] in want and r["question_id"] in sample:
                    g[(r["policy"], r["budget"])][r["question_id"]] = r
    return g


def main() -> None:
    g = load_all()
    qids = sorted({q.question_id for q in load_questions()})

    # ---------- 完整性断言 (KV/EDU 每格 n=120, 空记录仅允许 contentFilter) ----------
    completeness = {}
    complete = True
    for name, pol in STRUCT_POLS.items():
        for b in BUDGETS:
            cell = g.get((pol, b), {})
            missing = [q for q in qids if q not in cell]
            refusals = [q for q, r in cell.items()
                        if not r["pred"].strip() and _is_refusal(r.get("api_error", ""))]
            infra = [q for q, r in cell.items()
                     if not r["pred"].strip() and q not in refusals]
            completeness[f"{name}@{b}"] = {
                "n": len(cell), "missing": len(missing),
                "filter_refusals": len(refusals), "infra_failures": len(infra)}
            if missing or infra:
                complete = False

    # ---------- 逐格 relaxed EM (全 4 预算曲线) ----------
    def vec(pol: str, b: int, qs: list[str]) -> list[float]:
        cell = g.get((pol, b), {})
        return [cell[q]["relaxed_em"] if q in cell else 0.0 for q in qs]

    cells = {}
    for name, pol in list(STRUCT_POLS.items()) + list(BASE_POLS.items()):
        for b in BUDGETS:
            cell = g.get((pol, b), {})
            if cell:
                cells[f"{name}@{b}"] = {
                    "n": len(cell),
                    "relaxed_em": sum(r["relaxed_em"] for r in cell.values()) / len(cell),
                    "em": sum(r["em"] for r in cell.values()) / len(cell),
                }

    # ---------- @4096: gap-closed + 配对检验 (双口径) ----------
    def gap_closed(struct_pol: str, denom_pol: str, qs: list[str]) -> dict:
        s = vec(struct_pol, B, qs)
        f = vec(BASE_POLS["freeform"], B, qs)
        d = vec(denom_pol, B, qs)
        ms = sum(s) / len(s)
        mf = sum(f) / len(f)
        md = sum(d) / len(d)
        (ma, mb, _), ci = paired_bootstrap(s, f)
        return {
            "struct_relaxed_em": ms, "freeform_relaxed_em": mf,
            "denominator_policy": denom_pol, "denominator_relaxed_em": md,
            "gap_closed": (ms - mf) / (md - mf) if md != mf else None,
            "struct_ge_denominator": ms >= md,
            "mcnemar_struct_vs_freeform": mcnemar_exact(s, f),
            "delta_struct_vs_freeform": ma - mb,
            "delta_ci95": ci,
        }

    sens_qids = [q for q in qids if q not in FILTER_QIDS]
    analysis = {}
    for caliber, qs in (("main", qids), ("excl_filter", sens_qids)):
        analysis[caliber] = {
            "n": len(qs),
            "kv_vs_bm25": gap_closed(STRUCT_POLS["kv"], BASE_POLS["retrieval"], qs),
            "edu_vs_bm25": gap_closed(STRUCT_POLS["edu"], BASE_POLS["retrieval"], qs),
            "kv_vs_strongest": gap_closed(STRUCT_POLS["kv"], BASE_POLS["hierarchical"], qs),
            "edu_vs_strongest": gap_closed(STRUCT_POLS["edu"], BASE_POLS["hierarchical"], qs),
        }

    # ---------- 三档预注册判读 (KV 主点, 主口径; 敏感性并报) ----------
    def tier(gc, struct_ge_den, sig) -> str:
        if gc is None:
            return "UNDEFINED (分母为零)"
        if gc >= 0.60 or struct_ge_den:
            return "自由形式才是主因 (负结果限缩为 free-form-specific; 结构化压缩可用)"
        if gc >= 0.20:
            return ("结构部分救回、仍低于逐字检索" +
                    ("" if sig else " [KV vs freeform 不显著, 按更弱档措辞]"))
        return "结构不救 (有损压缩普遍失败, 最强泛化)"

    judgments = {}
    for caliber in ("main", "excl_filter"):
        a = analysis[caliber]["kv_vs_bm25"]
        sig = (a["mcnemar_struct_vs_freeform"]["p_value"] < 0.05
               and a["delta_struct_vs_freeform"] > 0)
        judgments[caliber] = {
            "kv_tier": tier(a["gap_closed"], a["struct_ge_denominator"], sig),
            "kv_significant_vs_freeform": sig,
            "edu_tier": tier(analysis[caliber]["edu_vs_bm25"]["gap_closed"],
                             analysis[caliber]["edu_vs_bm25"]["struct_ge_denominator"],
                             analysis[caliber]["edu_vs_bm25"]["mcnemar_struct_vs_freeform"]["p_value"] < 0.05),
        }
    trigger_500 = (analysis["main"]["kv_vs_bm25"]["gap_closed"] is not None
                   and analysis["main"]["kv_vs_bm25"]["gap_closed"] >= 0.60)

    # ---------- footprint: 三变体每会话均值 (词数 + token) ----------
    footprint = {}
    for name, pol in list(STRUCT_POLS.items()) + [("freeform", "compression")]:
        toks = [r["memory_footprint_tokens"] for b in BUDGETS
                for r in g.get((pol, b), {}).values()]
        footprint[name] = {
            "mean_memory_footprint_tokens": sum(toks) / len(toks) if toks else None,
        }
    # 词数: 直接从摘要缓存统计 (三变体同 5422 会话域)
    for name, cdir in (("kv", OUT / "cache" / "summaries_struct" / "kv"),
                       ("edu", OUT / "cache" / "summaries_struct" / "edu"),
                       ("freeform", OUT / "cache" / "summaries")):
        ws = []
        for p in cdir.glob("*.json"):
            try:
                txt = json.loads(p.read_text(encoding="utf-8"))["text"]
                ws.append(len(txt.split()))
            except Exception:  # noqa: BLE001
                pass
        if name in footprint:
            footprint[name]["mean_summary_words"] = sum(ws) / len(ws) if ws else None
            footprint[name]["n_summaries"] = len(ws)

    out = {
        "experiment": "E1 structured compressor (KV verbatim / EDU verbatim) vs freeform w60",
        "protocol": "ANALYSIS_PROTOCOL.md §3 + Addendum B; 主判据 KV @4096 relaxed EM "
                    "n=120, gap-closed 分母=BM25 retrieval; 敏感性口径排除 "
                    "contentFilter 拒答题 n=116; 第二对照 (hierarchical) 并报不用于判据",
        "n_questions": len(qids),
        "filter_refusal_questions": sorted(FILTER_QIDS),
        "completeness": completeness,
        "complete": complete,
        "cells": cells,
        "analysis_at_4096": analysis,
        "judgments": judgments,
        "trigger_full_500_confirmation": trigger_500,
        "footprint": footprint,
    }
    (TAB / "struct_eval.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"complete={complete}")
    for caliber in ("main", "excl_filter"):
        a = analysis[caliber]
        print(f"--- {caliber} (n={a['n']}) ---")
        for k in ("kv_vs_bm25", "edu_vs_bm25", "kv_vs_strongest", "edu_vs_strongest"):
            c = a[k]
            gc = c["gap_closed"]
            print(f"{k}: struct={c['struct_relaxed_em']:.4f} freeform="
                  f"{c['freeform_relaxed_em']:.4f} den={c['denominator_relaxed_em']:.4f}"
                  f" gap-closed={'None' if gc is None else f'{gc:.1%}'}"
                  f" p={c['mcnemar_struct_vs_freeform']['p_value']:.4f}")
        print(f"KV 档: {judgments[caliber]['kv_tier']}")
        print(f"EDU 档: {judgments[caliber]['edu_tier']}")
    print(f"触发全 500 题确认跑: {trigger_500}")
    print("footprint:", json.dumps(footprint, ensure_ascii=False))
    print(f"written -> {TAB / 'struct_eval.json'}")


if __name__ == "__main__":
    main()

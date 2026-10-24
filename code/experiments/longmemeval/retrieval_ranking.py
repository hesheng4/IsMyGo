# -*- coding: utf-8 -*-
"""检索排名诊断: 会话级 Recall@k / NDCG@k 对金证据 (零 LLM 成本)。

目的: 在"写入-检索-读取"三段中定位失效环节。已有 diagnostics.py 只报告
"金会话是否进了上下文"(二值, 受预算截断污染); 本脚本报告纯排名质量 ——
不做预算截断, 只看金会话 (answer_session_ids) 在各 ranker 全量排序中的深度。

Ranker (与 policies.py 装配所用的完全同一函数, 无预算截断):
  bm25    : _bm25_rank  (retrieval / retrieval_recency / hierarchical 的检索腿)
  dense   : _dense_rank (dense_retrieval)
  hybrid  : _rrf_rank   (hybrid_retrieval)
  recency : 会话按最近出现 (sliding_window 的参照系)

会话级聚合: 轮次排序 -> 会话首次出现序 (= 成员最高分序)。
金标签: q.answer_session_ids (LongMemEval-S 会话级金证据, 中位数 2 个/题)。

输出: tables/retrieval_ranking.{json,tex}
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import defaultdict
from pathlib import Path

from common import BUDGETS, load_questions
from local_embed import QUERY_PREFIX, load as load_bge, question_vectors
from policies import _bm25_rank, _dense_rank, _rrf_rank

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "output" / "longmemeval"
DIAG = OUT / "tables"
Ks = [1, 2, 5, 10]


def _sess_order_from_turns(turns_order) -> list[str]:
    """轮次排序 -> 会话首次出现序 (即成员最高分序)。"""
    seen: list[str] = []
    s = set()
    for t in turns_order:
        if t.session_id not in s:
            s.add(t.session_id)
            seen.append(t.session_id)
    return seen


def _recall_ndcg(order: list[str], gold: set[str], k: int) -> tuple[float, float]:
    topk = set(order[:k])
    recall = len(gold & topk) / len(gold)
    dcg = sum(1.0 / math.log2(i + 2) for i, s in enumerate(order[:k]) if s in gold)
    n_rel = min(len(gold), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(n_rel))
    return recall, (dcg / idcg if idcg else 0.0)


def main() -> None:
    DIAG.mkdir(parents=True, exist_ok=True)
    questions = load_questions()
    logger.info(f"[rank] 题数={len(questions)}")

    turn_embs = load_bge({t.turn_key for q in questions for t in q.turns})
    qe_map = question_vectors(questions)
    logger.info(f"[rank] 向量: turns={len(turn_embs)} questions={len(qe_map)}")

    rankers = ["bm25", "dense", "hybrid", "recency"]
    per_q: dict[str, dict] = defaultdict(dict)
    gold_sizes: list[int] = []
    gold_ranks: dict[str, list[int]] = defaultdict(list)  # ranker -> 最深金会话的 1-based 排名

    for q in questions:
        turns = q.turns
        present = {t.session_id for t in turns}
        gold = set(q.answer_session_ids) & present
        gold_sizes.append(len(gold))
        qe = qe_map.get(q.question_id)

        if True:
            orders = {
                "bm25": _sess_order_from_turns(_bm25_rank(turns, q.question)),
                "dense": _sess_order_from_turns(_dense_rank(turns, qe, turn_embs))
                if qe else [],
                "hybrid": _sess_order_from_turns(_rrf_rank(turns, q, qe, turn_embs))
                if qe else [],
                "recency": [s for s in
                            {t.session_id for t in reversed(turns)}],
            }
            row = {}
            for r, order in orders.items():
                rk = {s: i + 1 for i, s in enumerate(order)}
                if gold:
                    gold_ranks[r].append(max(rk[s] for s in gold if s in rk))
                row[r] = {
                    "recall@%d" % k: _recall_ndcg(order, gold, k)[0]
                    for k in Ks
                }
                row[r]["ndcg@10"] = _recall_ndcg(order, gold, 10)[1]
                row[r]["n_sessions"] = len(order)
            per_q[q.question_id] = {"type": q.question_type, "gold": len(gold),
                                    **row}

    # ---------------- 汇总 ----------------
    agg: dict[str, list] = defaultdict(list)
    for row in per_q.values():
        for r in rankers:
            for k in Ks:
                agg[(r, "recall@%d" % k)].append(row[r]["recall@%d" % k])
            agg[(r, "ndcg@10")].append(row[r]["ndcg@10"])

    def mean(xs):
        return sum(xs) / len(xs) if xs else 0.0

    summary = {}
    for r in rankers:
        summary[r] = {"recall@%d" % k: mean(agg[(r, "recall@%d" % k)]) for k in Ks}
        summary[r]["ndcg@10"] = mean(agg[(r, "ndcg@10")])

    # 题型细分 (multi-session 金会话最多, 最该被检索拯救)
    by_type: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    for row in per_q.values():
        for r in rankers:
            for k in Ks:
                by_type[row["type"]][(r, "recall@%d" % k)].append(
                    row[r]["recall@%d" % k])

    out = {
        "k_values": Ks,
        "n_questions": len(questions),
        "gold_sessions": {
            "mean": mean(gold_sizes),
            "median": sorted(gold_sizes)[len(gold_sizes) // 2],
            "max": max(gold_sizes),
            "hist": {str(c): gold_sizes.count(c) for c in sorted(set(gold_sizes))},
        },
        "deepest_gold_rank_median": {
            r: sorted(v)[len(v) // 2] for r, v in gold_ranks.items()},
        "summary": summary,
        "by_type": {t: {f"{r}|{k}": mean(v)
                        for (r, k), v in sorted(d.items())}
                    for t, d in sorted(by_type.items())},
        "per_question": per_q,
    }
    (DIAG / "retrieval_ranking.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------- LaTeX ----------------
    BS = chr(92)
    tex = [BS + "begin{tabular}{l" + "c" * (len(Ks) + 1) + "}", BS + "toprule",
           "Ranker & " + " & ".join("R@" + str(k) for k in Ks)
           + " & NDCG@10 " + BS + BS, BS + "midrule"]
    for r in rankers:
        tex.append(
            " & ".join([r] + ["%.3f" % summary[r]["recall@%d" % k] for k in Ks]
                      + ["%.3f" % summary[r]["ndcg@10"]]) + " " + BS + BS)
    tex += [BS + "bottomrule", BS + "end{tabular}"]
    (DIAG / "retrieval_ranking.tex").write_text("\n".join(tex), encoding="utf-8")

    # ---------------- 控制台 ----------------
    gs = out["gold_sessions"]
    logger.info("金会话/题: mean=%.1f median=%d max=%d hist=%s" %
          (gs["mean"], gs["median"], gs["max"], gs["hist"]))
    logger.info("最深金会话中位排名:",
          {r: out["deepest_gold_rank_median"][r] for r in rankers})
    logger.info("\n=== 会话级检索排名 (全量, 无预算截断) ===")
    logger.info("%-8s " % "ranker" + "  ".join("R@%-3d" % k for k in Ks) + "  NDCG@10")
    for r in rankers:
        logger.info("%-8s " % r + "  ".join("%5.3f" % summary[r]["recall@%d" % k]
                                     for k in Ks) + "   %5.3f"
              % summary[r]["ndcg@10"])
    logger.info("\n=== 按题型 Recall@5 / Recall@10 (bm25 vs dense vs hybrid) ===")
    logger.info("%-28s" % "type" + "".join("%10s" % ("%s|%s" % (r, k))
                                     for r in ("bm25", "dense", "hybrid")
                                     for k in (5, 10)))
    for t, d in sorted(by_type.items()):
        logger.info("%-28s" % t + "".join(
            "%10.3f" % mean(d[(r, "recall@%d" % k)])
            for r in ("bm25", "dense", "hybrid") for k in (5, 10)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()

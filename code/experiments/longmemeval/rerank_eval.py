# -*- coding: utf-8 -*-
"""E3 本地重排器实验 (ANALYSIS_PROTOCOL.md §5.1).

问题: 主表中 retrieval/dense 在 B>=2048 后平台化 —— 是"排名问题"(更好的
排序能把金证据顶进预算) 还是"读取侧内在天花板"(排序再好答题也不变)?

设计 (与基线同预算, 唯一变量 = 排序器):
  retrieval_rerank   : BM25 候选 top-50 -> bge-reranker-base 交叉编码器重排 -> 按预算回填
  dense_retrieval_rr : dense(bge-base) 候选 top-50 -> 重排 -> 回填
  dense_retrieval_bb : dense(bge-base) 直填 (无重排) —— dense 升级消融
基线: retrieval (BM25 直填) / dense_retrieval (bge-small 直填, 已在 results.jsonl).
分解: dense_retrieval(bge-small) -> dense_retrieval_bb(bge-base) 隔离编码器效应;
      dense_retrieval_bb -> dense_retrieval_rr 隔离重排效应.

判定: @4096 重排若显著抬升 -> 排名问题; 若几乎不动 -> 读取侧天花板。
输出: results.jsonl 追加 policy=retrieval_rerank/dense_retrieval_rr/dense_retrieval_bb
      记录 + tables/rerank_ranking.json (重排后的会话级 Recall@k, 纯离线).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

from common import BUDGETS, format_context, load_questions, ntokens
from llm import MODEL_MAIN, answer_with_memory
from policies import _bm25_rank, _dense_rank, _fill_from_ranked, _turn_segments
from score import em, relaxed_em, token_f1

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "output" / "longmemeval"
CACHE = OUT / "cache"
# E3 dense 升级: dense 腿统一用 bge-base 向量 (embeddings_bge_base, 768 维);
# 与主表 dense_retrieval 基线 (bge-small) 的差异 = 编码器升级效应.
BGE_BASE_DIR = CACHE / "embeddings_bge_base"
RERANK_MODEL = HERE.parents[2] / "models" / "bge-reranker-base"
TOP_K = 50  # 候选池 (协议 §5.1: top-50)

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _load_vecs(d: Path, keys: set[str]) -> dict[str, list[float]]:
    out = {}
    for k in keys:
        p = d / f"{k}.json"
        if p.exists():
            out[k] = json.loads(p.read_text(encoding="utf-8"))["v"]
    return out


def _rerank_top50(qe, turn_embs, qtext: str, ranked: list, ce) -> list:
    """对 ranked 的前 TOP_K 个 turn 用交叉编码器重打分重排, 其余保持原序附后。"""
    top = ranked[:TOP_K]
    rest = ranked[TOP_K:]
    if not top:
        return rest
    docs = [t.text for t in top]
    pairs = [(qtext, d) for d in docs]
    scores = ce.predict(pairs, batch_size=64, show_progress_bar=False)
    order = sorted(range(len(top)), key=lambda i: -float(scores[i]))
    return [top[i] for i in order] + rest


def _rerank_recall(order_sessions: list[str], gold: set[str]) -> dict:
    import math
    out = {}
    for k in (1, 2, 5, 10):
        out["recall@%d" % k] = len(gold & set(order_sessions[:k])) / len(gold)
    dcg = sum(1.0 / math.log2(i + 2) for i, s in enumerate(order_sessions[:10]) if s in gold)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold), 10)))
    out["ndcg@10"] = dcg / idcg if idcg else 0.0
    return out


async def main() -> None:
    offline_only = "--offline-only" in sys.argv
    print("[rr] 加载 bge-reranker-base (CPU) ...", flush=True)
    from sentence_transformers import CrossEncoder
    ce = CrossEncoder(str(RERANK_MODEL))
    import torch
    torch.set_num_threads(8)  # 与 _bge_base_embed 同: 8 线程实测最优

    questions = load_questions()
    lim = [a for a in sys.argv if a.startswith("--limit=")]
    if lim:
        questions = questions[:int(lim[0].split("=")[1])]
    turn_keys = {t.turn_key for q in questions for t in q.turns}
    print("[rr] 加载 bge-base 向量 ...", flush=True)
    turn_embs = _load_vecs(BGE_BASE_DIR, turn_keys)
    print(f"[rr] turns={len(turn_embs)}/{len(turn_keys)}  (缺失=向量未生成, dense 腿将降级)", flush=True)
    qe_map = {}
    for q in questions:
        p = BGE_BASE_DIR / f"{_key(QUERY_PREFIX + q.question)}.json"
        if p.exists():
            qe_map[q.question_id] = json.loads(p.read_text(encoding="utf-8"))["v"]

    # ---------- 离线部分: 重排 + 重排后 Recall@k ----------
    rr_ranking = {}
    plans: dict[tuple, list] = {}  # (policy, budget, qid) -> segments
    for q in questions:
        qe = qe_map.get(q.question_id)
        bm25 = _bm25_rank(q.turns, q.question)
        dense = _dense_rank(q.turns, qe, turn_embs) if qe else bm25
        bm25_rr = _rerank_top50(qe, turn_embs, q.question, bm25, ce)
        dense_rr = _rerank_top50(qe, turn_embs, q.question, dense, ce)
        gold = set(q.answer_session_ids) & {t.session_id for t in q.turns}

        def sess_order(turns):
            seen, out = set(), []
            for t in turns:
                if t.session_id not in seen:
                    seen.add(t.session_id)
                    out.append(t.session_id)
            return out

        rr_ranking[q.question_id] = {
            "gold": len(gold),
            "bm25_rerank": _rerank_recall(sess_order(bm25_rr), gold),
            "dense_rerank": _rerank_recall(sess_order(dense_rr), gold),
            "bm25_base": _rerank_recall(sess_order(bm25), gold),
            "dense_base": _rerank_recall(sess_order(dense), gold),
        }
        for pol, rr in (("retrieval_rerank", bm25_rr),
                        ("dense_retrieval_rr", dense_rr),
                        ("dense_retrieval_bb", dense)):
            for b in BUDGETS:
                sel = _fill_from_ranked(rr, b, set())
                sel.sort(key=lambda t: (t.session_idx, t.turn_idx))
                plans[(pol, b, q.question_id)] = _turn_segments(sel)

    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    (OUT / "tables" / "rerank_ranking.json").write_text(
        json.dumps(rr_ranking, ensure_ascii=False, indent=1), encoding="utf-8")
    base_rr = {k: [rr_ranking[q][k]["recall@5"] for q in rr_ranking]
               for k in ("bm25_base", "bm25_rerank", "dense_base", "dense_rerank")}
    print("[rr] 重排后 Recall@5: " +
          "  ".join(f"{k}={sum(v)/len(v):.3f}" for k, v in base_rr.items()), flush=True)
    if offline_only:
        print("[rr] --offline-only: 跳过答题部分, done", flush=True)
        return

    # ---------- 答题部分 (API): 同预算, 唯一变量=排序 ----------
    # 失败调用落盘空记录 (pred="" 按 0 计分, 与主网格口径一致, 保持 n=120);
    # api_error 字段区分 contentFilter 1301 (确定性拒答, 重试无益) 与 429 等
    # 瞬态故障 (续跑时可重试)。依据: ANALYSIS_PROTOCOL.md Addendum B。
    def _is_refusal(err: str) -> bool:
        return "1301" in err or "contentFilter" in err or "content filter" in err

    existing: set[str] = set()
    rp = OUT / "results.jsonl"
    if rp.exists():
        for line in rp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r["policy"] in ("retrieval_rerank", "dense_retrieval_rr",
                                   "dense_retrieval_bb"):
                    if r["pred"].strip() or _is_refusal(r.get("api_error", "")):
                        existing.add(f"{r['policy']}|{r['budget']}|{r['question_id']}")
    adir = CACHE / "answers"
    adir.mkdir(parents=True, exist_ok=True)
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(8)
    t0 = time.time()

    async def one(pol: str, b: int, q) -> None:
        tag = f"{pol}|{b}|{q.question_id}"
        if tag in existing:
            return
        async with sem:
            segs = plans[(pol, b, q.question_id)]
            fp = ntokens("\n\n".join(segs))
            try:
                ans = await answer_with_memory(
                    q.question, q.question_date, format_context(segs),
                    adir, f"{pol}|{b}|{q.question_id}")
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {str(e)[:200]}"
                print(f"[rr FAIL] {pol}@{b} {q.question_id[:12]} {err[:60]}", flush=True)
                rec = {
                    "policy": pol, "budget": b, "question_id": q.question_id,
                    "question_type": q.question_type, "gold": q.answer, "pred": "",
                    "em": 0.0, "relaxed_em": 0.0, "f1": 0.0,
                    "memory_footprint_tokens": fp, "n_turns": sum(1 for _ in q.turns),
                    "n_summaries": 0, "access_ms": 0.0,
                    "e2e_ms": 0.0, "prompt_tokens": 0, "completion_tokens": 0,
                    "api_error": err,
                }
                async with lock:
                    with rp.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                return
            pred = ans.get("text", "")
            rec = {
                "policy": pol, "budget": b, "question_id": q.question_id,
                "question_type": q.question_type, "gold": q.answer, "pred": pred,
                "em": em(pred, q.answer), "relaxed_em": relaxed_em(pred, q.answer),
                "f1": token_f1(pred, q.answer),
                "memory_footprint_tokens": fp, "n_turns": sum(1 for _ in q.turns),
                "n_summaries": 0, "access_ms": 0.0,
                "e2e_ms": ans.get("ms", 0.0),
                "prompt_tokens": ans.get("prompt_tokens", 0),
                "completion_tokens": ans.get("completion_tokens", 0),
            }
            async with lock:
                with rp.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[rr] {pol}@{b} {q.question_id[:12]} rel={rec['relaxed_em']:.0f}", flush=True)

    for pol in ("retrieval_rerank", "dense_retrieval_rr", "dense_retrieval_bb"):
        for b in BUDGETS:
            await asyncio.gather(*[one(pol, b, q) for q in questions])
            n_done = sum(1 for q in questions
                         if f"{pol}|{b}|{q.question_id}" in existing)
            print(f"[rr] {pol}@{b} {n_done}/{len(questions)}  ({time.time()-t0:.0f}s)", flush=True)
    print("[rr] E3 done", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

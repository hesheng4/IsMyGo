# -*- coding: utf-8 -*-
"""E0-cleanup: 重跑 main-120 受约束策略的空调用记录 (ANALYSIS_PROTOCOL.md A3).

背景: RESOURCE_REPORT 记录的 429 风暴期间, 部分 answer_with_memory 调用
在客户端层失败 (run.py except 分支), 以 pred="" / prompt_tokens=0 的空记录
写入 results.jsonl 并按 0 计分, 系统性压低各策略。

规则:
  - 只重跑 prompt_tokens == 0 的记录 (客户端层失败, 未产生真实 API 调用);
    pred 为空但 prompt_tokens > 0 的真实调用不动 (是合法观测)。
  - full_context 不重跑 (A1 用户决议: oracle 完成子集口径)。
  - 失败调用的答案缓存文件不存在 (answer_with_memory 抛异常前不落盘);
    若存在含空文本的缓存文件则先删除再重调 (防御 200-空响应被缓存)。
  - results.jsonl 原地替换记录, 事前备份。

执行结果 (2026-08-24, Addendum B 依据):
  62/62 全部为确定性 contentFilter 拒答 (Zhipu 1301,
  {'contentFilter': [{'level': 1, 'role': 'user'}]}), 零条 429 瞬态故障。
  A3 "重跑清洗" 不可行 —— 这些空记录按 0 计分保留并披露。
  触发题: 8550ddae(26格) / a06e4cfe(26格) / 3b6f954b(9格) / gpt4_372c3eed(1格)。
  过滤依赖装配上下文内容: BM25 检索类大预算必中, 摘要类洗掉敏感内容通过。

用法:
  python e0_cleanup.py --dry   # 只报告, 不改文件
  python e0_cleanup.py         # 执行重跑 + 替换
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

from common import format_context, load_questions
from llm import MODEL_MAIN, answer_with_memory
from policies import build_memory
from score import em, relaxed_em, token_f1

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "output" / "longmemeval"
CACHE = OUT / "cache"
RP = OUT / "results.jsonl"


def load_summaries(max_words: int) -> dict[str, str]:
    sums: dict[str, str] = {}
    for f in (CACHE / "summaries").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("max_words", 60) == max_words:
            sums[d["session_id"]] = d["text"]
    return sums


def answer_cache_file(cache_key: str) -> Path:
    h = hashlib.sha1(f"answer:v2:{cache_key}".encode("utf-8")).hexdigest()[:16]
    return CACHE / "answers" / f"{h}.json"


def variant_split(policy_field: str) -> tuple[str, str]:
    """'compression@w20' -> ('compression', '@w20'); 'retrieval' -> ('retrieval', '')"""
    if "@" in policy_field:
        base, var = policy_field.split("@", 1)
        return base, "@" + var
    return policy_field, ""


async def main() -> None:
    dry = "--dry" in sys.argv
    questions = {q.question_id: q for q in load_questions()}
    lines = RP.read_text(encoding="utf-8").splitlines()
    records = [json.loads(l) for l in lines if l.strip()]

    # ---------- 扫描空调用记录 ----------
    targets = []  # (line_idx, record)
    for i, r in enumerate(records):
        if r["question_id"] not in questions:
            continue  # 只处理 120 样本 (m47 子集等另有口径)
        if r["policy"] == "full_context":
            continue  # A1: oracle 不重跑
        if r.get("prompt_tokens", 0) == 0:
            targets.append((i, r))

    print(f"[e0] results.jsonl 总记录 {len(records)}, 120 样本内空调用 {len(targets)} 条")
    by_pol = Counter(f"{r['policy']}@{r['budget']}" for _, r in targets)
    for k in sorted(by_pol):
        print(f"      {k}: {by_pol[k]}")

    # 缓存文件状态 (应为"不存在")
    cached = [t for _, r in targets if (t := answer_cache_file(
        f"{r['policy']}|{r['budget']}|{r['question_id']}")).exists()]
    print(f"[e0] 空记录中已存在答案缓存文件: {len(cached)} (将删除后重调)")

    if dry:
        print("[e0] --dry: 只报告, 不改动")
        return
    if not targets:
        print("[e0] 无需清理")
        return

    # ---------- 装配输入 (按需懒加载) ----------
    sums_cache: dict[int, dict[str, str]] = {}
    turn_embs = None
    qe_map = None

    def get_sums(max_words: int) -> dict[str, str]:
        if max_words not in sums_cache:
            sums_cache[max_words] = load_summaries(max_words)
        return sums_cache[max_words]

    need_dense = any(variant_split(r["policy"])[0] in ("dense_retrieval", "hybrid_retrieval")
                     for _, r in targets)
    if need_dense:
        from local_embed import load as load_bge, question_vectors
        keys = set()
        for _, r in targets:
            q = questions[r["question_id"]]
            if variant_split(r["policy"])[0] in ("dense_retrieval", "hybrid_retrieval"):
                keys |= {t.turn_key for t in q.turns}
        turn_embs = load_bge(keys)
        qe_map = question_vectors(list(questions.values()))
        print(f"[e0] bge-small 向量: turns={len(turn_embs)} questions={len(qe_map)}")

    # ---------- 重跑 ----------
    t0 = time.time()
    sem = asyncio.Semaphore(8)
    replaced: dict[int, dict] = {}
    failed: list[str] = []

    async def rerun(i: int, r: dict) -> None:
        pol_field = r["policy"]
        base_pol, variant = variant_split(pol_field)
        q = questions[r["question_id"]]
        budget = r["budget"]
        key = f"{pol_field}|{budget}|{q.question_id}"

        # 摘要变体: '' -> w60; '@w20'/'@w120' -> 对应桶
        sums = {}
        if base_pol == "compression" or base_pol.startswith("hierarchical"):
            mw = {"": 60, "@w20": 20, "@w120": 120}.get(variant, 60)
            sums = get_sums(mw)
        qe = qe_map.get(q.question_id) if qe_map else None

        plan = build_memory(base_pol, q, budget, sums, qe=qe,
                            turn_embs=turn_embs, summary_variant=variant)
        cp = answer_cache_file(key)
        if cp.exists():
            d = json.loads(cp.read_text(encoding="utf-8"))
            if not d.get("text", "").strip():
                cp.unlink()  # 防御: 空文本缓存删掉重调
        async with sem:
            try:
                ans = await answer_with_memory(
                    q.question, q.question_date,
                    format_context(plan.segments), CACHE / "answers", key)
            except Exception as e:  # noqa: BLE001
                failed.append(key)
                print(f"[e0 FAIL] {key}: {type(e).__name__}: {str(e)[:60]}", flush=True)
                return
        replaced[i] = {
            "policy": pol_field, "budget": budget, "question_id": q.question_id,
            "question_type": q.question_type, "gold": q.answer, "pred": ans["text"],
            "em": em(ans["text"], q.answer),
            "relaxed_em": relaxed_em(ans["text"], q.answer),
            "f1": token_f1(ans["text"], q.answer),
            "memory_footprint_tokens": plan.footprint_tokens,
            "n_turns": plan.n_turns, "n_summaries": plan.n_summaries,
            "access_ms": round(plan.access_ms, 4),
            "e2e_ms": round(ans.get("ms", 0.0), 2),
            "prompt_tokens": ans.get("prompt_tokens", 0),
            "completion_tokens": ans.get("completion_tokens", 0),
        }
        print(f"[e0 ok] {key}  pred={ans['text'][:40]!r}", flush=True)

    await asyncio.gather(*(rerun(i, r) for i, r in targets))

    # ---------- 原地替换 + 备份 ----------
    if replaced:
        bak = RP.with_suffix(".jsonl.bak-pre-e0cleanup")
        bak.write_text(RP.read_text(encoding="utf-8"), encoding="utf-8")
        for i, new_rec in replaced.items():
            records[i] = new_rec
        with RP.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[e0] 替换 {len(replaced)}/{len(targets)} 条, 备份 -> {bak.name}")

    # ---------- 前后对比 ----------
    print(f"\n[e0] 耗时 {time.time()-t0:.0f}s; 失败 {len(failed)} 条 (保留原空记录)")
    if replaced:
        affected = sorted({f"{r['policy']}@{r['budget']}" for _, r in targets})
        sample_qids = set(questions)
        old_recs = [json.loads(l) for l in
                    RP.with_suffix(".jsonl.bak-pre-e0cleanup").read_text(
                        encoding="utf-8").splitlines() if l.strip()]
        for cell in affected:
            pol, b = cell.rsplit("@", 1)
            b = int(b)
            o = [r for r in old_recs if r["policy"] == pol and r["budget"] == b
                 and r["question_id"] in sample_qids]
            n = [r for r in records if r["policy"] == pol and r["budget"] == b
                 and r["question_id"] in sample_qids]
            if o and n:
                print(f"      {cell}: relEM {sum(r['relaxed_em'] for r in o)/len(o):.4f}"
                      f" -> {sum(r['relaxed_em'] for r in n)/len(n):.4f}  (n={len(n)})")


if __name__ == "__main__":
    asyncio.run(main())

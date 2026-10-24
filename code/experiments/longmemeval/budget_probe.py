# -*- coding: utf-8 -*-
"""Q6 预算扩展探针: retrieval / compression / hierarchical x {4096, 8192}, n=120.

审稿人问: 8k+ 预算下层级是否继续缩放、检索是否追赶、读侧天花板是否变化。
设计: glm-4.7-flash 同读者 (与 round-1 探针一致), T1 模板, 同装配代码
(policies.build_memory, 确定性); compression/hierarchical 复用冻结的
mimo 摘要缓存 (论文实际摘要, 零 LLM 调用), 只有答题调用 (720 次)。
记录: results_budget_probe.jsonl, 断点续跑按 (policy,budget,qid) 去重。
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import load_questions, ntokens  # noqa: E402
from llm import _chat, _needs_disable_thinking, ANSWER_SYS  # noqa: E402
from policies import build_memory  # noqa: E402
from score import em, relaxed_em, token_f1, paired_bootstrap, mcnemar_exact  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
READER = "deepseek-v4.1-flash"
CONCURRENCY = 4
BUDGETS = [4096, 8192]
POLICIES = ["retrieval", "compression", "hierarchical"]


def load_frozen_summaries() -> dict[str, str]:
    """直接读冻结摘要缓存 (mimo 生成, 论文实际摘要)。
    命名空间: model_cache_ns('mimo-v2.6-flash') = 'v2-mimo-v2.6-flash' (非 LEGACY);
    key = sha1('summary:v2-mimo-v2.6-flash:{sid}')[:16] = 文件名。"""
    import hashlib
    d = HERE.parents[1] / "output" / "longmemeval" / "cache" / "summaries"
    ns = "v2-mimo-v2.6-flash"
    out = {}
    for p in d.glob("*.json"):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            if j.get("model") == "mimo-v2.6-flash" and str(j.get("max_words")) == "60":
                sid = j["session_id"]
                key = hashlib.sha1(f"summary:{ns}:{sid}".encode()).hexdigest()[:16]
                if p.stem == key:
                    out[sid] = j["text"]
        except Exception:
            continue
    return out


async def main() -> None:
    questions = load_questions()
    summaries = load_frozen_summaries()
    print(f"[budget] reader={READER} questions={len(questions)} "
          f"frozen summaries={len(summaries)} cells={len(POLICIES)}x{len(BUDGETS)}")

    rp = OUT / "results_budget_probe.jsonl"
    existing: set = set()
    if rp.exists():
        for line in rp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                existing.add((r["policy"], r["budget"], r["question_id"]))
    print(f"[budget] 已有 {len(existing)} 条 (断点续跑)")

    sem = asyncio.Semaphore(CONCURRENCY)
    lock = asyncio.Lock()
    t0 = time.time()
    n_calls = 0

    async def one(pol: str, b: int, q) -> None:
        nonlocal n_calls
        if (pol, b, q.question_id) in existing:
            return
        plan = build_memory(pol, q, b, summaries)
        memory = "\n\n".join(plan.segments)
        date_line = f"(current date: {q.question_date})\n" if q.question_date else ""
        user = (f"Stored memory from past conversations:\n\n{memory}\n\n"
                f"{date_line}Based only on the memory above, answer:\n{q.question}")
        async with sem:
            try:
                out = await _chat(ANSWER_SYS, user, max_tokens=64, temperature=0.0,
                                  model=READER,
                                  disable_thinking=_needs_disable_thinking(READER),
                                  purpose="Q6预算扩展探针")
            except Exception as e:  # noqa: BLE001
                print(f"[budget FAIL] {pol}@{b} {q.question_id[:10]} {str(e)[:70]}", flush=True)
                return
        n_calls += 1
        rec = {
            "policy": pol, "budget": b, "question_id": q.question_id,
            "question_type": q.question_type, "gold": q.answer, "pred": out["text"],
            "em": em(out["text"], q.answer), "relaxed_em": relaxed_em(out["text"], q.answer),
            "f1": token_f1(out["text"], q.answer),
            "memory_footprint_tokens": plan.footprint_tokens,
            "e2e_ms": round(out["ms"], 2), "model": READER,
        }
        async with lock:
            with rp.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[budget] {pol}@{b} {q.question_id[:10]} rel={rec['relaxed_em']:.0f} "
              f"({time.time()-t0:.0f}s, {n_calls})", flush=True)

    for pol in POLICIES:
        for b in BUDGETS:
            await asyncio.gather(*(one(pol, b, q) for q in questions))
            print(f"[budget] cell {pol}@{b} done ({time.time()-t0:.0f}s)", flush=True)

    # 汇总
    by: dict = {}
    if rp.exists():
        for line in rp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                by.setdefault((r["policy"], r["budget"]), {})[r["question_id"]] = r
    print("\n=== 各格汇总 (relaxed EM / EM / F1, n per cell) ===")
    for pol in POLICIES:
        for b in BUDGETS:
            recs = list(by.get((pol, b), {}).values())
            if not recs:
                continue
            n = len(recs)
            print(f"{pol:14s}@{b:<5d} n={n:3d}  "
                  f"EM_rel={sum(r['relaxed_em'] for r in recs)/n:.4f}  "
                  f"EM={sum(r['em'] for r in recs)/n:.4f}  "
                  f"F1={sum(r['f1'] for r in recs)/n:.4f}")
    print("\n=== 配对 (4096 vs 8192, 同策略) ===")
    for pol in POLICIES:
        lo_, hi_ = by.get((pol, 4096), {}), by.get((pol, 8192), {})
        ids = sorted(set(lo_) & set(hi_))
        if len(ids) < 5:
            continue
        xa = [lo_[i]["relaxed_em"] for i in ids]
        xb = [hi_[i]["relaxed_em"] for i in ids]
        (_, _, _), (lo, hi) = paired_bootstrap(xb, xa)
        mc = mcnemar_exact(xb, xa)
        print(f"{pol:14s} 4096->8192: delta={sum(xb)/len(xb)-sum(xa)/len(xa):+.4f} "
              f"[{lo:+.4f},{hi:+.4f}]  p={mc['p_value']:.4f}")
    print(f"\n[budget] done: {n_calls} new calls, wall {time.time()-t0:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())

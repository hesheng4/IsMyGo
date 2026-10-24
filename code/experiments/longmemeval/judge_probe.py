# -*- coding: utf-8 -*-
"""LLM-judge 子集探针 (评审回应): 量化「读取失败」中有多少是意译惩罚。

取金证据已覆盖但 relaxed EM=0 的读取失败题 (每策略最多 30 题),
用 GLM-4.7-Flash 作裁判 (与答题器 GLM-4-Flash 不同, 降低循环论证),
判断候选答案与参考答案是否语义等价。
裁判通过率 = 读取失败中「其实答对了但被 EM 判错」的比例。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from common import load_questions
from llm import MODEL_ALT, _get_client

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "output" / "longmemeval"
CACHE = OUT / "cache" / "judge"
MAX_PER_POLICY = 30
POLICIES = ("compression", "retrieval", "hierarchical")

JUDGE_SYS = (
    "You are a strict but fair evaluation judge for a memory question-answering "
    "benchmark. You decide whether a candidate answer is factually equivalent "
    "to the reference answer."
)


def judge_prompt(question: str, gold, pred: str) -> str:
    return (
        f"Question: {question}\n"
        f"Reference answer: {gold}\n"
        f"Candidate answer: {pred}\n\n"
        "Does the candidate answer convey the same core fact as the reference "
        "answer? Paraphrasing, rewording, additional detail, or different "
        "surface form are all acceptable as long as the core fact matches. "
        "Reply with exactly one word: CORRECT or INCORRECT."
    )


async def judge_one(question: str, gold, pred: str, cache_key: str) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    cp = CACHE / f"{cache_key}.json"
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))["verdict"]
    extra = {"extra_body": {"thinking": {"type": "disabled"}}}
    for attempt in range(6):
        try:
            resp = await _get_client().chat.completions.create(
                model=MODEL_ALT,
                messages=[
                    {"role": "system", "content": JUDGE_SYS},
                    {"role": "user", "content": judge_prompt(question, gold, pred)},
                ],
                temperature=0, max_tokens=8, **extra,
            )
            text = (resp.choices[0].message.content or "").strip().upper()
            verdict = "CORRECT" if text.startswith("CORRECT") else "INCORRECT"
            cp.write_text(json.dumps({"verdict": verdict, "raw": text},
                                     ensure_ascii=False), encoding="utf-8")
            return verdict
        except Exception:  # noqa: BLE001
            # GLM-4.7-Flash 服务端拥堵 (429/1305) 常态化: 深重试 + 抖动抢空窗
            import random
            await asyncio.sleep(min(150.0, 15.0 * (attempt + 1))
                                + random.uniform(0, 10))
    return "ERROR"


async def main() -> None:
    questions = {q.question_id: q for q in load_questions()}
    diag = json.loads((OUT / "tables" / "retrieval_diagnosis.json").read_text(encoding="utf-8"))
    read_fails = [
        r for r in diag["per_question"]
        if r["gold_hit"] and not r["correct"] and r["budget"] == 4096
        and r["policy"] in POLICIES
    ]
    recs = {}
    for line in (OUT / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            recs[(r["policy"], r["budget"], r["question_id"])] = r

    tasks = []
    meta = []
    for pol in POLICIES:
        cases = [r for r in read_fails if r["policy"] == pol][:MAX_PER_POLICY]
        for r in cases:
            rec = recs.get((pol, 4096, r["qid"]))
            if not rec:
                continue
            q = questions[r["qid"]]
            key = hashlib.sha1(f"judge:{pol}:{r['qid']}".encode()).hexdigest()[:16]
            tasks.append(judge_one(q.question, q.answer, rec["pred"], key))
            meta.append({"policy": pol, "qid": r["qid"],
                         "gold": q.answer, "pred": rec["pred"]})

    sem = asyncio.Semaphore(2)

    async def guarded(t):
        async with sem:
            return await t

    verdicts = await asyncio.gather(*(guarded(t) for t in tasks))

    agg = {p: {"n": 0, "flip": 0} for p in POLICIES}
    rows = []
    for m, v in zip(meta, verdicts):
        agg[m["policy"]]["n"] += 1
        flip = v == "CORRECT"
        if flip:
            agg[m["policy"]]["flip"] += 1
        rows.append({**m, "verdict": v})
    (OUT / "tables" / "judge_probe.json").write_text(
        json.dumps({"rows": rows, "summary": agg}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print("=== judge 探针 (读取失败题中裁判判对比例 = 意译惩罚估计) ===")
    for p in POLICIES:
        a = agg[p]
        rate = a["flip"] / a["n"] if a["n"] else 0
        print(f"{p:14s} n={a['n']:3d} 裁判判对={a['flip']:3d} ({rate:.1%})")


if __name__ == "__main__":
    asyncio.run(main())

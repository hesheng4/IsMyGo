"""W10 探针: 结构化 JSON 读取协议 (第五轮审稿: LongMemEval 建议的 CoN+JSON 强化).

对照: T1 (copy-exact, 主网格模板) vs T4 (JSON 结构化: 先列证据片段再给答案)
策略: retrieval @4096, 120 题分层子集, deepseek 读者。
输出: code/output/longmemeval/results_json_probe.jsonl (断点续跑)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import load_questions  # noqa: E402
from llm import _chat, MODEL_MAIN  # noqa: E402
from policies import build_memory  # noqa: E402
from score import relaxed_em, token_f1  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
RESULTS = OUT / "results_json_probe.jsonl"
CONC = int(os.environ.get("PAPER_LAB_CONCURRENCY", "24"))

SYS_JSON = (
    "You are answering questions about a user's past conversations. You will be given "
    "stored memory. Reply with a single JSON object and nothing else, of the form "
    '{"evidence": ["<verbatim quote 1>", "<verbatim quote 2>"], "answer": "<short answer>"}. '
    "Quote at most three verbatim spans that support the answer; then give the answer in the "
    "shortest form possible (a number, entity, date, or yes/no). If the memory does not contain "
    "the answer, use an empty evidence list and reply with your best guess."
)


async def one(q, sem, recs: list) -> None:
    async with sem:
        plan = build_memory("retrieval", q, 4096, {})
        mem = "\n".join(plan.segments)
        user = (
            f"Stored memory from past conversations:\n\n{mem}\n\n"
            f"Based only on the memory above, answer:\n{q.question}"
        )
        try:
            out = await _chat(SYS_JSON, user, max_tokens=256, temperature=0.0,
                              model=MODEL_MAIN, purpose="JSON模板探针")
        except Exception as e:  # noqa: BLE001
            print(f"[json][FAIL] {q.question_id}: {str(e)[:70]}", flush=True)
            return
        txt = out["text"].strip()
        ans = txt
        ev = []
        try:
            obj = json.loads(txt)
            ans = str(obj.get("answer", "")).strip()
            ev = obj.get("evidence", []) or []
        except Exception:
            m = re.search(r'"answer"\s*:\s*"([^"]*)"', txt)
            if m:
                ans = m.group(1)
        recs.append({
            "policy": "retrieval", "budget": 4096, "question_id": q.question_id,
            "question_type": q.question_type, "model": MODEL_MAIN,
            "pred": ans, "gold": q.answer, "raw": txt[:400],
            "n_evidence": len(ev),
            "relaxed_em": relaxed_em(ans, q.answer), "f1": token_f1(ans, q.answer),
            "prompt_tokens": out["prompt_tokens"],
            "completion_tokens": out["completion_tokens"],
        })


async def main() -> None:
    qs = load_questions()
    done = set()
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if MODEL_MAIN in str(r.get("model", "")):
                    done.add(r["question_id"])
    todo = [q for q in qs if q.question_id not in done]
    print(f"[json] QA={len(qs)} 已有={len(done)} 待跑={len(todo)}", flush=True)
    sem = asyncio.Semaphore(CONC)
    recs: list[dict] = []
    await asyncio.gather(*(one(q, sem, recs) for q in todo))
    with RESULTS.open("a", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if recs:
        n = len(recs)
        print(f"[json] done n={n} EM={sum(r['relaxed_em'] for r in recs)/n:.4f} "
              f"F1={sum(r['f1'] for r in recs)/n:.4f}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

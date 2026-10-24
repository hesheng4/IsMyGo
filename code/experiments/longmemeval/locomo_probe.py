"""LoCoMo 泛化探针 (第五轮审稿 W5: 单一数据集泛化外推).

数据: data/locomo10_partial.json — jsDelivr 镜像的截断文件, 恰含 5/10 个完整对话
      (199+105+193+260+242 = 999 QA; 诚实披露 "5 of 10 conversations")。
策略: retrieval / compression / hierarchical x {1024, 2048, 4096}
协议: 与主网格相同 (同 answer 模板, 同 relaxed EM / token-F1; LoCoMo 官方指标为 F1)
输出: code/output/locomeval/results_locomo.jsonl (断点续跑, 按 (policy,budget,qid,model))
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import Question, Turn  # noqa: E402
from llm import MODEL_MAIN, answer_with_memory, summarize_session  # noqa: E402
from policies import build_memory  # noqa: E402
from score import relaxed_em, token_f1  # noqa: E402

DATA = HERE.parents[2] / "data" / "locomo10_partial.json"
OUT = HERE.parents[1] / "output" / "locomeval"
RESULTS = OUT / "results_locomo.jsonl"
SUMDIR = OUT / "cache" / "summaries"
POLICIES = ["retrieval", "compression", "hierarchical"]
BUDGETS = [1024, 2048, 4096]
CONC = int(os.environ.get("PAPER_LAB_CONCURRENCY", "24"))


def load_locomo() -> list[Question]:
    raw = DATA.read_text(encoding="utf-8", errors="replace")
    dec = json.JSONDecoder()
    i = raw.find("[")
    objs = []
    while True:
        j = raw.find("{", i)
        if j < 0:
            break
        try:
            obj, end = dec.raw_decode(raw, j)
            objs.append(obj)
            i = end
        except Exception:
            break
    qs: list[Question] = []
    for cid, o in enumerate(objs):
        conv = o["conversation"]
        sess_keys = sorted(
            (k for k in conv if k.startswith("session_") and not k.endswith("date_time")),
            key=lambda k: int(k.split("_")[1]),
        )
        turns: list[Turn] = []
        for si, sk in enumerate(sess_keys, 1):
            for ti, d in enumerate(conv[sk]):
                turns.append(
                    Turn(
                        session_idx=si,
                        turn_idx=ti,
                        role=str(d.get("speaker", "?")),
                        content=str(d.get("text", "")),
                        session_id=f"C{cid}D{si}",
                    )
                )
        sids = sorted({t.session_id for t in turns})
        for qn, qa in enumerate(o["qa"]):
            ev = qa.get("evidence") or []
            asids = sorted(
                {f"C{cid}D{e.split(':')[0].lstrip('D')}" for e in ev if ":" in str(e)}
            )
            qs.append(
                Question(
                    question_id=f"locomo{cid}_{qn}",
                    question_type=f"cat{qa.get('category')}",
                    question=str(qa["question"]),
                    question_date="",
                    answer=str(qa.get("answer", "")),
                    turns=turns,
                    session_ids=sids,
                    answer_session_ids=asids,
                )
            )
    return qs


async def main() -> None:
    qs = load_locomo()
    print(f"[locomo] QA={len(qs)}  convs=5  reader={MODEL_MAIN}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)

    # 每会话摘要 (compression/hierarchical 需要)
    sess_turns: dict[str, list[Turn]] = {}
    for q in qs:
        for t in q.turns:
            sess_turns.setdefault(t.session_id, []).append(t)
    print(f"[locomo] unique sessions={len(sess_turns)}", flush=True)

    sem = asyncio.Semaphore(CONC)

    async def summ(sid: str, turns: list[Turn]) -> tuple[str, str]:
        async with sem:
            try:
                return sid, await summarize_session(sid, turns, SUMDIR, max_words=60)
            except Exception as e:  # noqa: BLE001
                print(f"[locomo][WARN] summary fail {sid}: {str(e)[:80]}", flush=True)
                return sid, ""

    summaries = dict(await asyncio.gather(*(summ(s, t) for s, t in sess_turns.items())))
    ok = sum(1 for v in summaries.values() if v)
    print(f"[locomo] summaries {ok}/{len(summaries)}", flush=True)

    # 断点续跑
    done: set[tuple] = set()
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if MODEL_MAIN in str(r.get("model", "")):
                    done.add((r["policy"], r["budget"], r["question_id"]))
    print(f"[locomo] 已有 {len(done)} 条", flush=True)

    for policy in POLICIES:
        for budget in BUDGETS:
            todo = [q for q in qs if (policy, budget, q.question_id) not in done]
            if not todo:
                print(f"[locomo] skip {policy}|{budget}", flush=True)
                continue
            print(f"[locomo] run {policy}|{budget} n={len(todo)}", flush=True)
            t0 = time.time()
            recs: list[dict] = []

            async def one(q: Question) -> None:
                async with sem:
                    t1 = time.perf_counter()
                    try:
                        plan = build_memory(policy, q, budget, summaries)
                        mem = "\n".join(plan.segments)
                        ans = await answer_with_memory(
                            q.question, q.question_date, mem,
                            OUT / "cache" / "answers",
                            f"{policy}|{budget}|{q.question_id}", model_tag=MODEL_MAIN,
                        )
                    except Exception as e:  # noqa: BLE001
                        print(f"[locomo][FAIL] {policy}|{budget}|{q.question_id}: {str(e)[:80]}",
                              flush=True)
                        return
                    e2e = (time.perf_counter() - t1) * 1000
                    recs.append({
                        "policy": policy, "budget": budget, "question_id": q.question_id,
                        "question_type": q.question_type, "model": MODEL_MAIN,
                        "pred": ans["text"], "gold": q.answer,
                        "relaxed_em": relaxed_em(ans["text"], q.answer),
                        "em": float(str(ans["text"]).strip().lower() == q.answer.strip().lower()),
                        "f1": token_f1(ans["text"], q.answer),
                        "prompt_tokens": ans["prompt_tokens"],
                        "completion_tokens": ans["completion_tokens"],
                        "e2e_ms": round(e2e, 1),
                        "memory_footprint_tokens": plan.footprint_tokens,
                    })

            await asyncio.gather(*(one(q) for q in todo))
            with RESULTS.open("a", encoding="utf-8") as f:
                for r in recs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n = len(recs)
            if n:
                print(f"[locomo] {policy}|{budget} done n={n} "
                      f"EM={sum(r['relaxed_em'] for r in recs)/n:.3f} "
                      f"F1={sum(r['f1'] for r in recs)/n:.3f} "
                      f"({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

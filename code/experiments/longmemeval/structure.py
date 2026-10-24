# -*- coding: utf-8 -*-
"""E1 结构化压缩器: KV 逐字事实 / EDU 逐字单元 (ANALYSIS_PROTOCOL.md §3, A7)。

与自由形式 w60 基线同预算: 60 词上限、同 max_tokens、GLM-4-Flash 贪心。
隔离约定 (A7):
  摘要缓存  OUT/cache/summaries_struct/{variant}/   key = struct:{variant}:{sid}
  答题缓存  OUT/cache/answers_struct/{variant}/     key = struct:{variant}|{B}|{qid}
  结果文件  OUT/results_{variant}.jsonl             policy = compression@{variant}
  (不进 results.jsonl / cache/summaries, 防污染 analyze.py 与 diagnostics.py)

用法:
  python structure.py --variant kv --phase summaries [--limit N]
  python structure.py --variant kv --phase answers  --budgets 512,1024,2048,4096
  python structure.py --variant kv --phase all
  smoke: python structure.py --variant kv --phase all --limit 3 --budgets 512
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent.parent / "output" / "longmemeval"
sys.path.insert(0, str(ROOT))

from common import BUDGETS, format_context, load_questions, unique_sessions  # noqa: E402
from llm import _cache_path, _chat, answer_with_memory  # noqa: E402
from policies import build_memory  # noqa: E402
from score import em, relaxed_em, token_f1  # noqa: E402

MAX_WORDS = 60  # 与 w60 自由形式基线同上限 (协议 §3.2 预算公平)
MAX_TOKENS = 140  # 与 w60 桶同 (_SUMMARY_CAPS[60])

KV_SYS = (
    "You compress a conversation session between a user and an assistant into a "
    "fact-dense key-value memory. For every fact output EXACTLY ONE line of the form "
    "'Label: value' (label and value on the same line, separated by ': '). Label is a "
    "short 1-3 word noun (e.g. Name, Lives in, Car, Birthday, Employer, Preference, "
    "Decision, Event, Correction); value copies the EXACT words, numbers and dates "
    "from the session verbatim. Do NOT output bare 'Key:' or 'Value:' lines. Keep "
    "names, dates, numbers, preferences, decisions, corrections and factual statements "
    "about the user. Drop greetings and filler. "
    f"Output at most {MAX_WORDS} words total, no preamble, no prose."
)

EDU_SYS = (
    "You extract elementary discourse units (EDUs) from a conversation session between "
    "a user and an assistant: the smallest self-contained factual statements. Copy each "
    "EDU VERBATIM from the session (exact words, numbers, dates, names) - do not "
    "paraphrase or merge sentences. Keep only factual statements about the user (names, "
    "dates, numbers, preferences, decisions, corrections, events). Drop greetings and "
    "filler. "
    f"Output at most {MAX_WORDS} words total, one EDU per line, no preamble."
)


def _sys(variant: str) -> str:
    return KV_SYS if variant == "kv" else EDU_SYS


def _sum_dir(variant: str) -> Path:
    return OUT / "cache" / "summaries_struct" / variant


async def gen_summaries(variant: str, limit: int | None) -> dict[str, str]:
    questions = load_questions()
    sessions = unique_sessions(questions)
    if limit:
        sessions = dict(list(sessions.items())[:limit])
    cdir = _sum_dir(variant)
    cdir.mkdir(parents=True, exist_ok=True)

    async def one(sid: str, turns: list) -> tuple[str, str | None]:
        key = f"struct:{variant}:{sid}"
        cp = _cache_path(cdir, key)
        if cp.exists():
            return sid, json.loads(cp.read_text(encoding="utf-8"))["text"]
        user = "\n".join(t.text for t in turns)
        try:
            out = await _chat(_sys(variant), user, MAX_TOKENS, 0.0)
            text = out.get("text", "").strip()
            if not text:
                return sid, None
            cp.write_text(json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8")
            return sid, text
        except Exception as e:  # noqa: BLE001  失败不缓存, 下轮重跑
            print(f"[summary FAIL] {sid[:16]} {type(e).__name__}: {str(e)[:60]}", flush=True)
            return sid, None

    sem = asyncio.Semaphore(8)

    async def guarded(sid, turns):
        async with sem:
            return await one(sid, turns)

    results = await asyncio.gather(*[guarded(s, t) for s, t in sessions.items()])
    ok = [s for s, t in results if t]
    fail = [s for s, t in results if not t]
    print(f"[summaries {variant}] {len(ok)}/{len(sessions)} ok, {len(fail)} fail", flush=True)
    return {s: t for s, t in results if t}


def _res_path(variant: str) -> Path:
    return OUT / f"results_{variant}.jsonl"


def _is_refusal(err: str) -> bool:
    """contentFilter 1301 确定性拒答 (Addendum B): 重试无益, 落盘空记录。"""
    return "1301" in err or "contentFilter" in err or "content filter" in err


def _load_done(variant: str, budget: int) -> set[str]:
    p = _res_path(variant)
    if not p.exists():
        return set()
    done = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r["budget"] != budget:
                continue
            # 成功记录, 或 contentFilter 拒答空记录 (不重试); 429 等瞬态失败
            # 不落盘 → 不在 done 中 → 下轮重跑
            if r.get("completion_tokens", 0) > 0 or (
                    not r.get("pred", "").strip()
                    and _is_refusal(r.get("api_error", ""))):
                done.add(r["question_id"])
    return done


async def _run_answers(
    variant: str,
    budgets: list[int],
    limit: int | None,
    concurrency: int,
    summaries: dict[str, str],
) -> None:
    questions = load_questions()
    if limit:
        questions = questions[:limit]
    adir = OUT / "cache" / "answers_struct" / variant
    adir.mkdir(parents=True, exist_ok=True)
    res_path = _res_path(variant)
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(concurrency)

    async def one(budget: int, q) -> None:
        done = _load_done(variant, budget)
        if q.question_id in done:
            return
        async with sem:
            plan = build_memory("compression", q, budget, summaries, summary_variant=variant)
            key = f"struct:{variant}|{budget}|{q.question_id}"
            t0 = time.time()
            try:
                ans = await answer_with_memory(
                    q.question, q.question_date, format_context(plan.segments),
                    adir, key,
                )
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {str(e)[:200]}"
                print(f"[answer FAIL] {variant}@{budget} {q.question_id[:12]} "
                      f"{err[:60]}", flush=True)
                if _is_refusal(err):
                    # contentFilter 确定性拒答 (Addendum B): 落盘空记录按 0 计分,
                    # 带 api_error 存证, 保持每格 n=120; 瞬态失败不落盘待重跑
                    rec = {
                        "policy": f"compression@{variant}", "budget": budget,
                        "question_id": q.question_id,
                        "question_type": q.question_type, "gold": q.answer,
                        "pred": "", "em": 0.0, "relaxed_em": 0.0, "f1": 0.0,
                        "prompt_tokens": 0, "completion_tokens": 0,
                        "e2e_ms": 0.0, "access_ms": 0.0,
                        "memory_footprint_tokens": plan.footprint_tokens,
                        "n_turns": plan.n_turns, "n_summaries": plan.n_summaries,
                        "api_error": err,
                    }
                    async with lock:
                        with res_path.open("a", encoding="utf-8") as f:
                            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                return
            pred = ans.get("text", "").strip()
            rec = {
                "policy": f"compression@{variant}",
                "budget": budget,
                "question_id": q.question_id,
                "question_type": q.question_type,
                "gold": q.answer,
                "pred": pred,
                "em": em(pred, q.answer),
                "relaxed_em": relaxed_em(pred, q.answer),
                "f1": token_f1(pred, q.answer),
                "prompt_tokens": ans.get("prompt_tokens", 0),
                "completion_tokens": ans.get("completion_tokens", 0),
                "e2e_ms": ans.get("ms", 0),
                "access_ms": round((time.time() - t0) * 1000, 1),
                "memory_footprint_tokens": plan.footprint_tokens,
                "n_turns": plan.n_turns,
                "n_summaries": plan.n_summaries,
            }
            async with lock:
                with res_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            tag = "OK " if rec["relaxed_em"] else "   "
            print(f"{tag}{variant}@{budget} {q.question_id[:12]} rel={rec['relaxed_em']:.0f} "
                  f"pred={pred[:30]!r} gold={str(q.answer)[:20]!r}", flush=True)

    for budget in budgets:
        t0 = time.time()
        await asyncio.gather(*[one(budget, q) for q in questions])
        done = _load_done(variant, budget)
        print(f"[answers {variant}@{budget}] {len(done)}/{len(questions)} done in "
              f"{time.time() - t0:.0f}s", flush=True)


def gen_summaries_sync(variant: str, limit: int | None) -> dict[str, str]:
    return asyncio.run(gen_summaries(variant, limit))


def run_answers(variant: str, budgets: list[int], limit: int | None,
                concurrency: int) -> None:
    summaries = gen_summaries_sync(variant, limit)
    asyncio.run(_run_answers(variant, budgets, limit, concurrency, summaries))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["kv", "edu"], required=True)
    ap.add_argument("--phase", choices=["summaries", "answers", "all"], default="all")
    ap.add_argument("--budgets", default=",".join(map(str, BUDGETS)))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=8)
    a = ap.parse_args()
    budgets = [int(x) for x in a.budgets.split(",") if x]
    if a.phase in ("summaries", "all"):
        gen_summaries_sync(a.variant, a.limit)
    if a.phase in ("answers", "all"):
        run_answers(a.variant, budgets, a.limit, a.concurrency)


if __name__ == "__main__":
    main()

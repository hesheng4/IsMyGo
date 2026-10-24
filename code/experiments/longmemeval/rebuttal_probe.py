# -*- coding: utf-8 -*-
"""评审回应探针: Q5 顺序对照 + Q7 读侧模板敏感性 (共用基线臂).

背景:
  Q5: reranker 把离线 Recall@5 抬到 0.95 但在线 EM 不动 —— 审稿人问是否有
      ordering / lost-in-the-middle 证据, 乱序/重排对照能否解锁增益。
  Q7: 读侧指令模板固定 (附录 A), 绝对水平是否模板敏感 (Chain-of-Note / JSON /
      放宽逐字约束, LongMemEval 作者建议的读侧变体)。

设计 (全部 retrieval@4096, 同 turn 选择, 120 题):
  臂 (policy 变体后缀, 记录 reader=glm-4.7-flash):
    @chrono : 基线 —— 时间序注入 + 原模板 T1 (与主网格装配完全一致,
              因读者不可用 (mimo 网关已下线), 基线臂同读者重跑, 臂内配对)
    @shuf   : Q5 —— 同 turn 集, 按题确定性随机乱序注入 (seed=qid 哈希)
    @rel    : Q5 —— 同 turn 集, 按 BM25 相关性序注入 (不重排回时间序)
    @nat    : Q7 —— 时间序 + 模板 T2 (放宽逐字约束, 自然短语作答)
    @con    : Q7 —— 时间序 + 模板 T3 (Chain-of-Note 两步: 先列证据要点再作答)

判定:
  Q5: @shuf/@rel vs @chrono 配对 (McNemar + bootstrap); 若乱序显著掉分 ->
      顺序重要, 读侧布局干预有空间; 若不动 -> 顺序不是主要瓶颈。
  Q7: @nat/@con vs @chrono 配对; 观察绝对水平与排序稳定性。

记录: output/longmemeval/results_rebuttal_probe.jsonl (独立文件, 不污染
      冻结的论文 results.jsonl); 断点续跑按 (arm, qid) 去重。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import load_questions, ntokens  # noqa: E402
from llm import MODEL_MAIN, _chat, _needs_disable_thinking  # noqa: E402
from policies import _bm25_rank, _fill_from_ranked, _turn_segments  # noqa: E402
from score import em, relaxed_em, token_f1, paired_bootstrap, mcnemar_exact  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
BUDGET = 4096
READER = "glm-4.7-flash"          # mimo 网关已下线, 探针读者固定 glm-4.7-flash
CONCURRENCY = 4                    # glm-4.7-flash 免费档限流, 保守并发

# ---------------- 读侧模板 (T1 与 llm.ANSWER_SYS 逐字一致) ----------------
T1 = (
    "You answer questions about a user based on stored memory from past conversations. "
    "Reply with ONLY the exact factual answer phrase copied as verbatim as possible from "
    "the memory: a few words, no explanation, no full sentence, no units beyond what the "
    "memory states. If the answer is a number, reply with just the number. Never pad the "
    "answer with extra words. If the memory does not contain the answer, reply with your "
    "best guess."
)
T2 = (
    "You answer questions about a user based on stored memory from past conversations. "
    "Reply with a short, natural answer phrase: a few words, no explanation, no full "
    "sentence. You do not need to copy the memory wording exactly; give the fact as you "
    "understand it. If the answer is a number, reply with just the number. If the memory "
    "does not contain the answer, reply with your best guess."
)
T3 = (
    "You answer questions about a user based on stored memory from past conversations. "
    "First, write 1-3 short bullet points quoting the exact relevant facts from the "
    "memory that answer the question. Then, on a final new line, output exactly "
    "'Answer: ' followed by ONLY the exact factual answer phrase: a few words, copied "
    "as verbatim as possible from the memory. If the answer is a number, give just the "
    "number. If the memory does not contain the answer, make your best guess."
)

ARMS = {
    "@chrono": {"order": "chrono", "sys": T1, "max_tokens": 64},
    "@shuf":   {"order": "shuf",   "sys": T1, "max_tokens": 64},
    "@rel":    {"order": "rel",    "sys": T1, "max_tokens": 64},
    "@nat":    {"order": "chrono", "sys": T2, "max_tokens": 64},
    "@con":    {"order": "chrono", "sys": T3, "max_tokens": 256},
}


def _parse_con(text: str) -> str:
    """T3: 取最后一个 'Answer:' 之后的内容; 无则取最后一个非空行。"""
    m = re.findall(r"(?im)^\s*answer\s*:\s*(.+)$", text)
    if m:
        return m[-1].strip()
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    return lines[-1] if lines else ""


def build_arm_context(q, order: str) -> list[str]:
    ranked = _bm25_rank(q.turns, q.question)
    sel = _fill_from_ranked(ranked, BUDGET, set())
    if order == "chrono":
        sel.sort(key=lambda t: (t.session_idx, t.turn_idx))
    elif order == "shuf":
        seed = int(hashlib.sha1(q.question_id.encode("utf-8")).hexdigest()[:12], 16)
        rng = random.Random(seed)
        rng.shuffle(sel)
    elif order == "rel":
        pass  # 保持 BM25 序
    else:
        raise ValueError(order)
    return _turn_segments(sel)


async def main() -> None:
    smoke = "--smoke" in sys.argv
    questions = load_questions(n=5 if smoke else None)
    n = len(questions)
    print(f"[probe] reader={READER} questions={n} arms={list(ARMS)}")

    rp = OUT / "results_rebuttal_probe.jsonl"
    existing: dict[str, dict] = {}
    if rp.exists():
        for line in rp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                existing[f"{r['policy']}|{r['question_id']}"] = r
    print(f"[probe] 已有记录 {len(existing)} 条 (断点续跑)")

    sem = asyncio.Semaphore(CONCURRENCY)
    lock = asyncio.Lock()
    t0 = time.time()
    n_calls = 0

    async def one(arm: str, q) -> None:
        nonlocal n_calls
        cfg = ARMS[arm]
        tag = f"retrieval{arm}|{q.question_id}"
        if tag in existing:
            return
        segs = build_arm_context(q, cfg["order"])
        memory = "\n\n".join(segs)
        date_line = f"(current date: {q.question_date})\n" if q.question_date else ""
        user = (
            f"Stored memory from past conversations:\n\n{memory}\n\n"
            f"{date_line}Based only on the memory above, answer:\n{q.question}"
        )
        async with sem:
            try:
                out = await _chat(cfg["sys"], user, max_tokens=cfg["max_tokens"],
                                  temperature=0.0, model=READER,
                                  disable_thinking=_needs_disable_thinking(READER),
                                  purpose="rebuttal探针")
            except Exception as e:  # noqa: BLE001
                print(f"[probe FAIL] {arm} {q.question_id[:10]} {str(e)[:80]}", flush=True)
                return
        n_calls += 1
        pred = out["text"]
        if arm == "@con":
            pred = _parse_con(pred)
        rec = {
            "policy": f"retrieval{arm}", "budget": BUDGET,
            "question_id": q.question_id, "question_type": q.question_type,
            "gold": q.answer, "pred": pred,
            "raw_pred": out["text"],
            "em": em(pred, q.answer), "relaxed_em": relaxed_em(pred, q.answer),
            "f1": token_f1(pred, q.answer),
            "memory_footprint_tokens": ntokens(memory),
            "e2e_ms": round(out["ms"], 2),
            "prompt_tokens": out["prompt_tokens"], "completion_tokens": out["completion_tokens"],
            "model": READER,
        }
        async with lock:
            with rp.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[probe] {arm} {q.question_id[:10]} rel={rec['relaxed_em']:.0f} "
              f"({time.time()-t0:.0f}s, {n_calls} calls)", flush=True)

    for arm in ARMS:
        await asyncio.gather(*(one(arm, q) for q in questions))
        print(f"[probe] arm {arm} done ({time.time()-t0:.0f}s)", flush=True)

    # ---------------- 汇总与配对检验 ----------------
    by_arm: dict[str, dict[str, dict]] = {a: {} for a in ARMS}
    if rp.exists():
        for line in rp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r["model"] == READER:
                by_arm.setdefault(r["policy"], {})[r["question_id"]] = r

    print("\n=== 各臂汇总 (relaxed EM / EM / F1) ===")
    print(f"{'arm':12s} {'n':>4s} {'EM_rel':>7s} {'EM':>7s} {'F1':>7s} {'e2e_s':>6s}")
    for arm in ARMS:
        recs = list(by_arm[f"retrieval{arm}"].values())
        recs = [r for r in recs if r["question_id"] in {q.question_id for q in questions}]
        if not recs:
            continue
        print(f"{arm:12s} {len(recs):4d} "
              f"{sum(r['relaxed_em'] for r in recs)/len(recs):7.4f} "
              f"{sum(r['em'] for r in recs)/len(recs):7.4f} "
              f"{sum(r['f1'] for r in recs)/len(recs):7.4f} "
              f"{sum(r['e2e_ms'] for r in recs)/len(recs)/1000:6.2f}")

    canon = {q.question_id for q in questions}

    def paired(a: str, b: str) -> None:
        ra, rb = by_arm[f"retrieval{a}"], by_arm[f"retrieval{b}"]
        ids = sorted((set(ra) & set(rb)) & canon)  # 只用规范 120 题, 排除冒烟残留
        if len(ids) < 5:
            print(f"[pair] {a} vs {b}: 交集不足 (n={len(ids)})")
            return
        xa = [ra[i]["relaxed_em"] for i in ids]
        xb = [rb[i]["relaxed_em"] for i in ids]
        (ma, mb, _), (lo, hi) = paired_bootstrap(xa, xb)
        mc = mcnemar_exact(xa, xb)
        print(f"[pair] {a} vs {b}: n={len(ids)}  {ma:.4f} vs {mb:.4f}  "
              f"delta={ma-mb:+.4f} [{lo:+.4f},{hi:+.4f}]  McNemar p={mc['p_value']:.4f} "
              f"(n10={mc['n10']}, n01={mc['n01']})")

    print("\n=== 配对检验 (relaxed EM) ===")
    paired("@chrono", "@shuf")
    paired("@chrono", "@rel")
    paired("@chrono", "@nat")
    paired("@chrono", "@con")
    print(f"\n[probe] done: {n_calls} new calls, wall {time.time()-t0:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())

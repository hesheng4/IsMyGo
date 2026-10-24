# -*- coding: utf-8 -*-
"""评测编排入口。

用法:
  python run.py --smoke            # 10 题冒烟 (全策略 x 全预算)
  python run.py --full             # 120 题全量
  python run.py --full --policies compression,retrieval_recency   # 断点续跑

输出: ../../output/longmemeval/results.jsonl (逐题记录 JSONL, 可追溯; 唯一事实基准)
      ../../output/longmemeval/tables/  (analyze.py 聚合出的统计表)
      ../../output/longmemeval/cache/{summaries,answers}/  (LLM 调用缓存)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "longmemeval"
CACHE = OUT / "cache"

# --------------------------------------------------------------------------- #
# --log-run：必须在导入 llm 之前设置 RUN_LOG_DIR —— llm.py 在模块导入期读取该变量
# 构造 RunLogger，因此必须早于 `from llm import ...` 执行。
# 日志落到包根 logs/{run.json,calls.jsonl}（见 logs/README.md）。
# --------------------------------------------------------------------------- #
_argv = sys.argv[1:]
if "--log-run" in _argv:
    _logs = ROOT.parent / "logs"                # ROOT = IsMyGo/code -> IsMyGo/logs
    _logs.mkdir(parents=True, exist_ok=True)
    os.environ["RUN_LOG_DIR"] = str(_logs)
    os.environ.setdefault("RUN_ID", "agent-sci-2026-comp-001")
    os.environ.setdefault("RUN_TOPIC",
                          "Agent记忆引擎：长程流式任务中的记忆策略权衡")
    os.environ.setdefault("RUN_COMMAND",
                          "python code/experiments/longmemeval/run.py "
                          + " ".join(_argv))
    os.environ.setdefault("RUN_OUTPUT_PAPER", "paper/paper.pdf")

from common import BUDGETS, format_context, load_questions, unique_sessions
from common import fresh_run, record_matches_model
from llm import MODEL_ALT, MODEL_MAIN, answer_with_memory, summarize_fetched, summarize_session
from llm import RUN_LOGGER
from policies import (ABLATION_POLICIES, ABLATION_POLICIES_V2, EXTENDED_POLICIES,
                      POLICIES, build_memory, fetch_evidence)
from score import em, relaxed_em, token_f1
from embed_util import embed_texts, load_cached_embeddings


async def precompute_summaries(questions, max_words: int = 60) -> dict[str, str]:
    sessions = unique_sessions(questions)
    print(f"[summaries w{max_words}] 去重后待摘要会话数: {len(sessions)}")

    async def one(sid: str, turns):
        try:
            s = await summarize_session(sid, turns, CACHE / "summaries",
                                        max_words=max_words)
            return sid, s
        except Exception as e:  # noqa: BLE001
            print(f"[summaries] FAIL {sid}: {e}")
            return sid, ""

    results = await asyncio.gather(*(one(sid, t) for sid, t in sessions.items()))
    ok = sum(1 for _, s in results if s)
    print(f"[summaries w{max_words}] 完成 {ok}/{len(results)}")
    return dict(results)


CONCURRENCY = int(os.environ.get("PAPER_LAB_CONCURRENCY", "24"))


async def precompute_fetch_summaries(questions, budgets=None) -> dict[str, str]:
    """compression_fetch 阶段2 预计算: 每 (题, 预算) 一条问题聚焦摘要, 落盘缓存。
    key = "{budget}|{question_id}"。失败项返回空串, 由 build_memory 以截断原始证据兜底。"""
    budgets = budgets or BUDGETS
    out: dict[str, str] = {}

    async def one(q, b):
        max_words = int(b * 0.5)
        evidence = fetch_evidence(q, b)
        try:
            # 单条摘要总超时兜底（含内部重试），超时以截断原始证据降级，不阻塞整体流程
            d = await asyncio.wait_for(
                summarize_fetched(q.question_id, q.question, evidence,
                                  CACHE / "fetch", max_words),
                timeout=300.0,
            )
            return f"{b}|{q.question_id}", d
        except Exception as e:  # noqa: BLE001
            print(f"[fetch] FAIL {q.question_id}|{b}: {e}")
            return f"{b}|{q.question_id}", ""

    pairs = [(q, b) for q in questions for b in budgets]
    results = await asyncio.gather(*(one(q, b) for q, b in pairs))
    out.update(dict(results))
    ok = sum(1 for v in out.values() if v)
    print(f"[fetch] 问题聚焦摘要完成 {ok}/{len(out)}"
          f"（失败 {len(out) - ok} 项由截断原始证据兜底）")
    return out


async def run(policy: str, budget: int | None, questions, summaries: list | dict,
              records: list[dict], *, qe=None, turn_embs=None, variant: str = "",
              model_tag: str = MODEL_MAIN, fetch: dict | None = None) -> None:
    sem_records = asyncio.Semaphore(CONCURRENCY)

    async def one(q):
        qe_this = qe.get(q.question_id) if isinstance(qe, dict) else qe
        plan = build_memory(policy, q, budget, summaries, qe=qe_this,
                            turn_embs=turn_embs, summary_variant=variant,
                            session_dates=getattr(q, "session_dates", None),
                            fetch=fetch)
        key = f"{policy}{variant}|{budget}|{q.question_id}"
        try:
            ans = await answer_with_memory(
                q.question, q.question_date,
                format_context(plan.segments),
                CACHE / "answers", key, model_tag=model_tag,
            )
        except Exception as e:  # noqa: BLE001
            # 调用失败（限流/超时/网关错误）不落"空预测伪 0 行"——那会被续跑判为
            # 已完成、被聚合判为 EM=0, 产生伪退化结论。不记录即保持缺失, 续跑自动重答。
            print(f"[answer] FAIL {key}: {e}")
            return
        if model_tag != MODEL_MAIN and not ans["text"].strip():
            # 跨读者复跑: 限流失败不记 0 分污染均值, 跳过该题 (表格按实际 n 报告)
            return
        async with sem_records:
            records.append({
                "policy": f"{policy}{variant}", "budget": budget, "question_id": q.question_id,
                "question_type": q.question_type, "gold": q.answer,
                "pred": ans["text"], "model": model_tag,
                "em": em(ans["text"], q.answer),
                "relaxed_em": relaxed_em(ans["text"], q.answer),
                "f1": token_f1(ans["text"], q.answer),
                "memory_footprint_tokens": plan.footprint_tokens,
                "n_turns": plan.n_turns, "n_summaries": plan.n_summaries,
                "access_ms": round(plan.access_ms, 4),
                "e2e_ms": round(ans.get("ms", 0.0), 2),
                "prompt_tokens": ans.get("prompt_tokens", 0),
                "completion_tokens": ans.get("completion_tokens", 0),
            })

    await asyncio.gather(*(one(q) for q in questions))



async def main() -> None:
    _t_run0 = time.perf_counter()
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--ablate", action="store_true",
                    help="敏感性消融: 摘要长度 20/120 + 层级分配变体 + dense/hybrid 检索")
    ap.add_argument("--robustness", action="store_true",
                    help="跨读者稳健性: 同网格换 GLM-4.7-Flash 答题 (复用冻结摘要)")
    ap.add_argument("--v2", action="store_true",
                    help="评审回应新增策略: 读取侧相关性感知摘要 + 事件锚定检索腿")
    ap.add_argument("--extended", action="store_true",
                    help="插件式强基线 (评审弱点回应): compression_select / hierarchical_ev / "
                         "retrieval_sentence(句子级) / compression_fetch(先取后总结)")
    ap.add_argument("--key-only", action="store_true",
                    help="配合 --robustness: 只跑信息量最高的关键格 (跳过其余网格)")
    ap.add_argument("--fresh", action="store_true",
                    help="全新运行：忽略一切 LLM 缓存与断点续跑记录，以当前模型完整重跑"
                         "（不读不写缓存，等价 PAPER_LAB_FRESH=1）")
    ap.add_argument("--full500", action="store_true",
                    help="全量 500 题复跑 (审稿回应 W1: 不分层, 全 6 题型, "
                         "记录与 120 题主网格同池追加, 断点续跑按 (policy,budget,qid) 去重)")
    ap.add_argument("--policies", type=str, default="")
    ap.add_argument("--n", type=int, default=None)
    ap.add_argument("--log-run", action="store_true",
                    help="把本次运行写入 logs/{run.json,calls.jsonl}"
                         "（等价于设置 RUN_LOG_DIR 环境变量）")
    args = ap.parse_args()

    if args.fresh:
        os.environ["PAPER_LAB_FRESH"] = "1"  # 全新运行：缓存与续跑全部旁路
    print(f"[model] 答题器 = {MODEL_MAIN}（随配置变化）"
          f"{' | FRESH 全新运行（忽略缓存与续跑）' if fresh_run() else ''}")

    if args.ablate:
        await run_ablation()
        return
    if args.robustness:
        await run_robustness(key_only=args.key_only)
        return
    if args.v2:
        await run_v2()
        return
    if args.extended:
        await run_extended()
        return

    policies = [p.strip() for p in args.policies.split(",") if p.strip()] or list(POLICIES)
    if args.full500:
        questions = load_questions(full=True)
        n = len(questions)
    else:
        n = 10 if args.smoke else (args.n or (None if args.full else 10))
        questions = load_questions(n=n) if (args.smoke or n) else load_questions()
    print(f"[data] 题数={len(questions)}  策略={policies}"
          f"{'  [FULL-500]' if args.full500 else ''}")

    OUT.mkdir(parents=True, exist_ok=True)
    results_path = OUT / "results.jsonl"
    existing: dict[str, dict] = {}
    if results_path.exists() and not fresh_run():  # 断点续跑: 同答题器模型的已有记录直接复用
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if record_matches_model(r, MODEL_MAIN):
                    existing[f"{r['policy']}|{r['budget']}|{r['question_id']}"] = r

    summaries = await precompute_summaries(questions) if any(
        p == "compression" or p.startswith("hierarchical") for p in policies
    ) else {}
    if summaries:
        _missing = [sid for sid, v in summaries.items() if not v]
        if _missing and os.environ.get("PAPER_LAB_SUMMARY_STRICT", "1") != "0":
            print(f"[FATAL] 摘要缺失 {len(_missing)} 条 — 拒绝在空摘要腿上产出记录, "
                  f"退出。请先补齐摘要 (PAPER_LAB_SUMMARY_STRICT=0 可显式绕过)")
            sys.exit(3)

    t0 = time.time()
    records: list[dict] = []
    todo = [
        (p, None if p == "full_context" else b)
        for p in policies
        for b in (BUDGETS if p != "full_context" else [None])
    ]
    for policy, budget in todo:
        missing = [q for q in questions
                   if f"{policy}|{budget}|{q.question_id}" not in existing]
        have = [existing[f"{policy}|{budget}|{q.question_id}"]
                for q in questions
                if f"{policy}|{budget}|{q.question_id}" in existing]
        if not missing:
            records.extend(have)
            print(f"[skip] {policy}|{budget} 已完成")
            continue
        print(f"[run ] {policy}|{budget} 待跑 {len(missing)} 题")
        new: list[dict] = []
        await run(policy, budget, missing, summaries, new)
        records.extend(have + new)
        with results_path.open("a", encoding="utf-8") as f:
            for r in new:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 汇总表
    agg: dict[str, dict] = {}
    for r in records:
        k = f"{r['policy']}|{r['budget']}"
        a = agg.setdefault(k, {"em": [], "f1": [], "e2e": [], "tok": []})
        a["em"].append(r["em"]); a["f1"].append(r["f1"])
        a["e2e"].append(r["e2e_ms"]); a["tok"].append(r["memory_footprint_tokens"])
    print(f"\n=== 汇总 (耗时 {time.time()-t0:.0f}s) ===")
    print(f"{'policy|budget':32s} {'EM':>7s} {'F1':>7s} {'e2e_ms':>9s} {'mem_tok':>8s}")
    for k in sorted(agg):
        a = agg[k]
        print(f"{k:32s} {sum(a['em'])/len(a['em']):7.4f} {sum(a['f1'])/len(a['f1']):7.4f} "
              f"{sum(a['e2e'])/len(a['e2e']):9.1f} {sum(a['tok'])/len(a['tok']):8.0f}")

    # 本次运行总账：token 汇总由 calls.jsonl 逐行重新求和，强一致（见 run_logger.finish）
    if RUN_LOGGER is not None:
        payload = RUN_LOGGER.finish(
            output_dir="code/output/longmemeval/",
            wall_seconds=time.perf_counter() - _t_run0,
        )
        print("[log] run.json -> logs/run.json  llm_calls=%d token_total=%d"
              % (payload["llm_calls"], payload["token_total"]))


async def _run_cells(cells, questions, summaries_map, *, qe=None, turn_embs=None,
                     model_tag=MODEL_MAIN, fetch: dict | None = None) -> None:
    """按 (policy, budget, variant) 单元格写入 results.jsonl, 断点续跑（按答题器模型）。"""
    results_path = OUT / "results.jsonl"
    existing: dict[str, dict] = {}
    if results_path.exists() and not fresh_run():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if record_matches_model(r, model_tag):
                    existing[f"{r['policy']}|{r['budget']}|{r['question_id']}"] = r
    for policy, budget, variant in cells:
        pol_key = f"{policy}{variant}"
        missing = [q for q in questions
                   if f"{pol_key}|{budget}|{q.question_id}" not in existing]
        if not missing:
            print(f"[skip] {pol_key}|{budget}")
            continue
        print(f"[run ] {pol_key}|{budget} 待跑 {len(missing)} 题")
        new: list[dict] = []
        await run(policy, budget, missing, summaries_map.get(variant, {}),
                  new, qe=qe, turn_embs=turn_embs, variant=variant,
                  model_tag=model_tag, fetch=fetch)
        with results_path.open("a", encoding="utf-8") as f:
            for r in new:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


async def run_ablation() -> None:
    """评审回应消融: ①摘要长度 20/120 ②分配变体 ③dense/hybrid 检索。"""
    OUT.mkdir(parents=True, exist_ok=True)
    questions = load_questions()
    print(f"[ablate] 题数={len(questions)}")

    # ① 摘要长度变体 (底座 GLM-4-Flash 不变)
    sums60 = await precompute_summaries(questions, max_words=60)
    sums20 = await precompute_summaries(questions, max_words=20)
    sums120 = await precompute_summaries(questions, max_words=120)
    cells = [("compression", b, v) for b in (1024, 2048, 4096)
             for v in ("@w20", "@w120")]
    await _run_cells(cells, questions,
                     {"@w20": sums20, "@w120": sums120, "": sums60})

    # ③ dense / hybrid 检索 (embedding-3)
    all_turn_texts = list({t.text for q in questions for t in q.turns})
    q_texts = [q.question for q in questions]
    turn_embs = await embed_texts(all_turn_texts, CACHE / "embeddings")
    qe_raw = await embed_texts(q_texts, CACHE / "embeddings")
    # 问题向量按题注入：_run_cells 每个格跑全部题，qe 传 map
    cells = [(p, b, "") for p in ("dense_retrieval", "hybrid_retrieval")
             for b in BUDGETS]
    # 逐题向量: build_memory 需要单题向量 -> 在 run() 内按 qid 取
    global _QE_MAP
    _QE_MAP = {q.question_id: qe_raw.get(
        __import__("hashlib").sha1(q.question.encode("utf-8")).hexdigest()[:16], None)
        for q in questions}
    await _run_cells(cells, questions, {}, turn_embs=turn_embs,
                     qe=_QE_MAP)

    # ② 层级分配变体
    cells = [(p, b, "") for p in ("hierarchical_sumheavy", "hierarchical_evidence")
             for b in (2048, 4096)]
    await _run_cells(cells, questions, {"": sums60})


_QE_MAP: dict = {}


async def run_v2() -> None:
    """评审回应新增的两条设计: 读取侧相关性感知摘要 + 事件锚定检索腿。

    compression_select : 摘要按与问题的相关性排序后装填 (先取再总结)
    hierarchical_ev    : 三层分割不变, 检索腿换成事件锚定/时间信号排序
    摘要复用冻结的 w60 缓存, 只新增答题调用。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    questions = load_questions()
    sums = await precompute_summaries(questions, max_words=60)
    print(f"[v2] 题数={len(questions)} 策略={ABLATION_POLICIES_V2}")
    cells = [(p, b, "") for p in ABLATION_POLICIES_V2 for b in BUDGETS]
    await _run_cells(cells, questions, {"": sums})


async def run_extended() -> None:
    """插件式强基线 (评审弱点回应): 相关性摘要 / 事件锚定 / 句子级检索 / 先取后总结。

    - compression_select / hierarchical_ev 已有数据的格子自动跳过 (断点续跑);
    - retrieval_sentence 纯本地装配, 仅新增答题调用;
    - compression_fetch 需 (题, 预算) 问题聚焦摘要预计算, 之后仅答题调用。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    questions = load_questions()
    print(f"[extended] 题数={len(questions)} "
          f"策略={ABLATION_POLICIES_V2 + EXTENDED_POLICIES}")
    sums = await precompute_summaries(questions, max_words=60)
    fetch = await precompute_fetch_summaries(questions)
    cells = [(p, b, "") for p in (ABLATION_POLICIES_V2 + EXTENDED_POLICIES)
             for b in BUDGETS]
    await _run_cells(cells, questions, {"": sums}, fetch=fetch)
    if RUN_LOGGER is not None:
        payload = RUN_LOGGER.finish(
            output_dir="code/output/longmemeval/",
            wall_seconds=0.0,
        )
        print("[log] run.json llm_calls=%d token_total=%d"
              % (payload["llm_calls"], payload["token_total"]))


def _robust_suffix(model_tag: str) -> str:
    """跨读者记录后缀按模型版本自动生成 (GLM-4.7-Flash -> @m47, glm-5.3-flash -> @m53),
    不同读者模型的记录落不同命名空间, 避免混池。"""
    import re
    m = re.search(r"(\d+)\.(\d+)", model_tag or "")
    return f"@m{m.group(1)}{m.group(2)}" if m else "@mx"


async def run_robustness(key_only: bool = False) -> None:
    """跨读者稳健性: 完整网格换强读者答题 (PAPER_LAB_ALT_MODEL, 默认 GLM-4.7-Flash),
    摘要/压缩产物冻结复用。"""
    OUT.mkdir(parents=True, exist_ok=True)
    questions = load_questions(n=60)  # 跨读者子集: 分层 60 题, 论文标注 n=60
    sums = await precompute_summaries(questions, max_words=60)
    fetch = await precompute_fetch_summaries(questions)
    # 强读者免费档速率限制严格: 串行 + 全局信号量收紧
    global CONCURRENCY
    CONCURRENCY = 2
    import llm as _llm
    _llm.SEM = asyncio.Semaphore(2)
    v = _robust_suffix(MODEL_ALT)
    print(f"[robustness] 题数={len(questions)} 模型={MODEL_ALT} 后缀={v} "
          f"(thinking disabled, 并发2, key_only={key_only})")
    # 跨读者关键断言 = oracle 崩塌 + 检索/层级顺序保持; 优先跑信息量最高的格子
    key_cells = [("full_context", None, v)]
    key_cells += [(p, 4096, v) for p in
                  ("retrieval", "retrieval_recency", "compression", "hierarchical")]
    key_cells += [(p, 4096, v) for p in
                  ("compression_select", "hierarchical_ev",
                   "retrieval_sentence", "compression_fetch")]
    rest = [] if key_only else [
        (p, b, v) for p in POLICIES[1:] for b in (512, 1024, 2048)
        if (p, b, v) not in key_cells]
    await _run_cells(key_cells + rest, questions,
                     {v: sums}, model_tag=MODEL_ALT, fetch=fetch)
    if RUN_LOGGER is not None:
        payload = RUN_LOGGER.finish(
            output_dir="code/output/longmemeval/",
            wall_seconds=0.0,
        )
        print("[log] run.json llm_calls=%d token_total=%d"
              % (payload["llm_calls"], payload["token_total"]))




if __name__ == "__main__":
    asyncio.run(main())

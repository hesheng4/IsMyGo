# -*- coding: utf-8 -*-
"""E4 judge 扩容 (ANALYSIS_PROTOCOL.md §5.2, 评审问题 4).

判定范围:
  1. 全部 read-fail 错答题 (7 策略 x 4 预算, 诊断表现存 1,746 条);
  2. 每策略 30 题正确对照 (防裁判偏置漂移: EM 判对但裁判判错的比率);
  3. P3 全错答题（E7 意意译友好模板，本脚本不含）。

裁判: GLM-4.7-Flash (thinking off)，使用与 judge_probe 一致的 prompt
(judge_probe.JUDGE_SYS / judge_prompt)，与答题器 GLM-4-Flash 不同模型，降低循环论证。

口径 (Addendum B): contentFilter 拒答记录 (空 pred) 不入 read-fail 集合
(诊断表生成时已跳过), flip 率只在非拒答题上估计。

缓存键 = (question, gold, pred) 内容哈希: 同一题同一错误答案跨预算/策略
只判一次, 判决映射回所有对应格子。

输出: tables/judge_full.json —— 逐策略x预算 flip 计数 + 正确对照误判率
+ 汇总 (意译惩罚占比估计, 供论文 §Analysis 与 Q4 回应)。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

from common import load_questions
from judge_probe import judge_one

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "output" / "longmemeval"
TAB = OUT / "tables"

POLICIES = ("sliding_window", "retrieval", "retrieval_recency", "compression",
            "hierarchical", "dense_retrieval", "hybrid_retrieval")
N_CONTROLS = 30
SEED = 42


def content_key(question: str, gold, pred: str) -> str:
    raw = f"{question}\x00{gold}\x00{pred}"
    # 注意: Windows 文件名禁止冒号, 前缀必须用下划线 (judge_one 直接拿 key 当文件名)
    return "jfull_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


async def main() -> None:
    questions = {q.question_id: q for q in load_questions()}
    diag = json.loads((TAB / "retrieval_diagnosis.json").read_text(encoding="utf-8"))
    recs = {}
    for line in (OUT / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            recs[(r["policy"], r["budget"], r["question_id"])] = r

    # ---------- 集合构造 ----------
    # read-fail: 金证据覆盖 + relaxed EM 错 (诊断表已排除空 pred/缺失记录)
    read_fails = [r for r in diag["per_question"]
                  if r["gold_hit"] and not r["correct"]
                  and r["policy"] in POLICIES]
    # 正确对照: 每策略从正确池确定性抽 30 格 (seed 42)
    rng = random.Random(SEED)
    controls = []
    for pol in POLICIES:
        pool = sorted([r for r in diag["per_question"]
                       if r["correct"] and r["policy"] == pol],
                      key=lambda r: (r["qid"], r["budget"]))
        controls.extend(rng.sample(pool, min(N_CONTROLS, len(pool))))

    # ---------- 去重判题 (内容哈希) ----------
    jobs: dict[str, tuple] = {}  # cache_key -> (question, gold, pred)
    cell_map: dict[str, list[dict]] = defaultdict(list)  # cache_key -> cells
    for r in read_fails:
        rec = recs.get((r["policy"], r["budget"], r["qid"]))
        if not rec or not rec["pred"].strip():
            continue  # 防御: 拒答不入判
        q = questions[r["qid"]]
        k = content_key(q.question, q.answer, rec["pred"])
        jobs[k] = (q.question, q.answer, rec["pred"])
        cell_map[k].append({"policy": r["policy"], "budget": r["budget"],
                            "qid": r["qid"], "kind": "read_fail"})
    for r in controls:
        rec = recs.get((r["policy"], r["budget"], r["qid"]))
        if not rec or not rec["pred"].strip():
            continue
        q = questions[r["qid"]]
        k = content_key(q.question, q.answer, rec["pred"])
        jobs[k] = (q.question, q.answer, rec["pred"])
        cell_map[k].append({"policy": r["policy"], "budget": r["budget"],
                            "qid": r["qid"], "kind": "control"})

    n_rf_entries = sum(1 for c in cell_map.values()
                       if any(x["kind"] == "read_fail" for x in c))
    print(f"[e4] read-fail {n_rf_entries} 格 / 正确对照 {len(controls)} 格; "
          f"去重后待判 {len(jobs)} 条", flush=True)

    sem = asyncio.Semaphore(4)  # 4.7-Flash 服务端拥堵常态: 并发 4 抢空窗, 深重试兜底

    async def guarded(k: str):
        async with sem:
            q, g, p = jobs[k]
            return k, await judge_one(q, g, p, k)

    results = await asyncio.gather(*(guarded(k) for k in jobs))
    verdicts = dict(results)

    # ---------- 聚合 ----------
    rf_cell = defaultdict(lambda: {"n": 0, "flip": 0})
    ctl_cell = defaultdict(lambda: {"n": 0, "incorrect": 0})
    rows = []
    for k, cells in cell_map.items():
        v = verdicts.get(k, "ERROR")
        for c in cells:
            if c["kind"] == "read_fail":
                a = rf_cell[(c["policy"], c["budget"])]
                a["n"] += 1
                if v == "CORRECT":
                    a["flip"] += 1
            else:
                a = ctl_cell[c["policy"]]
                a["n"] += 1
                if v == "INCORRECT":
                    a["incorrect"] += 1
            rows.append({**c, "verdict": v})

    # 汇总: 意译惩罚占比 (read-fail flip 率) + 对照误判率
    rf_tot = {"n": sum(a["n"] for a in rf_cell.values()),
              "flip": sum(a["flip"] for a in rf_cell.values())}
    ctl_tot = {"n": sum(a["n"] for a in ctl_cell.values()),
               "incorrect": sum(a["incorrect"] for a in ctl_cell.values())}
    errors = sum(1 for r in rows if r["verdict"] == "ERROR")

    out = {
        "experiment": "E4 judge full read-fail sweep",
        "protocol": "ANALYSIS_PROTOCOL.md §5.2 + Addendum B; judge=GLM-4.7-Flash "
                    "(thinking off), 同上轮 prompt; 拒答记录不入集",
        "read_fail_by_cell": {f"{p}@{b}": v for (p, b), v in sorted(rf_cell.items())},
        "controls_by_policy": {p: v for p, v in sorted(ctl_cell.items())},
        "read_fail_total": rf_tot,
        "controls_total": ctl_tot,
        "flip_rate_read_fail": rf_tot["flip"] / rf_tot["n"] if rf_tot["n"] else None,
        "incorrect_rate_controls": (ctl_tot["incorrect"] / ctl_tot["n"]
                                    if ctl_tot["n"] else None),
        "judge_errors": errors,
        "n_unique_judgments": len(jobs),
        "rows": rows,
    }
    (TAB / "judge_full.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n=== E4 judge 扩容 (去重 {len(jobs)} 判, ERROR {errors}) ===")
    print(f"read-fail flip (意译惩罚): {rf_tot['flip']}/{rf_tot['n']}"
          f" = {out['flip_rate_read_fail']:.1%}")
    print(f"正确对照误判 (裁判过严):   {ctl_tot['incorrect']}/{ctl_tot['n']}"
          f" = {out['incorrect_rate_controls']:.1%}")
    for (p, b), a in sorted(rf_cell.items()):
        if a["n"]:
            print(f"  {p}@{b}: {a['flip']}/{a['n']} ({a['flip']/a['n']:.1%})")
    print(f"written -> {TAB / 'judge_full.json'}")


if __name__ == "__main__":
    asyncio.run(main())

# -*- coding: utf-8 -*-
"""W3/Q3 补充实验: 片段级证据审计 (covered-but-wrong 三分类 + lost-in-the-middle 位置分析).

背景: 诊断表 (Table 5) 的 "read failure" 是 session 级上界 —— 金会话被覆盖
不代表答案片段真的在注入上下文里。审稿人 (W3/Q3) 要求片段级证据。

方法 (全部本地、确定性、零 LLM 调用):
  对 retrieval@4096 的 covered-but-wrong 题 (金会话命中但 relaxed_EM<0.5):
    1. 重建与归档运行完全一致的记忆 plan (BM25 确定性);
    2. 归一化子串检测: gold (score.normalize 同口径) 是否逐字出现在上下文中;
    3. 内容词覆盖率: gold 内容词 (去停用词) 出现在上下文中的比例;
    4. 位置签名: 答案 span 首次出现的字符位置 / 上下文总长 -> 分十桶,
       检验 lost-in-the-middle (中段命中率是否偏低 / 首尾是否更准).

三分类:
    span-present : 归一化 gold 完整出现 (证据在, 读取失败)
    partial      : 内容词覆盖率 >= 0.5 (证据大致在, 但被改写/截断)
    absent       : 其余 (session 覆盖是假阳性: 金会话的其他 turn 被检索,
                   答案所在 turn/snippet 不在 —— 归因应从 read 移向 retrieval/truncation)

输出:
    output/longmemeval/tables/snippet_audit.json   (逐题明细)
    stdout 汇总 (含与 Table 5 的对账: 覆盖率、三分类占比、位置分布)
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import load_questions  # noqa: E402
from policies import _bm25_rank, _fill_from_ranked  # noqa: E402
from score import normalize  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
BUDGET = 4096
POLICY = "retrieval"

# 英文停用词 (内容词过滤; LongMemEval 为英文语料)
_STOP = set("""a an the and or but if then else of to in on at by for with about as is are was
were be been being do does did doing have has had having i you he she it we they me him her them
my your his its our their this that these those there here what which who whom when where why how
not no nor so too very can will just would should could may might must shall""".split())


def content_words(s: str) -> list[str]:
    return [w for w in normalize(s).split() if w not in _STOP]


def find_span_positions(norm_gold: str, norm_ctx: str, ctx_char_len: int, raw_ctx: str):
    """gold 在归一化上下文中的出现位置映射回原上下文的相对位置.

    归一化会改变字符偏移, 用词序列对齐: 在归一化文本中找 gold 的所有出现,
    以出现处首词在归一化词流中的索引 / 总词数作为相对位置 (0~1)。
    """
    g_words = norm_gold.split()
    c_words = norm_ctx.split()
    n = len(c_words)
    if not g_words or n == 0:
        return []
    poses = []
    gw = len(g_words)
    for i in range(n - gw + 1):
        if c_words[i:i + gw] == g_words:
            poses.append(i / n)
    return poses


def main() -> None:
    res_path = HERE.parents[2] / "output" / "results.jsonl"
    res: dict[str, dict] = {}
    for line in res_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if (r["policy"] == POLICY and r.get("budget") == BUDGET
                and str(r.get("model", "mimo-v2.6-flash")) == "mimo-v2.6-flash"):
            res[r["question_id"]] = r
    assert len(res) == 120, f"expected 120 retrieval@4096 records, got {len(res)}"

    questions = load_questions()
    details = []
    n_covered = n_covered_wrong = 0
    for q in questions:
        r = res.get(q.question_id)
        if r is None:
            continue
        ranked = _bm25_rank(q.turns, q.question)
        sel = _fill_from_ranked(ranked, BUDGET, set())
        sel.sort(key=lambda t: (t.session_idx, t.turn_idx))
        covered = {t.session_id for t in sel}
        gold_hit = bool(covered & set(q.answer_session_ids))
        if not gold_hit:
            continue
        n_covered += 1
        if r["relaxed_em"] >= 0.5:
            continue
        n_covered_wrong += 1

        raw_ctx = "\n".join(t.text for t in sel)
        norm_ctx = normalize(raw_ctx)
        norm_gold = normalize(q.answer)
        gold_cw = content_words(q.answer)
        cw_cov = (sum(1 for w in set(gold_cw) if w in norm_ctx) / len(set(gold_cw))
                  if gold_cw else 0.0)

        span_present = bool(norm_gold) and norm_gold in norm_ctx
        cls = "span-present" if span_present else ("partial" if cw_cov >= 0.5 else "absent")
        poses = find_span_positions(norm_gold, norm_ctx, len(raw_ctx), raw_ctx) if span_present else []
        details.append({
            "question_id": q.question_id, "question_type": q.question_type,
            "gold": q.answer, "pred": r["pred"],
            "gold_len_words": len(norm_gold.split()),
            "content_word_coverage": round(cw_cov, 3),
            "span_present": span_present, "class": cls,
            "span_rel_positions": [round(p, 3) for p in poses[:20]],
            "ctx_tokens": r["memory_footprint_tokens"],
        })

    # ---------- 汇总 ----------
    cls_counts = Counter(d["class"] for d in details)
    n = len(details)
    print(f"[audit] retrieval@{BUDGET}  covered={n_covered}/120  covered-but-wrong={n}")
    print(f"[audit] 三分类: " + "  ".join(
        f"{k}={cls_counts[k]} ({cls_counts[k]/n:.1%})" for k in ("span-present", "partial", "absent")))
    print(f"[audit] 证据在场率 (span-present + partial) = "
          f"{(cls_counts['span-present']+cls_counts['partial'])/n:.1%}")

    # 位置签名 (lost-in-the-middle): span-present 题的 span 相对位置分桶
    # 桶定义: [0,.1) [.1,.2) ... [.9,1]; 取每题首次出现位置
    first_pos = [d["span_rel_positions"][0] for d in details if d["span_rel_positions"]]
    bins = Counter(int(p * 10) for p in first_pos)
    print("[audit] span 首次出现位置分布 (十桶, 0=开头 0.9=结尾):")
    for b in range(10):
        print(f"  [{b/10:.1f},{b/10+0.1:.1f}): {'#'*bins.get(b,0)} {bins.get(b,0)}")
    # 首段/中段/尾段对比: 前1/3 中1/3 后1/3 的 span-present 题, 各自的实际答对率没法算
    # (这些题都答错了), 但可对比: 全体 span-present 题的位置分布 vs 随机均匀
    if first_pos:
        thirds = Counter("head" if p < 1/3 else ("mid" if p < 2/3 else "tail") for p in first_pos)
        print(f"[audit] 三分位分布: head={thirds['head']} mid={thirds['mid']} tail={thirds['tail']} "
              f"(均匀期望 {len(first_pos)/3:.0f} each)")

    # gold 长度与 span 检出率的关系 (长 gold 描述性答案更难逐字命中)
    short = [d for d in details if d["gold_len_words"] <= 5]
    long_ = [d for d in details if d["gold_len_words"] > 5]
    for name, grp in (("短gold(<=5词)", short), ("长gold(>5词)", long_)):
        if grp:
            sp = sum(1 for d in grp if d["class"] == "span-present")
            print(f"[audit] {name}: n={len(grp)} span-present={sp} ({sp/len(grp):.1%})")

    by_type = {}
    for d in details:
        t = by_type.setdefault(d["question_type"], Counter())
        t[d["class"]] += 1
    print("[audit] 按题型:")
    for t, c in sorted(by_type.items()):
        print(f"  {t:28s} total={sum(c.values()):3d}  " +
              "  ".join(f"{k}={c[k]}" for k in ("span-present", "partial", "absent")))

    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    (OUT / "tables" / "snippet_audit.json").write_text(
        json.dumps({
            "meta": {"policy": POLICY, "budget": BUDGET, "reader": "mimo-v2.6-flash",
                     "n_covered": n_covered, "n_covered_wrong": n,
                     "class_counts": dict(cls_counts)},
            "details": details,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[audit] 明细 -> {OUT / 'tables' / 'snippet_audit.json'}")


if __name__ == "__main__":
    main()

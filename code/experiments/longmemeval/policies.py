# -*- coding: utf-8 -*-
"""六种记忆策略的预算受控实现。

预算 B = 进入答题上下文的 cl100k_base token 数 (系统提示与问题不计入 B,
与"记忆占用上下文"的定义一致, 论文 §Setup 显式声明)。

策略 -> 机制族映射 (mechanism-inspired, 论文 §Method 标注):
  full_context      : 无损 oracle 上界 (不做对比对象)
  sliding_window    : 纯驱逐式窗口
  retrieval         : MemGPT/RAG 式外部存储 + BM25 检索回填
  retrieval_recency : 检索 + 新近混合
  compression       : MemoryBank 式 窗口 + 会话级 LLM 摘要 (真实 LLM 摘要)
  hierarchical      : SGMem 式三层 (新近 + 摘要 + 检索) 预算分割

消融变体 (评审回应, 补上最初缺席的读取/检索侧设计):
  compression_select : 先取再总结——摘要按与问题的相关性排序后再装填
  hierarchical_ev   : 三层 + 事件锚定/时间信号检索腿

插件式强基线 (评审弱点回应, EXTENDED_POLICIES):
  retrieval_sentence : 句子级细粒度检索 (更细于 turn 级, 回应检索粒度质疑)
  compression_fetch  : 先取后总结两阶段流水线 (检索 top 证据 -> 问题聚焦 LLM 压缩,
                       回应"低估 fetch-then-summarize 管道"与"多阶段流水线"质疑)
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from rank_bm25 import BM25Okapi

from common import Question, Turn, ntokens, truncate_to_budget

TIER_SHARES = {"recency": 0.25, "summary": 0.50, "retrieval": 0.25}
# 分配敏感性变体：摘要偏重 / 证据偏重
POLICY_SHARERS = {
    "hierarchical": (0.25, 0.50, 0.25),
    "hierarchical_sumheavy": (0.15, 0.70, 0.15),
    "hierarchical_evidence": (0.40, 0.20, 0.40),
    "hierarchical_ev": (0.25, 0.50, 0.25),
    # 第八轮: 层级家族的两种"更强检索逻辑"
    #   hier_multiindex: 双索引 (turn 索引 + digest 索引) 均按问题相关性查询
    #   hier_traverse  : 检索腿 BM25 命中会话后做 1 跳邻接扩展 (多跳图遍历的最弱形式)
    "hier_multiindex": (0.25, 0.50, 0.25),
    "hier_traverse": (0.25, 0.50, 0.25),
}

# 事件锚定检索腿的融合权重 (hierarchical_ev): 语义分与事件/时间分各占一半
_EV_SEM_W = 0.5
_EV_EVT_W = 0.5


@dataclass
class MemoryPlan:
    """一次查询的记忆装配结果: 进入上下文的段 + 纯内存访问耗时。"""
    segments: list[str] = field(default_factory=list)
    access_ms: float = 0.0
    n_turns: int = 0
    n_summaries: int = 0
    footprint_tokens: int = 0
    # 证据溯源 (检索阶段诊断用): 保留轮次所属会话 / 保留摘要所属会话
    covered_turn_sessions: set = field(default_factory=set)
    covered_summary_sessions: set = field(default_factory=set)
    # 证据溯源 (检索阶段诊断用): 被选中轮次所属会话 / 被纳入摘要的会话
    sel_sessions: set = field(default_factory=set)
    sel_summ_sessions: set = field(default_factory=set)

    def finalize(self) -> "MemoryPlan":
        self.footprint_tokens = ntokens("\n\n".join(self.segments))
        return self


def _tail_turns(turns: list[Turn], budget: int) -> list[Turn]:
    """按时间序取最新轮次直到装满预算。"""
    chosen: list[Turn] = []
    used = 0
    for t in reversed(turns):
        if used + t.ntok > budget:
            break
        chosen.append(t)
        used += t.ntok
    return list(reversed(chosen))


def _bm25_rank(turns: list[Turn], query: str) -> list[Turn]:
    if not turns:
        return []
    corpus = [t.text.split() for t in turns]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(query.split())
    ranked = sorted(zip(turns, scores), key=lambda x: -x[1])
    return [t for t, _ in ranked]


def _dense_rank(turns: list[Turn], qe, turn_embs) -> list[Turn]:
    """按 turn 向量与问题向量的余弦相似度排序 (向量缺失的 turn 排最后)。"""
    import math

    qn = math.sqrt(sum(x * x for x in qe)) or 1.0
    scored = []
    for t in turns:
        v = (turn_embs or {}).get(t.turn_key)
        if v is None:
            scored.append((t, -1.0))
            continue
        dot = sum(a * b for a, b in zip(qe, v))
        vn = math.sqrt(sum(x * x for x in v)) or 1.0
        scored.append((t, dot / (qn * vn)))
    scored.sort(key=lambda x: -x[1])
    return [t for t, _ in scored]


def _rrf_rank(turns: list[Turn], q: Question, qe, turn_embs, k: int = 60) -> list[Turn]:
    """BM25 与 dense 的 Reciprocal-Rank-Fusion 融合排序。"""
    bm25_order = {t.turn_key: r for r, t in enumerate(_bm25_rank(turns, q.question))}
    dense_order = {t.turn_key: r for r, t in enumerate(_dense_rank(turns, qe, turn_embs))}
    ids = set(bm25_order) | set(dense_order)
    score = {
        i: 1.0 / (k + bm25_order.get(i, 10**6)) + 1.0 / (k + dense_order.get(i, 10**6))
        for i in ids
    }
    by_key = {t.turn_key: t for t in turns}
    return [by_key[i] for i in sorted(score, key=lambda x: -score[x])]


def _fill_from_ranked(ranked: list[Turn], budget: int, skip: set[tuple[int, int]]) -> list[Turn]:
    chosen: list[Turn] = []
    used = 0
    for t in ranked:
        key = (t.session_idx, t.turn_idx)
        if key in skip:
            continue
        if used + t.ntok > budget:
            break
        chosen.append(t)
        used += t.ntok
    return chosen


def _traverse_expand(seeds: list[Turn], ranked: list[Turn], q: Question,
                     budget: int, skip: set[tuple[int, int]]) -> list[Turn]:
    """1 跳邻接扩展: 以 BM25 命中的会话为锚, 把会话序列上的前后邻居整段拉进来。

    多跳图遍历的最小可用形式 (会话邻接图, 无学习边权): 若答案需要相邻会话的
    上下文 (跨会话共指/时间承接), 纯 turn 检索拿不到, 而邻接扩展可以。预算仍
    严格受限: 先按会话序装填邻域整段, 剩余预算再回落到 BM25 序。"""
    if not seeds:
        return seeds
    hit_sessions: list[int] = []
    for t in seeds:
        if t.session_idx not in hit_sessions:
            hit_sessions.append(t.session_idx)
    anchors = hit_sessions[:2]
    order = {sid: i for i, sid in enumerate(q.session_ids)}
    idx_to_sid = {i: sid for sid, i in order.items()}
    neigh: set[int] = set()
    for a in anchors:
        for j in (a - 1, a + 1):
            if j in idx_to_sid:
                neigh.add(j)
    neigh_sids = {idx_to_sid[j] for j in neigh}
    pool = [t for t in q.turns if t.session_id in neigh_sids]
    chosen: list[Turn] = []
    used = 0
    seen = set(skip)
    for t in pool + ranked:
        key = (t.session_idx, t.turn_idx)
        if key in seen:
            continue
        if used + t.ntok > budget:
            continue
        chosen.append(t)
        seen.add(key)
        used += t.ntok
    return chosen


# --------------------------------------------------------------------------- #
# 句子级细粒度检索单元 (retrieval_sentence): 比 turn 级更细的检索单元
# --------------------------------------------------------------------------- #
_SENT_SPLIT = re.compile(r"(?<=[.!?。！？])\s+|\n+")


@dataclass
class SentenceUnit:
    turn: Turn
    text: str   # "role: 句子" 完整可检索文本
    ntok: int


def _sentence_units(turns: list[Turn]) -> list[SentenceUnit]:
    units: list[SentenceUnit] = []
    for t in turns:
        for s in _SENT_SPLIT.split(t.content or ""):
            s = s.strip()
            if not s:
                continue
            text = f"{t.role}: {s}"
            units.append(SentenceUnit(turn=t, text=text, ntok=ntokens(text)))
    return units


def _bm25_rank_units(units: list[SentenceUnit], query: str) -> list[SentenceUnit]:
    if not units:
        return []
    bm25 = BM25Okapi([u.text.split() for u in units])
    scored = sorted(zip(units, bm25.get_scores(query.split())), key=lambda x: -x[1])
    return [u for u, _ in scored]


def _sentence_segments(units: list[SentenceUnit]) -> list[str]:
    """选中句子按时间序还原: 同轮次的相邻句子合并为一段。"""
    ordered = sorted(units, key=lambda u: (u.turn.session_idx, u.turn.turn_idx))
    segs: list[str] = []
    cur: list[str] = []
    last_key = None
    for u in ordered:
        key = (u.turn.session_idx, u.turn.turn_idx)
        if cur and key != last_key:
            segs.append("\n".join(cur))
            cur = []
        cur.append(u.text)
        last_key = key
    if cur:
        segs.append("\n".join(cur))
    return segs


# --------------------------------------------------------------------------- #
# 先取后总结 (compression_fetch) 的取证据阶段: BM25 top 轮次拼接,
# 装填上限 FETCH_MULT x budget (阶段 2 的 LLM 问题聚焦压缩在 llm.summarize_fetched)
# --------------------------------------------------------------------------- #
FETCH_MULT = 2.0


def fetch_evidence(q: "Question", budget: int, mult: float = FETCH_MULT) -> str:
    ranked = _bm25_rank(q.turns, q.question)
    cap = int(budget * mult)
    chosen = _fill_from_ranked(ranked, cap, set())
    chosen.sort(key=lambda t: (t.session_idx, t.turn_idx))
    return "\n".join(t.text for t in chosen)


def _turn_segments(turns: list[Turn]) -> list[str]:
    # 保持时间顺序, 相邻同会话轮次合并为一段
    segs: list[str] = []
    cur: list[Turn] = []
    for t in turns:
        if cur and t.session_idx != cur[-1].session_idx:
            segs.append("\n".join(x.text for x in cur))
            cur = []
        cur.append(t)
    if cur:
        segs.append("\n".join(x.text for x in cur))
    return segs


def _summary_segments(sums: dict[str, str], session_ids: list[str], budget: int) -> tuple[list[str], int, list[str]]:
    """从最新会话向前装填摘要, 返回 (段, 使用 token 数, 选中摘要的会话 id)。"""
    segs: list[str] = []
    picked: list[str] = []
    used = 0
    for sid in reversed(session_ids):
        s = sums.get(sid)
        if not s:
            continue
        tok = ntokens(s)
        if used + tok > budget:
            if used == 0:  # 预算连一条摘要都放不下: 截断放入
                s = truncate_to_budget(s, budget)
                tok = budget
            else:
                break
        segs.append(s)
        picked.append(sid)
        used += tok
    return segs, used, picked


def _summary_rank(sums: dict[str, str], session_ids: list[str], query: str) -> list[str]:
    """按摘要与问题的 BM25 相关性给出会话偏好序 (读取侧相关性感知)。"""
    cands = [sid for sid in session_ids if sums.get(sid)]
    if not cands:
        return []
    bm25 = BM25Okapi([sums[sid].split() for sid in cands])
    scored = sorted(zip(cands, bm25.get_scores(query.split())), key=lambda x: -x[1])
    return [sid for sid, _ in scored]


def _summary_segments_ranked(sums: dict[str, str], session_ids: list[str],
                             budget: int, query: str) -> tuple[list[str], int, list[str]]:
    """按相关性排序装填摘要, 返回 (段, 使用 token 数, 选中摘要的会话 id)。"""
    segs: list[str] = []
    picked: list[str] = []
    used = 0
    for sid in _summary_rank(sums, session_ids, query):
        s = sums[sid]
        tok = ntokens(s)
        if used + tok > budget:
            if used == 0:
                s = truncate_to_budget(s, budget)
                tok = budget
            else:
                continue  # 相关性序: 跳过放不下的, 继续看后面的
        segs.append(s)
        picked.append(sid)
        used += tok
    return segs, used, picked


def _date_of(session_dates: dict, sid: str) -> float:
    """会话首次出现时间 -> 可比较的浮点 (缺则为 +inf, 排最后)。"""
    import datetime

    raw = (session_dates or {}).get(sid)
    if not raw:
        return float("inf")
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", str(raw))
    if not m:
        return float("inf")
    try:
        return datetime.datetime(*map(int, m.groups())).timestamp()
    except ValueError:
        return float("inf")


def _ev_rank(turns: list[Turn], q: "Question", session_dates: dict) -> list[Turn]:
    """事件锚定 + 时间信号检索排序。

    语义分 (BM25) 与事件分各占一半。事件分 = 时间邻近度 x 事件锚定命中:
      - 时间邻近: |会话时间 - 提问时间| 越小分越高 (指数衰减, 30 天尺度)
      - 事件锚定: 轮次含显式时间表达式 (日期/星期/相对时间) 视为事件锚点
    """
    import math

    sem_order = {t.turn_key: r for r, t in enumerate(_bm25_rank(turns, q.question))}
    qt = _date_of({"__q__": getattr(q, "question_date", "")}, "__q__")
    if qt == float("inf"):
        qt = 0.0
    sess_t = {}
    for t in turns:
        if t.session_id not in sess_t:
            sess_t[t.session_id] = _date_of(session_dates or {}, t.session_id)
    anchor_re = re.compile(
        r"\b(\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}[/-]\d{1,2}"
        r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
        r"|yesterday|tomorrow|last\s+\w+|next\s+\w+|\d+\s*(?:days?|weeks?|months?|years?)\s+ago"
        r"|january|february|march|april|may|june|july|august|september|october|november|december)\b",
        re.I,
    )
    evt_scores = {}
    for t in turns:
        st = sess_t.get(t.session_id, float("inf"))
        if st == float("inf"):
            prox = 0.0
        else:
            prox = math.exp(-abs(st - qt) / (30 * 86400.0))
        anch = 1.0 if anchor_re.search(t.content or "") else 0.0
        evt_scores[t.turn_key] = 0.5 * prox + 0.5 * anch
    max_sem = max(len(turns), 1)
    fused = {}
    keys = set(sem_order) | set(evt_scores)
    for k in keys:
        sem = 1.0 - sem_order.get(k, max_sem) / max_sem
        fused[k] = _EV_SEM_W * sem + _EV_EVT_W * evt_scores.get(k, 0.0)
    by_key = {t.turn_key: t for t in turns}
    return [by_key[k] for k in sorted(fused, key=lambda x: -fused[x])]


def build_memory(
    policy: str,
    q: Question,
    budget: int | None,
    summaries: dict[str, str],
    qe: "list[float] | None" = None,
    turn_embs: "dict[int, list[float]] | None" = None,
    summary_variant: str = "",
    session_dates: "dict[str, str] | None" = None,
    fetch: "dict[str, str] | None" = None,
) -> MemoryPlan:
    t0 = time.perf_counter()
    plan = MemoryPlan()
    turns = q.turns

    if policy == "full_context":
        plan.segments = _turn_segments(turns)
        plan.n_turns = len(turns)
        plan.covered_turn_sessions = {t.session_id for t in turns}
    elif policy == "sliding_window":
        sel = _tail_turns(turns, budget)
        plan.segments = _turn_segments(sel)
        plan.n_turns = len(sel)
        plan.covered_turn_sessions = {t.session_id for t in sel}
    elif policy == "retrieval":
        ranked = _bm25_rank(turns, q.question)
        sel = _fill_from_ranked(ranked, budget, set())
        sel.sort(key=lambda t: (t.session_idx, t.turn_idx))
        plan.segments = _turn_segments(sel)
        plan.n_turns = len(sel)
        plan.covered_turn_sessions = {t.session_id for t in sel}
    elif policy == "retrieval_recency":
        half = budget // 2
        tail = _tail_turns(turns, half)
        skip = {(t.session_idx, t.turn_idx) for t in tail}
        ranked = _bm25_rank(turns, q.question)
        retr = _fill_from_ranked(ranked, budget - sum(t.ntok for t in tail), skip)
        merged = sorted(tail + retr, key=lambda t: (t.session_idx, t.turn_idx))
        plan.segments = _turn_segments(merged)
        plan.n_turns = len(merged)
        plan.covered_turn_sessions = {t.session_id for t in merged}
    elif policy in ("compression", "compression_select"):
        rec_b = int(budget * 0.25)
        tail = _tail_turns(turns, rec_b)
        rest = budget - sum(t.ntok for t in tail)
        if policy == "compression_select":
            # 先取再总结: 摘要按与问题的相关性排序后装填, 而非纯取最近
            segs, used, picked = _summary_segments_ranked(
                summaries, q.session_ids, rest, q.question
            )
        else:
            segs, used, picked = _summary_segments(summaries, q.session_ids, rest)
        plan.segments = _turn_segments(tail) + segs
        plan.n_turns = len(tail)
        plan.n_summaries = len(segs)
        plan.covered_turn_sessions = {t.session_id for t in tail}
        plan.covered_summary_sessions = set(picked)
    elif policy in ("dense_retrieval", "hybrid_retrieval"):
        if policy == "dense_retrieval":
            ranked = _dense_rank(turns, qe, turn_embs)
        else:
            ranked = _rrf_rank(turns, q, qe, turn_embs)
        sel = _fill_from_ranked(ranked, budget, set())
        sel.sort(key=lambda t: (t.session_idx, t.turn_idx))
        plan.segments = _turn_segments(sel)
        plan.n_turns = len(sel)
        plan.covered_turn_sessions = {t.session_id for t in sel}
    elif policy == "retrieval_sentence":
        # 句子级细粒度检索: 以句子为检索单元 BM25 排序, 按预算装填 (可跨句拼满预算)
        units = _sentence_units(turns)
        ranked = _bm25_rank_units(units, q.question)
        chosen: list[SentenceUnit] = []
        used = 0
        for u in ranked:
            if used + u.ntok > budget:
                continue  # 句子短: 跳过放不下的, 继续看后面的 (提高预算利用率)
            chosen.append(u)
            used += u.ntok
            if used >= budget:
                break
        plan.segments = _sentence_segments(chosen)
        plan.n_turns = len({(u.turn.session_idx, u.turn.turn_idx) for u in chosen})
        plan.covered_turn_sessions = {u.turn.session_id for u in chosen}
    elif policy == "compression_fetch":
        # 先取后总结两阶段流水线: 阶段1 BM25 取证据(fetch_evidence) ->
        # 阶段2 问题聚焦 LLM 压缩(summarize_fetched, 预计算传入 fetch dict)。
        # 预计算缺失时确定性降级为截断原始证据 (不发起 LLM 调用, 保证流程不中断)。
        digest = (fetch or {}).get(f"{budget}|{q.question_id}", "")
        if not digest:
            digest = fetch_evidence(q, budget)
        digest = truncate_to_budget(digest, budget)
        plan.segments = [digest]
        plan.n_summaries = 1
    elif policy in POLICY_SHARERS:
        rec_s, sum_s, ret_s = POLICY_SHARERS[policy]
        rec_b = int(budget * rec_s)
        sum_b = int(budget * sum_s)
        tail = _tail_turns(turns, rec_b)
        if policy in ("hierarchical_ev", "hier_multiindex"):
            segs, _, picked = _summary_segments_ranked(
                summaries, q.session_ids, sum_b, q.question
            )
        else:
            segs, _, picked = _summary_segments(summaries, q.session_ids, sum_b)
        skip = {(t.session_idx, t.turn_idx) for t in tail}
        if policy == "hierarchical_ev":
            ranked = _ev_rank(turns, q, session_dates)
        else:
            ranked = _bm25_rank(turns, q.question)
        retr = _fill_from_ranked(ranked, int(budget * ret_s), skip)
        if policy == "hier_traverse":
            retr = _traverse_expand(retr, ranked, q, int(budget * ret_s), skip)
        merged = sorted(tail + retr, key=lambda t: (t.session_idx, t.turn_idx))
        plan.segments = _turn_segments(merged) + segs
        plan.n_turns = len(merged)
        plan.n_summaries = len(segs)
        plan.covered_turn_sessions = {t.session_id for t in merged}
        plan.covered_summary_sessions = set(picked)
    else:
        raise ValueError(f"unknown policy: {policy}")

    plan.access_ms = (time.perf_counter() - t0) * 1000.0
    return plan.finalize()


POLICIES = [
    "full_context",
    "sliding_window",
    "retrieval",
    "retrieval_recency",
    "compression",
    "hierarchical",
]

ABLATION_POLICIES = [
    "dense_retrieval",
    "hybrid_retrieval",
    "hierarchical_sumheavy",
    "hierarchical_evidence",
]

# 读取侧相关性感知 + 事件锚定检索 (评审回应新增)
ABLATION_POLICIES_V2 = [
    "compression_select",
    "hierarchical_ev",
]

# 插件式强基线 (评审弱点回应): 细粒度检索 + 先取后总结多阶段流水线
EXTENDED_POLICIES = [
    "retrieval_sentence",
    "compression_fetch",
]

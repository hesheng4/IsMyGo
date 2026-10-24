"""三种记忆策略：全量上下文 / 滑动窗口 / 检索式记忆（BM25 + recency 先验）。

统一接口：
    mem = Strategy(budget=..., recency_boost=...)  # budget = 记忆槽位上限
    mem.write(entity, attr, value)
    mem.query(entity, attr) -> str | None

机制对比点：
- FullContext：无遗忘上界基线（预算=∞），准确率上界、footprint 最大。
- SlidingWindow：按键去重、只留最近 budget 次写入，ancient 带必然衰减，
  但对重写天然免疫（旧键被新值原地覆盖）。
- RetrievalMemory：按写入原样建索引（不去重、不删旧版本），
  取最近 budget 条原始写入，查询时 BM25 检索 top-1。
  * recency_boost=0：同键新旧版本得分并列，平局按旧文档优先 →
    重写场景出现"陈旧答案"失败模式（无版本控制的朴素 RAG 记忆）。
  * recency_boost>0：得分加时间先验 → 新版本胜出（recency-aware 检索）。
"""

from __future__ import annotations

import math
import re
from collections import Counter, deque

_TOKEN = re.compile(r"[a-z0-9]+")

BM25_K1 = 1.5
BM25_B = 0.75


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class FullContext:
    """基线：按键去重保留全部事实（预算无限）。"""

    unlimited = True

    def __init__(self, budget: int = 0, recency_boost: float = 0.0) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def write(self, entity: str, attr: str, value: str) -> None:
        self._store[(entity, attr)] = value

    def query(self, entity: str, attr: str) -> str | None:
        return self._store.get((entity, attr))

    def footprint(self) -> int:
        return len(self._store)


class SlidingWindow:
    """按键去重、容量 budget 的最近写入缓冲。"""

    unlimited = False

    def __init__(self, budget: int, recency_boost: float = 0.0) -> None:
        if budget <= 0:
            raise ValueError(f"budget must be positive, got {budget}")
        self._budget = budget
        self._order: deque[tuple[str, str]] = deque()
        self._store: dict[tuple[str, str], str] = {}

    def write(self, entity: str, attr: str, value: str) -> None:
        key = (entity, attr)
        if key not in self._store:
            self._order.append(key)
        self._store[key] = value
        if len(self._order) > self._budget:
            self._store.pop(self._order.popleft(), None)

    def query(self, entity: str, attr: str) -> str | None:
        return self._store.get((entity, attr))

    def footprint(self) -> int:
        return len(self._store)


class RetrievalMemory:
    """原始写入索引（不去重）+ BM25 top-1 + 可选 recency 先验。"""

    unlimited = False

    def __init__(self, budget: int, recency_boost: float = 0.0) -> None:
        if budget <= 0:
            raise ValueError(f"budget must be positive, got {budget}")
        self._budget = budget
        self._boost = recency_boost
        self._docs: deque[tuple[tuple[str, str], str, list[str]]] = deque()

    def write(self, entity: str, attr: str, value: str) -> None:
        self._docs.append(((entity, attr), value,
                           _tokens(f"{entity} {attr} {value}")))
        if len(self._docs) > self._budget:
            self._docs.popleft()

    def query(self, entity: str, attr: str) -> str | None:
        n = len(self._docs)
        if n == 0:
            return None
        q_terms = set(_tokens(f"{entity} {attr}"))
        avg_len = sum(len(t) for _, _, t in self._docs) / n
        df: Counter[str] = Counter(
            tok for _, _, toks in self._docs for tok in set(toks)
        )
        best_score = -1.0
        best_idx = -1
        best_val: str | None = None
        for i, (_, val, toks) in enumerate(self._docs):
            tf = Counter(toks)
            score = 0.0
            for term in q_terms:
                d = df.get(term, 0)
                f = tf.get(term, 0)
                if d == 0 or f == 0:
                    continue
                idf = math.log(1.0 + (n - d + 0.5) / (d + 0.5))
                denom = f + BM25_K1 * (1.0 - BM25_B + BM25_B * len(toks) / avg_len)
                score += idf * f * (BM25_K1 + 1.0) / max(denom, 1e-9)
            score += self._boost * ((i / (n - 1)) if n > 1 else 1.0)
            better = score > best_score + 1e-12
            # 平局（boost=0 时同键版本并列）：旧文档优先 → 陈旧答案失败模式
            tie_older = (abs(score - best_score) <= 1e-12 and i < best_idx)
            if better or tie_older:
                best_score, best_idx, best_val = score, i, val
        return best_val

    def footprint(self) -> int:
        return len(self._docs)


class CompressionMemory:
    """压缩/摘要层：recent 逐字窗口 + 旧事实压入"实体级摘要"。

    压缩协议（确定性、无 LLM）：
    - 预算 B 分为近切窗口 W 与摘要槽 S（W = B//2, S = B - W）。
    - 新事实进近切窗口逐字保留；超 W 时最旧事实被"压缩"进实体摘要：
      每实体摘要至多保留 digest_cap 条最近属性（折损低频/久远属性）。
    - 摘要实体数超 S 时，整体淘汰最早实体摘要（全局再压缩）。
    查询：近切窗口精确命中优先，否则查摘要，否则 miss。

    与 SlidingWindow 差异：被挤出窗口的事实并非丢弃，而是被压缩进
    实体摘要（按实体去重、保留最近属性），budget 覆盖更多实体，
    但牺牲单实体属性粒度 —— 呈现"覆盖率 vs 保真度"的压缩权衡。
    """

    unlimited = False

    def __init__(self, budget: int, recency_boost: float = 0.0,
                 recency_frac: float = 0.5, digest_cap: int = 2) -> None:
        if budget < 2:
            raise ValueError(f"budget must be >= 2, got {budget}")
        self._budget = budget
        self._digest_cap = digest_cap
        self._recency_slots = max(int(budget * recency_frac), 1)
        self._summary_slots = budget - self._recency_slots
        self._recent: deque[tuple[tuple[str, str], str]] = deque()
        self._recent_map: dict[tuple[str, str], str] = {}
        self._digest: dict[str, dict[str, str]] = {}
        self._digest_order: deque[str] = deque()

    def write(self, entity: str, attr: str, value: str) -> None:
        key = (entity, attr)
        if key in self._recent_map:  # 近切窗口内重写：原地更新并刷新顺序
            self._recent_map[key] = value
            self._recent.remove(key)
            self._recent.append(key)
            return
        digest_ent = self._digest.get(entity)
        if digest_ent is not None and attr in digest_ent:  # 摘要内重写
            digest_ent[attr] = value
            return
        self._recent.append(key)
        self._recent_map[key] = value
        if len(self._recent) > self._recency_slots:
            self._flush_oldest()

    def _flush_oldest(self) -> None:
        key = self._recent.popleft()
        entity, attr = key
        value = self._recent_map.pop(key)
        if entity not in self._digest:
            if len(self._digest) >= self._summary_slots:
                oldest = self._digest_order.popleft()
                self._digest.pop(oldest, None)
            self._digest[entity] = {}
            self._digest_order.append(entity)
        d = self._digest[entity]
        if len(d) < self._digest_cap or attr in d:
            d[attr] = value  # 摘要未满或该属性已存在 → 收录/更新

    def query(self, entity: str, attr: str) -> str | None:
        key = (entity, attr)
        if key in self._recent_map:
            return self._recent_map[key]
        d = self._digest.get(entity)
        if d is not None and attr in d:
            return d[attr]
        return None

    def footprint(self) -> int:
        return len(self._recent_map) + sum(len(v) for v in self._digest.values())


class HierarchicalMemory:
    """三阶层级记忆引擎：recency 窗口(精确) + 压缩摘要(覆盖) + BM25 检索(精度)。

    预算 B 分三阶：W=recency（逐字最近）、D=摘要槽（实体级压缩摘要）、
    R=检索槽（BM25 索引，recency 挤出的事实）。
    查询路由：recency 精确命中 → 摘要命中 → 检索 top-1。
    合成层级：近切可精确回答 recent，压缩摘要覆盖 mid，检索兜底 ancient，
    是论文主张的"层级记忆引擎"的完整实现。
    """

    unlimited = False

    def __init__(self, budget: int, recency_boost: float = 0.0,
                 digest_cap: int = 2) -> None:
        if budget < 4:
            raise ValueError(f"budget must be >= 4, got {budget}")
        self._budget = budget
        self._digest_cap = digest_cap
        self._recency_slots = max(budget // 2, 1)
        rest = budget - self._recency_slots
        self._summary_slots = max(rest // 2, 1)
        self._retrieval_slots = max(rest - self._summary_slots, 1)
        self._recent: deque[tuple[tuple[str, str], str]] = deque()
        self._recent_map: dict[tuple[str, str], str] = {}
        self._digest: dict[str, dict[str, str]] = {}
        self._digest_order: deque[str] = deque()
        self._docs: deque[tuple[tuple[str, str], str, list[str]]] = deque()

    def write(self, entity: str, attr: str, value: str) -> None:
        key = (entity, attr)
        if key in self._recent_map:
            self._recent_map[key] = value
            self._recent.remove(key)
            self._recent.append(key)
            self._update_doc(key, value)
            return
        digest_ent = self._digest.get(entity)
        if digest_ent is not None and attr in digest_ent:
            digest_ent[attr] = value
            self._update_doc(key, value)
            return
        self._recent.append(key)
        self._recent_map[key] = value
        if len(self._recent) > self._recency_slots:
            self._flush_oldest()

    def _update_doc(self, key: tuple[str, str], value: str) -> None:
        """重写时同步更新检索索引与摘要中的旧版本。"""
        entity, attr = key
        for i, (k, _, toks) in enumerate(self._docs):
            if k == key:
                self._docs[i] = (key, value, _tokens(f"{entity} {attr} {value}"))
                return
        digest_ent = self._digest.get(entity)
        if digest_ent is not None and attr in digest_ent:
            digest_ent[attr] = value

    def _flush_oldest(self) -> None:
        key = self._recent.popleft()
        entity, attr = key
        value = self._recent_map.pop(key)
        # 压缩进实体摘要
        if entity not in self._digest:
            if len(self._digest) >= self._summary_slots:
                oldest = self._digest_order.popleft()
                self._digest.pop(oldest, None)
            self._digest[entity] = {}
            self._digest_order.append(entity)
        d = self._digest[entity]
        if len(d) < self._digest_cap or attr in d:
            d[attr] = value
        # 进入检索索引
        self._docs.append(((entity, attr), value,
                           _tokens(f"{entity} {attr} {value}")))
        if len(self._docs) > self._retrieval_slots:
            self._docs.popleft()

    def query(self, entity: str, attr: str) -> str | None:
        key = (entity, attr)
        if key in self._recent_map:
            return self._recent_map[key]
        d = self._digest.get(entity)
        if d is not None and attr in d:
            return d[attr]
        return self._bm25(entity, attr)

    def _bm25(self, entity: str, attr: str) -> str | None:
        n = len(self._docs)
        if n == 0:
            return None
        q_terms = set(_tokens(f"{entity} {attr}"))
        avg_len = sum(len(t) for _, _, t in self._docs) / n
        df: Counter[str] = Counter(
            tok for _, _, toks in self._docs for tok in set(toks)
        )
        best_score = -1.0
        best_idx = -1
        best_val: str | None = None
        for i, (_, val, toks) in enumerate(self._docs):
            tf = Counter(toks)
            score = 0.0
            for term in q_terms:
                dd = df.get(term, 0)
                f = tf.get(term, 0)
                if dd == 0 or f == 0:
                    continue
                idf = math.log(1.0 + (n - dd + 0.5) / (dd + 0.5))
                denom = f + BM25_K1 * (1.0 - BM25_B + BM25_B * len(toks) / avg_len)
                score += idf * f * (BM25_K1 + 1.0) / max(denom, 1e-9)
            if score > best_score + 1e-12:
                best_score, best_idx, best_val = score, i, val
        return best_val

    def footprint(self) -> int:
        return (len(self._recent_map)
                + sum(len(v) for v in self._digest.values())
                + len(self._docs))


def build(kind: str, budget: int, recency_boost: float = 0.0):
    if kind == "full_context":
        return FullContext(budget, recency_boost)
    if kind == "sliding_window":
        return SlidingWindow(budget, recency_boost)
    if kind == "retrieval":
        return RetrievalMemory(budget, recency_boost=0.0)
    if kind == "retrieval_recency":
        return RetrievalMemory(budget, recency_boost=1.0)
    if kind == "compression":
        return CompressionMemory(budget, recency_boost)
    if kind == "hierarchical":
        return HierarchicalMemory(budget, recency_boost)
    raise ValueError(kind)
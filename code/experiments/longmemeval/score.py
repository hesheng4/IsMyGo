# -*- coding: utf-8 -*-
"""打分与统计: EM / token-F1 (LongMemEval 官方口径), 按题配对 bootstrap 95% CI,
McNemar 精确检验 (无 scipy 依赖, math.comb 实现二项精确p值)。"""
from __future__ import annotations

import math
import random
import re
from collections import Counter

_ARTICLES = re.compile(r"\b(a|an|the)\b")
_PUNCT = re.compile(r"[^\w\s]")


def normalize(s) -> str:
    s = str(s).lower().strip()  # 部分标准答案为 int/年份, 统一转字符串
    s = _PUNCT.sub(" ", s)
    s = _ARTICLES.sub(" ", s)
    return " ".join(s.split())


def em(pred: str, gold: str) -> float:
    return 1.0 if normalize(pred) == normalize(gold) else 0.0


def relaxed_em(pred: str, gold: str) -> float:
    """宽松 EM: 归一化后 gold 为 pred 子串即算对 (SQuAD 式 containment,
    对开放短语的 gold 更公平; 与严格 EM 同步报告)。"""
    p, g = normalize(pred), normalize(gold)
    if not g:
        return 1.0 if not p else 0.0
    return 1.0 if g in p else 0.0


def token_f1(pred: str, gold: str) -> float:
    p, g = normalize(pred).split(), normalize(gold).split()
    if not p or not g:
        return 1.0 if not p and not g else 0.0
    common = Counter(p) & Counter(g)
    overlap = sum(common.values())
    if overlap == 0:
        return 0.0
    prec, rec = overlap / len(p), overlap / len(g)
    return 2 * prec * rec / (prec + rec)


def paired_bootstrap(
    a: list[float], b: list[float], n_boot: int = 10000, seed: int = 42
) -> tuple[float, float, float]:
    """返回 (a 均值, b 均值, P(a-b > 0) 的 bootstrap 置信水平)。
    delta_ci: 差值 a-b 的 95% CI。"""
    assert len(a) == len(b)
    rng = random.Random(seed)
    n = len(a)
    deltas = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        deltas.append(sum(a[i] - b[i] for i in idx) / n)
    deltas.sort()
    lo, hi = deltas[int(0.025 * n_boot)], deltas[int(0.975 * n_boot)]
    p_greater = sum(1 for d in deltas if d > 0) / n_boot
    return (sum(a) / n, sum(b) / n, p_greater), (lo, hi)


def mcnemar_exact(a: list[float], b: list[float]) -> dict:
    """按题二值正确性 (阈值 EM>0 或传入前自行二值化) 的精确 McNemar。"""
    bin_a = [x > 0.5 for x in a]
    bin_b = [x > 0.5 for x in b]
    n01 = sum(1 for x, y in zip(bin_a, bin_b) if not x and y)  # b对a错
    n10 = sum(1 for x, y in zip(bin_a, bin_b) if x and not y)  # a对b错
    n = n01 + n10
    if n == 0:
        return {"n10": n10, "n01": n01, "p_value": 1.0}
    k = min(n10, n01)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2**n
    return {"n10": n10, "n01": n01, "p_value": min(1.0, 2 * p)}

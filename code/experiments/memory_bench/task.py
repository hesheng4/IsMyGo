"""合成长程记忆任务：流式事实 + 带距离分带的查询集。

任务协议（确定性，仅依赖 seed）：
- 事件流：N 条事实（entity, attr, value），其中穿插重写事实
  （同 entity+attr 出现新 value，记忆策略必须保留最新版本）。
- 查询集：Q 条 "entity.attr = ?"，按事实写入位置到流末尾的距离分带：
  recent（最后 1/3）/ mid / ancient（前 1/3），用于机制级分析
  （记忆容量 vs 召回距离的权衡）。

输出确定性：同 seed 同结果，无随机 API 泄漏。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

ATTRS = ["color", "size", "weight", "status", "owner", "location", "level", "tag"]
VALUES = [
    "red", "blue", "green", "amber", "large", "tiny", "heavy", "light",
    "active", "idle", "alice", "bob", "carol", "north", "south", "east",
    "v0", "v1", "v2", "v3", "beta", "gold", "silver", "bronze",
]


@dataclass(frozen=True)
class Task:
    stream: tuple[tuple[str, str, str], ...]   # 按顺序写入的事实
    queries: tuple[tuple[str, str, str, str], ...]  # (entity, attr, answer, band)


def build_task(seed: int, n_entities: int = 40, facts_per_entity: int = 6,
               n_queries: int = 120, rewrite_ratio: float = 0.15) -> Task:
    """生成长程流式记忆任务。

    Args:
        seed: 随机种子（全任务唯一随机源）。
        n_entities: 实体数（命名 e000..）。
        facts_per_entity: 每实体属性写入次数（含重写）。
        n_queries: 查询数，按距离分带均匀采样。
        rewrite_ratio: 重写比例：同 entity+attr 后写覆盖旧值。

    Returns:
        Task: 事实流 + 分带查询集。
    """
    rng = random.Random(seed)
    entities = [f"e{i:03d}" for i in range(n_entities)]
    stream: list[tuple[str, str, str]] = []
    truth: dict[tuple[str, str], str] = {}
    pos: dict[tuple[str, str], int] = {}

    total = n_entities * facts_per_entity
    for _ in range(total):
        ent = rng.choice(entities)
        if rng.random() < rewrite_ratio:
            # 重写：从已写入的该实体键中挑一个覆盖
            keys = [k for k in truth if k[0] == ent]
            if keys:
                key = rng.choice(keys)
                val = rng.choice(VALUES)
                stream.append((ent, key[1], val))
                truth[key] = val
                pos[key] = len(stream) - 1
                continue
        attr = rng.choice(ATTRS)
        val = rng.choice(VALUES)
        stream.append((ent, attr, val))
        truth[(ent, attr)] = val
        pos[(ent, attr)] = len(stream) - 1

    n = len(stream)
    bands = {"ancient": [], "mid": [], "recent": []}
    for (ent, attr), p in pos.items():
        rel = p / max(n - 1, 1)
        band = "ancient" if rel < 1 / 3 else ("mid" if rel < 2 / 3 else "recent")
        bands.setdefault(band, []).append((ent, attr))

    per_band = max(n_queries // 3, 1)
    queries: list[tuple[str, str, str, str]] = []
    for band, keys in bands.items():
        if not keys:  # 极小参数保护
            continue
        rng.shuffle(keys)
        for ent, attr in keys[:per_band]:
            queries.append((ent, attr, truth[(ent, attr)], band))
    rng.shuffle(queries)
    return Task(stream=tuple(stream), queries=tuple(queries))
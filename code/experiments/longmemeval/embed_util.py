# -*- coding: utf-8 -*-
"""embedding-3 向量化工具: 批量 embed + 按文本 sha1 落盘缓存。

dense/hybrid 检索策略用。缓存文件: cache/embeddings/<sha1>.json
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path

# llm.py 未导出名为 client 的对象；此处以惰性代理暴露其客户端，
# 复用 _get_client()，语义等价：同一 api_key / base_url / timeout。
from llm import _get_client


class _LazyClient:
    """把 llm._get_client() 暴露成 client.embeddings.create(...) 的惰性代理。"""

    @property
    def embeddings(self):
        return _get_client().embeddings


client = _LazyClient()

SEM_EMB = asyncio.Semaphore(8)
EMB_MODEL = "embedding-3"


def _cache_path(cache_dir: Path, text: str) -> Path:
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{h}.json"


async def embed_texts(texts: list[str], cache_dir: Path) -> dict[str, list[float]]:
    """返回 sha1键 -> 向量。未缓存的批量调用 API (每批 16 条), 失败条目重试。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, list[float]] = {}
    missing: list[str] = []
    for txt in texts:
        cp = _cache_path(cache_dir, txt)
        if cp.exists():
            out[cp.stem] = json.loads(cp.read_text(encoding="utf-8"))["v"]
        else:
            missing.append(txt)
    if not missing:
        return out

    # 去重后分批
    uniq = list(dict.fromkeys(missing))
    batches = [uniq[i : i + 16] for i in range(0, len(uniq), 16)]
    sem = SEM_EMB

    async def one(batch: list[str]) -> None:
        for attempt in range(6):
            try:
                async with sem:
                    r = await client.embeddings.create(model=EMB_MODEL, input=batch)
                for txt, d in zip(batch, r.data):
                    cp = _cache_path(cache_dir, txt)
                    cp.write_text(
                        json.dumps({"v": d.embedding}, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    out[cp.stem] = d.embedding
                return
            except Exception:  # noqa: BLE001
                await asyncio.sleep(min(60.0, 2**attempt))
        for txt in batch:  # 最终失败的记空向量, 排序时沉底
            cp = _cache_path(cache_dir, txt)
            out[cp.stem] = []

    t0 = time.perf_counter()
    await asyncio.gather(*(one(b) for b in batches))
    print(f"[embed] {len(uniq)} 条新向量化, 耗时 {time.perf_counter()-t0:.0f}s")
    return out


def load_cached_embeddings(cache_dir: Path, keys: set[str]) -> dict[str, list[float]]:
    """同步读回已缓存的向量 (run 阶段用, 不触发 API)。"""
    out: dict[str, list[float]] = {}
    if not cache_dir.exists():
        return out
    for cp in cache_dir.glob("*.json"):
        if cp.stem in keys:
            out[cp.stem] = json.loads(cp.read_text(encoding="utf-8"))["v"]
    return out

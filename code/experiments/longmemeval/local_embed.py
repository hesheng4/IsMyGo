# -*- coding: utf-8 -*-
"""本地 bge-small-en-v1.5 向量化 (API embedding 额度耗尽后的替代方案)。

模型: ModelScope BAAI/bge-small-en-v1.5 (33M 参数, 384 维, CPU 批量 ~240 texts/s)
缓存: cache/embeddings_bge/<sha1(text)>.json  {"v": [...]}  (与 API 向量目录隔离)

用法:
  python local_embed.py            # 全量向量化 (轮次 + 问题)
  python local_embed.py --answers  # 加载缓存并跑 dense/hybrid 答题
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

from common import load_questions, require_model

HERE = Path(__file__).resolve().parent
CACHE = HERE.parents[1] / "output" / "longmemeval" / "cache"
BGE_DIR = CACHE / "embeddings_bge"
MODEL_PATH = HERE.parents[2] / "models" / "bge-small-en-v1.5"

# bge-small-en-v1.5 官方查询前缀 (短查询检索相关段落)
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def embed_all() -> None:
    from sentence_transformers import SentenceTransformer

    questions = load_questions()
    turn_texts = list({t.text for q in questions for t in q.turns})
    q_texts = [q.question for q in questions]
    print(f"[bge] 轮次文本 {len(turn_texts)} + 问题 {len(q_texts)}")

    BGE_DIR.mkdir(parents=True, exist_ok=True)
    cached = {p.stem for p in BGE_DIR.glob("*.json")}
    todo_passages = [t for t in turn_texts if _key(t) not in cached]
    todo_queries = [t for t in q_texts if _key(QUERY_PREFIX + t) not in cached]

    require_model(MODEL_PATH, "bge-small")
    model = SentenceTransformer(str(MODEL_PATH))
    t0 = time.perf_counter()
    n = 0
    if todo_passages:
        vecs = model.encode(todo_passages, batch_size=256, show_progress_bar=False)
        for txt, v in zip(todo_passages, vecs):
            (BGE_DIR / f"{_key(txt)}.json").write_text(
                json.dumps({"v": v.tolist()}), encoding="utf-8")
        n += len(todo_passages)
    if todo_queries:
        vecs = model.encode([QUERY_PREFIX + t for t in todo_queries],
                            batch_size=64, show_progress_bar=False)
        for txt, v in zip(todo_queries, vecs):
            (BGE_DIR / f"{_key(QUERY_PREFIX + txt)}.json").write_text(
                json.dumps({"v": v.tolist()}), encoding="utf-8")
        n += len(todo_queries)
    print(f"[bge] 新增 {n} 条, 耗时 {time.perf_counter()-t0:.0f}s -> {BGE_DIR}")


def load(turn_keys: set[str]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for p in BGE_DIR.glob("*.json"):
        if p.stem in turn_keys:
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))["v"]
    return out


def question_vectors(questions) -> dict[str, list[float]]:
    out = {}
    for q in questions:
        k = _key(QUERY_PREFIX + q.question)
        p = BGE_DIR / f"{k}.json"
        if p.exists():
            out[q.question_id] = json.loads(p.read_text(encoding="utf-8"))["v"]
    return out


async def run_dense_answers() -> None:
    from common import BUDGETS
    from run import _run_cells

    questions = load_questions()
    turn_embs = load({t.turn_key for q in questions for t in q.turns})
    qe = question_vectors(questions)
    print(f"[dense] 向量就绪: turns={len(turn_embs)} questions={len(qe)}")
    cells = [(p, b, "") for p in ("dense_retrieval", "hybrid_retrieval")
             for b in BUDGETS]
    await _run_cells(cells, questions, {}, turn_embs=turn_embs, qe=qe)
    print("[dense] done")


if __name__ == "__main__":
    if "--answers" in sys.argv:
        asyncio.run(run_dense_answers())
    else:
        embed_all()

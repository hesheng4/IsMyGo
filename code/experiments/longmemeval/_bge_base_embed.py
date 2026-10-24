# -*- coding: utf-8 -*-
"""bge-base-en-v1.5 向量化 (E3 dense 升级, 与 bge-small 目录隔离).

输出: cache/embeddings_bge_base/<sha1(text)>.json {"v": [...]} (768 维)
范围: 120 样本唯一轮次文本 + 查询向量 (与 bge-small 同口径).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from common import load_questions, require_model

HERE = Path(__file__).resolve().parent
CACHE = HERE.parents[1] / "output" / "longmemeval" / "cache"
OUT_DIR = CACHE / "embeddings_bge_base"
MODEL_PATH = HERE.parents[2] / "models" / "bge-base-en-v1.5"

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def main() -> None:
    from sentence_transformers import SentenceTransformer

    questions = load_questions()
    turn_texts = list({t.text for q in questions for t in q.turns})
    q_texts = [q.question for q in questions]
    print(f"[bge-base] 轮次 {len(turn_texts)} + 查询 {len(q_texts)}", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cached = {p.stem for p in OUT_DIR.glob("*.json")}
    todo_passages = [t for t in turn_texts if _key(t) not in cached]
    todo_queries = [t for t in q_texts if _key(QUERY_PREFIX + t) not in cached]
    print(f"[bge-base] 待向量化: passages={len(todo_passages)} queries={len(todo_queries)}", flush=True)

    t0 = time.perf_counter()
    require_model(MODEL_PATH, "bge-base")
    model = SentenceTransformer(str(MODEL_PATH))
    # 线程配置：8 线程 fp32 为本地 CPU 向量化的最优点（更多线程无增益，
    # 更少线程吞吐减半；bf16 autocast 显著更慢），故钉死 8 线程 fp32。
    import torch
    torch.set_num_threads(8)
    if todo_passages:
        for i in range(0, len(todo_passages), 2000):
            chunk = todo_passages[i:i + 2000]
            vecs = model.encode(chunk, batch_size=256, show_progress_bar=False)
            for txt, v in zip(chunk, vecs):
                (OUT_DIR / f"{_key(txt)}.json").write_text(
                    json.dumps({"v": v.tolist()}), encoding="utf-8")
            print(f"[bge-base] passages {min(i+2000, len(todo_passages))}/{len(todo_passages)} "
                  f"({time.perf_counter()-t0:.0f}s)", flush=True)
    if todo_queries:
        vecs = model.encode([QUERY_PREFIX + t for t in todo_queries],
                            batch_size=64, show_progress_bar=False)
        for txt, v in zip(todo_queries, vecs):
            (OUT_DIR / f"{_key(QUERY_PREFIX + txt)}.json").write_text(
                json.dumps({"v": v.tolist()}), encoding="utf-8")
    print(f"[bge-base] DONE in {time.perf_counter()-t0:.0f}s -> {OUT_DIR}", flush=True)


if __name__ == "__main__":
    main()

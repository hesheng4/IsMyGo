# -*- coding: utf-8 -*-
"""GLM-4.7-Flash 上干净重取 full-context oracle (n=60, 失败跳过)。"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import llm
from common import load_questions
from run import OUT, CACHE, _run_cells
from llm import MODEL_ALT

logger = logging.getLogger(__name__)

llm.SEM = asyncio.Semaphore(2)


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    questions = load_questions(n=60)
    import run as _r
    _r.CONCURRENCY = 2
    logger.info(f"[oracle-refetch] n={len(questions)} model={MODEL_ALT}")
    await _run_cells([("full_context", None, "@m47")], questions, {},
                     model_tag=MODEL_ALT)
    # 汇总
    _jsonl_lines = (OUT / "results.jsonl").read_text(encoding="utf-8").splitlines()
    recs = [json.loads(line) for line in _jsonl_lines if line.strip()]
    item = [r for r in recs if r["policy"] == "full_context@m47"]
    logger.info(f"[oracle-refetch] n={len(item)} relaxed_EM={sum(r['relaxed_em'] for r in item)/max(len(item),1):.4f}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(main())

"""Generate GLM-5.3-Flash digests for the stratified 120-question subset (round 9, R5 cross).

Run with PAPER_LAB_MODEL=glm-5.3-flash so the cache namespace and the `model` field of
each digest are GLM-5.3-Flash; loops until every session of the subset has a digest.

Usage: PAPER_LAB_MODEL=glm-5.3-flash python r9_summaries_glm.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import run as R  # noqa: E402
from common import load_questions  # noqa: E402
from llm import MODEL_MAIN  # noqa: E402


async def main() -> None:
    qs = load_questions()
    max_loops = int(os.environ.get("PAPER_LAB_LOOP_MAX", "60"))
    sleep_s = float(os.environ.get("PAPER_LAB_LOOP_SLEEP", "20"))
    print(f"[glm-sum] model={MODEL_MAIN} questions={len(qs)}", flush=True)
    for i in range(1, max_loops + 1):
        t0 = time.time()
        sums = await R.precompute_summaries(qs)
        missing = [sid for sid, v in sums.items() if not v]
        print(f"[glm-sum] loop {i}: sessions={len(sums)} missing={len(missing)} "
              f"{time.time()-t0:.0f}s", flush=True)
        if not missing:
            print("[glm-sum] complete", flush=True)
            return
        await asyncio.sleep(sleep_s)
    print("[glm-sum] gave up", flush=True)
    sys.exit(4)


if __name__ == "__main__":
    asyncio.run(main())

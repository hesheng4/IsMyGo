"""摘要补齐循环: 反复扫描直到全部会话摘要成功 (供 full-500 批2 前置使用).

用法: python summaries_fill.py
环境: PAPER_LAB_CONCURRENCY (默认 6), PAPER_LAB_LOOP_MAX (最大轮数, 默认 500),
      PAPER_LAB_LLM_ATTEMPTS (建议 2: 白天网关拒绝时快进快出, 靠循环轮次重试),
      PAPER_LAB_LOOP_SLEEP (轮间秒数, 默认 60)
每轮调用 run.precompute_summaries -- 已缓存的秒回, 失败的重试; 全部成功即退出。
"""
import asyncio
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import run as R  # noqa: E402
from common import load_questions  # noqa: E402


async def main() -> None:
    qs = load_questions(full=True)
    max_loops = int(os.environ.get("PAPER_LAB_LOOP_MAX", "500"))
    sleep_s = float(os.environ.get("PAPER_LAB_LOOP_SLEEP", "60"))
    for i in range(1, max_loops + 1):
        t0 = time.time()
        try:
            sums = await R.precompute_summaries(qs)
        except Exception:
            print(f"[loop {i}] precompute 异常:\n{traceback.format_exc()}", flush=True)
            await asyncio.sleep(sleep_s)
            continue
        missing = [sid for sid, v in sums.items() if not v]
        print(f"[loop {i}] 总会话 {len(sums)}  缺失 {len(missing)}  "
              f"本轮耗时 {time.time()-t0:.0f}s", flush=True)
        if not missing:
            print("[loop] 全部摘要就绪 ✓", flush=True)
            return
        await asyncio.sleep(sleep_s)
    print(f"[loop] 达到最大轮数 {max_loops}, 仍有缺失 — 退出码 4", flush=True)
    sys.exit(4)


if __name__ == "__main__":
    asyncio.run(main())

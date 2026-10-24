"""实验执行总入口：跑全部实验 → 写 output/results.json（唯一事实基准）。

运行：python experiments/run_all.py [--out PATH] [--quick]
- 沙箱运行：scripts/sandbox_runner.py 以子进程调起本脚本，超时保护。
- 幻觉校验基准：HallucinationCheckRail 默认读取 ~/.jiuwenswarm/.../results.json，
  部署时把该路径软链/复制为本输出，或配置 paper_guard.results_path。
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))

from memory_bench import run_experiment  # noqa: E402

DEFAULT_OUT = HERE.parent / "output" / "results.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--quick", action="store_true",
                        help="快速档：单种子小规模（冒烟用）")
    args = parser.parse_args()

    t0 = time.perf_counter()
    if args.quick:
        memory_bench = run_experiment(seeds=(42,), budgets=(16, 32),
                                      n_entities=20, facts_per_entity=4, n_queries=60)
    else:
        memory_bench = run_experiment(seeds=(42, 43, 44), budgets=(16, 32, 64))

    duration = round(time.perf_counter() - t0, 3)
    payload = {
        "meta": {
            "topic": "Agent记忆引擎：长程流式任务中的记忆策略权衡",
            "experiment": "memory_bench",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "duration_sec": duration,
            "deterministic": True,
        },
        "experiments": {"memory_bench": memory_bench},
        "provenance": {
            "cmd": "python experiments/run_all.py",
            "cwd": str(HERE.parent),
            "seed_policy": "random.Random(seed) per task; no global RNG leakage",
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # 末行 JSON 摘要（供沙箱执行器捕获）
    logger.info(json.dumps({"ok": True, "out": str(out), "duration_sec": duration}))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
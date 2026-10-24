# -*- coding: utf-8 -*-
"""main.py —— Agent 科研流水线统一入口（对应提交样例 code/main.py）

本项目按四条路径组织，main.py 负责调度并按需写出 `logs/` 与 `output/`：

  ① experiments/run_all.py            确定性实验真值（零 LLM，output/results.json）
  ② system/run_system.py              主系统：规划→实验→因果分析→写作→评审
  ③ experiments/longmemeval/run.py    LongMemEval 真实 LLM 主实验（论文数字来源）
  ④ deploy/research_pipeline_v5.py    JiuwenSwarm 引擎部署版流水线（需引擎）

用法：
  # 零 LLM 路径（约 10 秒）：只跑 ①+②
  python code/main.py

  # 与 logs/、output/ 对应的论文运行（真实 LLM，约 83 分钟，消耗约 3,000 万 token）
  python code/main.py --paper-run

  # 冒烟档：11 题，约 10 分钟，用于验证环境
  python code/main.py --paper-run --smoke

`--paper-run` 依次执行 ③ 主实验（带 `--log-run`，写 logs/）→ 表格生成 → `populate_output.py`
（整理 output/ 并编译 PDF）。产出的 logs/ 与 output/ 同属一次运行，run_id 均为
`agent-sci-2026-comp-001`。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent      # code/
PKG = HERE.parent                            # IsMyGo/
PY = sys.executable


def run(label: str, cmd: list, cwd: Path | None = None, env: dict | None = None) -> None:
    """按序执行子命令，失败即中止并保留输出便于排查。"""
    print("\n=== %s ===\n$ %s" % (label, " ".join(str(c) for c in cmd)), flush=True)
    rc = subprocess.call([str(c) for c in cmd], cwd=str(cwd or HERE), env=env)
    if rc != 0:
        sys.exit("[main] %s 失败（exit=%d），流水线中止" % (label, rc))


def run_zero_llm(args) -> None:
    """① 确定性实验真值 + ② 主系统（纯标准库，无网络）。"""
    if not args.skip_exp:
        cmd = [PY, HERE / "experiments" / "run_all.py"]
        if args.quick:
            cmd.append("--quick")
        run("① 实验真值", cmd)
    run("② 主系统", [PY, HERE / "system" / "run_system.py"])
    print("\n[main] 完成。产出：output/results.json、paper_system/、charts_system/、logs_system/")


def run_paper(args) -> None:
    """③ LongMemEval 主实验（带日志）→ 表格 → output/。与 logs/ 同属一次运行。"""
    lm = HERE / "experiments" / "longmemeval"
    logs = PKG / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    mode = "--smoke" if args.smoke else "--full"
    env = dict(os.environ)
    env.setdefault("PAPER_LAB", str(PKG))

    # ③ 主实验：--log-run 让 llm.py 在导入期构造 RunLogger，写 logs/{run.json,calls.jsonl}
    run("③ LongMemEval 主实验（%s）" % mode,
        [PY, lm / "run.py", mode, "--log-run"], cwd=lm, env=env)

    # ④ 由逐题记录生成论文表格
    run("④ 生成论文表格", [PY, lm / "analyze.py"], cwd=lm, env=env)

    # ⑤ 整理到 output/ 并编译 PDF
    run("⑤ 整理 output/ 并编译 PDF",
        [PY, HERE / "scripts" / "populate_output.py"],
        env={**env, "PAPER_PKG": str(PKG), "PAPER_PY": PY})

    print("\n[main] 完成。本次运行产出：")
    print("  日志      : logs/run.json、logs/calls.jsonl")
    print("  生成稿    : output/paper.tex、output/paper.pdf")
    print("  结果文件  : output/results.jsonl、output/tables/")
    print("  运行清单  : output/run_manifest.json")


def main() -> None:
    ap = argparse.ArgumentParser(description="Agent 科研流水线统一入口")
    ap.add_argument("--paper-run", action="store_true",
                    help="跑论文主实验（③④⑤）：真实 LLM，写 logs/ 与 output/")
    ap.add_argument("--smoke", action="store_true",
                    help="配合 --paper-run：用 11 题冒烟档（约 10 分钟）")
    ap.add_argument("--quick", action="store_true",
                    help="零 LLM 路径的实验真值用快速档预算")
    ap.add_argument("--skip-exp", action="store_true",
                    help="跳过实验真值层，仅运行主系统")
    args = ap.parse_args()

    if args.paper_run:
        run_paper(args)
    else:
        run_zero_llm(args)
        print("[main] 提示：要产出与论文对应的 logs/ 与 output/，请用")
        print("        python code/main.py --paper-run")


if __name__ == "__main__":
    main()

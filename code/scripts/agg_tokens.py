#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agg_tokens.py —— 聚合引擎侧 LLM 调用流水（resource_report.md 附录 A 的复算命令）。

扫描 JiuwenSwarm 引擎的 llm.log 轮转链，逐行解析 usage，汇总 token 与失败调用数。

日志目录按以下**优先级**定位，任一命中即可，因此可直接在他机复现：
  1. 环境变量 JIUWENSWARM_LOG_DIR（显式指定，最高优先级）
  2. 环境变量 JIUWENSWARM_DATA_DIR + /logs/logs
  3. ~/.jiuwenswarm/logs/logs          （桌面版默认位置）
  4. ~/.jiuwenswarm-instances/*/logs/logs  （实例版位置，取最近修改的一个）

用法：
  python code/scripts/agg_tokens.py
  python code/scripts/agg_tokens.py --dir /path/to/logs/logs
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path


def find_log_dirs() -> list[Path]:
    """按优先级返回候选日志目录（存在的才返回）。"""
    cands: list[Path] = []
    env = os.environ.get("JIUWENSWARM_LOG_DIR")
    if env:
        cands.append(Path(env))
    data = os.environ.get("JIUWENSWARM_DATA_DIR")
    if data:
        cands.append(Path(data) / "logs" / "logs")
    cands.append(Path.home() / ".jiuwenswarm" / "logs" / "logs")
    # 实例版：<home>/.jiuwenswarm-instances/<name>/logs/logs，按 mtime 取最新
    inst_root = Path.home() / ".jiuwenswarm-instances"
    if inst_root.is_dir():
        found = [p for p in inst_root.glob("*/logs/logs") if p.is_dir()]
        found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        cands.extend(found)
    seen, out = set(), []
    for c in cands:
        key = str(c).lower()
        if key in seen:
            continue
        seen.add(key)
        if c.is_dir():
            out.append(c)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="聚合引擎 LLM 调用流水")
    ap.add_argument("--dir", default=None,
                    help="显式指定日志目录（等价于设置 JIUWENSWARM_LOG_DIR）")
    ap.add_argument("--all", action="store_true",
                    help="扫描全部候选目录（默认只扫第一个命中的）")
    args = ap.parse_args()

    if args.dir:
        dirs = [Path(args.dir)]
    else:
        dirs = find_log_dirs()
    if not dirs:
        print("未找到引擎日志目录。请用 --dir 指定，或设置 JIUWENSWARM_LOG_DIR。", file=sys.stderr)
        print("已尝试：JIUWENSWARM_LOG_DIR / JIUWENSWARM_DATA_DIR/logs/logs / "
              "~/.jiuwenswarm/logs/logs / ~/.jiuwenswarm-instances/*/logs/logs", file=sys.stderr)
        return 2
    if not args.all:
        dirs = dirs[:1]

    files: list[str] = []
    for d in dirs:
        files.extend(sorted(glob.glob(str(d / "llm.log*"))))

    tot_pt = tot_ct = calls = errs = 0
    models: dict[str, int] = {}
    for fp in files:
        with open(fp, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "llm_call_end" in line and "usage=" in line:
                    u = re.search(
                        r"usage=CompletionUsage\(completion_tokens=(\d+), prompt_tokens=(\d+)",
                        line)
                    if u:
                        calls += 1
                        tot_ct += int(u.group(1))
                        tot_pt += int(u.group(2))
                    mo = re.search(r"model='([^']+)'", line)
                    if mo:
                        models[mo.group(1)] = models.get(mo.group(1), 0) + 1
                elif "llm_call_error" in line:
                    errs += 1

    print(json.dumps({
        "log_dirs_scanned": [str(d) for d in dirs],
        "files_scanned": len(files),
        "successful_calls": calls,
        "prompt_tokens_total": tot_pt,
        "completion_tokens_total": tot_ct,
        "total_tokens": tot_pt + tot_ct,
        "llm_call_errors": errs,
        "models": models,
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

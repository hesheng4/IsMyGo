#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_submission.py —— 按提交样例结构打包。

样例结构（提交样例说明.md）：
    队伍名称/
    ├── Agentic Reviewer/   ├── paper/   ├── code/   ├── data/
    ├── logs/               ├── output/  ├── docs/
    ├── resource_report.md  └── framework_contribution.md

用法（在包根 IsMyGo/ 下执行）：
    python code/scripts/make_submission.py                 # 默认: 队伍名 IsMyGo, 全量
    python code/scripts/make_submission.py --name 队伍名    # 指定队伍名(zip 内根目录)
    python code/scripts/make_submission.py --no-models     # 排除 models/ (~1.6 GiB)
    python code/scripts/make_submission.py --no-data       # 排除大数据集 (266 MiB)
    python code/scripts/make_submission.py --no-cache      # 排除 LLM/向量缓存 (~760 MiB)

排除项（始终排除）：.git .idea .team .tmp __pycache__ *.pyc .pytest_cache
*.part；被排除的数据/模型/缓存按 code/README.md §3 的命令可重新获取。
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path, PurePosixPath

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PKG = Path(__file__).resolve().parents[2]          # IsMyGo/

ALWAYS_EXCLUDE_DIRS = {".git", ".idea", ".team", ".tmp", "__pycache__", ".pytest_cache"}
ALWAYS_EXCLUDE_SUFFIX = (".pyc", ".part")
OPTIONAL_EXCLUDES = {                             # flag -> 目录前缀(POSIX) 与说明
    "no_models": ("models", "本地模型 (README §3.2 fetch_models.py 可重获)"),
    "no_data": ("data/longmemeval-cleaned", "LongMemEval 数据集 (README §3.2 fetch_data.py 可重获)"),
    "no_cache": ("code/output/longmemeval/cache", "LLM 断点缓存 + bge 向量缓存 (可再生)"),
}
SAMPLE_REQUIRED = [
    "Agentic Reviewer", "paper", "code", "data", "logs", "output", "docs",
    "resource_report.md", "framework_contribution.md",
]


def human(n: int) -> str:
    return "%.1f MiB" % (n / 1048576)


def main() -> int:
    ap = argparse.ArgumentParser(description="按提交样例结构打包 zip")
    ap.add_argument("--name", default="IsMyGo", help="队伍名（zip 文件名与包内根目录名）")
    for flag, (_d, desc) in OPTIONAL_EXCLUDES.items():
        ap.add_argument("--%s" % flag.replace("_", "-"), action="store_true", help="排除 %s" % desc)
    args = ap.parse_args()

    excl_dirs = set(ALWAYS_EXCLUDE_DIRS)
    excl_prefixes = []
    for flag, (d, _desc) in OPTIONAL_EXCLUDES.items():
        if getattr(args, flag):
            if "/" not in d:
                excl_dirs.add(d)                  # 顶层目录整除
            else:
                excl_prefixes.append(d)           # 子目录前缀

    out = PKG.parent / ("%s.zip" % args.name)
    n_files, n_bytes, skipped = 0, 0, 0

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(PKG.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(PKG).as_posix()   # zip 内统一 POSIX 正斜杠
            parts = rel.split("/")
            if any(part in excl_dirs for part in parts[:-1]) or parts[0] in excl_dirs:
                skipped += 1
                continue
            if p.suffix in ALWAYS_EXCLUDE_SUFFIX:
                skipped += 1
                continue
            if any(rel == d or rel.startswith(d + "/") for d in excl_prefixes):
                skipped += 1
                continue
            zf.write(p, arcname="%s/%s" % (args.name, rel))
            n_files += 1
            n_bytes += p.stat().st_size

    print("包内根目录 : %s/" % args.name)
    print("文件数     : %d（跳过 %d 个排除项）" % (n_files, skipped))
    print("原始体积   : %s -> zip: %s" % (human(n_bytes), human(out.stat().st_size)))
    print("输出       : %s" % out)

    # 样例必备成员核验（zip 名均为 POSIX 正斜杠）
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        missing = [m for m in SAMPLE_REQUIRED
                   if not any(n == "%s/%s" % (args.name, m)
                              or n.startswith("%s/%s/" % (args.name, m)) for n in names)]
    if missing:
        print("⚠ 样例必备成员缺失: %s" % ", ".join(missing))
        return 1
    print("样例结构核验: 9 项必备成员全部在包 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())

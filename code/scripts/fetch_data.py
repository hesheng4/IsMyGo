#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_data.py —— 下载复现论文所需的全部外部数据。

论文：When Does Memory Compression Pay Off? A Budget-Controlled Study of
      Memory Policies for LLM Agents on LongMemEval

用法：
    python code/scripts/fetch_data.py                  # 下载全部
    python code/scripts/fetch_data.py --dest data/     # 指定落盘根目录
    python code/scripts/fetch_data.py --check          # 只校验已有文件
    python code/scripts/fetch_data.py --only dataset   # 只下数据集

设计说明：
  * 数据集 264.5 MiB，超过常见提交包体积上限，故**不随包提交**，
    由本脚本按固定 URL + SHA256 校验可重复获取。
  * 脚本对每个目标文件先查本地校验和，已存在且校验通过则跳过（幂等）。
  * 校验和不匹配时报错退出，不接受损坏数据。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

# Windows 控制台默认 GBK，统一 UTF-8 输出，避免中文/符号在重定向或子进程中乱码
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# --------------------------------------------------------------------------- #
# 数据清单：每项 = 目标相对路径、来源、大小、SHA256
# --------------------------------------------------------------------------- #
DATASET_REL = "longmemeval-cleaned/longmemeval_s_cleaned.json"

MANIFEST = {
    "dataset": {
        "rel": DATASET_REL,
        "name": "LongMemEval-S (cleaned release)",
        "source": "ModelScope 数据集 evalscope/longmemeval-cleaned",
        "url": (
            "https://www.modelscope.cn/api/v1/datasets/evalscope/"
            "longmemeval-cleaned/repo?Revision=master"
            "&FilePath=longmemeval_s_cleaned.json"
        ),
        "url_alt": (
            "https://www.modelscope.cn/datasets/evalscope/"
            "longmemeval-cleaned/resolve/master/longmemeval_s_cleaned.json"
        ),
        "git": "https://www.modelscope.cn/datasets/evalscope/longmemeval-cleaned.git",
        "bytes": 277383467,
        "sha256": "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442",
        "md5": "9b009af4084c6207e9d41aa0dcb6506c",
        "used_by": "experiments/longmemeval/*（分层抽样 120 题、haystack 组装、token 预算计数）",
    },
}

# 论文表格/记录由流水生成，不需要外部下载；这里只列出「随包提交」的产物，
# 供 --check 一并核对完整性。
IN_PACKAGE = {
    "output/longmemeval/results.jsonl":
        "主网格逐题记录（6 策略 x 4 预算 x 120 题，含 full-context）",
    "output/longmemeval/results_kv.jsonl": "结构化压缩器 KV 逐题记录",
    "output/longmemeval/results_edu.jsonl": "结构化压缩器 EDU 逐题记录",
    "output/longmemeval/tables/judge_full.json": "全量语义 judge 结果（E4）",
    "output/longmemeval/tables/retrieval_ranking.json": "session 级排名指标（E2）",
    "output/longmemeval/tables/rerank_eval.json": "重排器 + dense 升级判读（E3）",
    "output/longmemeval/tables/struct_eval.json": "结构化压缩器判读（E1）",
    "output/longmemeval/tables/retrieval_diagnosis.json": "gold 召回 / 读取失败定位",
    "output/longmemeval/tables/stats.json": "配对 bootstrap CI + 精确 McNemar",
    "output/results.json": "确定性实验真值（主系统 ①② 层唯一事实基准）",
}


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def human(n: int) -> str:
    return "%.1f MiB" % (n / 1048576)


def download(url: str, dest: Path, expect_bytes: int) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        import ssl
        ctx = ssl.create_default_context()
    except Exception:
        ctx = None
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=1800) as resp, \
                open(tmp, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                blk = resp.read(1 << 20)
                if not blk:
                    break
                out.write(blk)
                done += len(blk)
                if total and done % (20 << 20) < (1 << 20):
                    sys.stdout.write("\r    下载中 %s / %s (%.0f%%)"
                                     % (human(done), human(total), 100.0 * done / total))
                    sys.stdout.flush()
        sys.stdout.write("\r    下载完成 %s%s\n" % (human(tmp.stat().st_size), " " * 30))
    except Exception as exc:
        print("    下载失败: %s: %s" % (type(exc).__name__, exc))
        if tmp.exists():
            tmp.unlink()
        return False
    if expect_bytes and tmp.stat().st_size != expect_bytes:
        print("    大小不符：期望 %d，实得 %d" % (expect_bytes, tmp.stat().st_size))
        tmp.unlink()
        return False
    tmp.replace(dest)
    return True


def check_one(dest: Path, spec: dict) -> bool:
    if not dest.exists():
        print("    [缺失] %s" % dest)
        return False
    size = dest.stat().st_size
    if spec.get("bytes") and size != spec["bytes"]:
        print("    [大小不符] %s：%d != %d" % (dest, size, spec["bytes"]))
        return False
    digest = sha256_of(dest)
    if digest != spec["sha256"]:
        print("    [校验和不符] %s\n      期望 %s\n      实得 %s"
              % (dest, spec["sha256"], digest))
        return False
    print("    [OK] %s  %s  sha256=%s" % (dest.name, human(size), digest[:16] + "..."))
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="下载论文复现所需外部数据")
    here = Path(__file__).resolve()
    default_dest = here.parents[1].parent / "data"          # code/scripts/ -> IsMyGo/data
    ap.add_argument("--dest", default=str(default_dest),
                    help="落盘根目录（默认 IsMyGo/data）")
    ap.add_argument("--check", action="store_true", help="只校验，不下载")
    ap.add_argument("--only", choices=sorted(MANIFEST), default=None,
                    help="只处理指定条目")
    ap.add_argument("--force", action="store_true", help="忽略已有文件，强制重下")
    args = ap.parse_args()

    dest_root = Path(args.dest).resolve()
    print("落盘根目录：%s" % dest_root)
    print("校验清单  ：%d 项外部数据 + %d 项随包产物\n"
          % (len(MANIFEST), len(IN_PACKAGE)))

    keys = [args.only] if args.only else sorted(MANIFEST)
    all_ok = True
    for key in keys:
        spec = MANIFEST[key]
        dest = dest_root / spec["rel"]
        print("[%s] %s" % (key, spec["name"]))
        print("    来源   : %s" % spec["source"])
        print("    大小   : %s" % human(spec["bytes"]))
        print("    SHA256 : %s" % spec["sha256"])
        print("    用途   : %s" % spec["used_by"])
        if not args.check and (args.force or not dest.exists()
                               or not check_one(dest, spec)):
            if dest.exists() and args.force:
                dest.unlink()
            print("    开始下载 ...")
            for url in (spec["url"], spec.get("url_alt")):
                if url and download(url, dest, spec["bytes"]):
                    break
            else:
                print("    全部镜像失败。可改用 git 克隆：")
                print("      git -c http.sslBackend=openssl clone --depth 1 %s" % spec["git"])
                print("      （LFS 文件需额外 git lfs pull；或直接重试本脚本）")
                all_ok = False
                continue
        if not check_one(dest, spec):
            all_ok = False
        print()

    print("随包提交的产物（应由流水生成，此处只核验存在性）：")
    pkg_root = here.parents[1].parent          # IsMyGo/
    for rel, desc in sorted(IN_PACKAGE.items()):
        p = pkg_root / "code" / rel
        ok = p.exists()
        all_ok &= ok
        print("    [%s] %-46s %s" % ("OK" if ok else "缺失", rel, desc))
    print()
    print("=" * 72)
    print("结果：%s" % ("全部就绪" if all_ok else "存在缺失项，见上"))
    print("=" * 72)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

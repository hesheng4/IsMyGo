#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_models.py —— 下载复现消融实验所需的本地编码/重排模型。

用法：
    python code/scripts/fetch_models.py                # 下载全部缺失模型
    python code/scripts/fetch_models.py --check        # 只校验已有模型
    python code/scripts/fetch_models.py --only bge-small   # 只处理指定模型
    python code/scripts/fetch_models.py --force        # 忽略已有文件强制重下

覆盖三个本地模型（与 experiments/longmemeval/common.py:LOCAL_MODELS 同一口径）：
    bge-small      BAAI/bge-small-en-v1.5   dense 检索基线 / hybrid 融合 (Table 12)
    bge-base       BAAI/bge-base-en-v1.5    dense 升级消融腿 (Table 9)
    bge-reranker   BAAI/bge-reranker-base   交叉编码器重排探针 (Table 9)
                  （bge-reranker-base 已随提交包附带 1.1 GiB；本脚本供
                   GitHub 克隆用户 —— models/ 被 .gitignore 排除 —— 补齐用）

设计说明：
  * 与 fetch_data.py 同款：清单驱动、幂等（已存在且非零即跳过）、
    .part 临时文件落盘后改名，失败不留半截文件。
  * 模型仓库文件会随上游更新，不做 SHA256 硬校验；校验口径为
    「必需文件存在 + 非零 + config.json 可解析为 JSON」。
  * 权重文件按 model.safetensors -> pytorch_model.bin 顺序取首个可得。
  * 纯标准库（urllib），不引入 modelscope/huggingface_hub 依赖。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# --------------------------------------------------------------------------- #
# 模型清单
# --------------------------------------------------------------------------- #
# 必需文件: 缺任一则判定模型不完整; weights 按序取首个下载成功的。
_COMMON_FILES = [
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.txt",
]
_WEIGHT_FILES = ["model.safetensors", "pytorch_model.bin"]
# sentence-transformers 结构文件: BAAI 仓库有则下载 (404 容忍, 仅编码器需要)
_ST_FILES = [
    "modules.json",
    "config_sentence_transformers.json",
    "sentence_bert_config.json",
    "1_Pooling/config.json",
]

MANIFEST = {
    "bge-small": {
        "repo": "BAAI/bge-small-en-v1.5",
        "usage": "dense 检索基线 / hybrid 融合 (Table 12 检索器家族消融)",
        "approx": "~130 MiB",
        "files": _COMMON_FILES,
        "st_files": _ST_FILES,
        "shipped": False,
    },
    "bge-base": {
        "repo": "BAAI/bge-base-en-v1.5",
        "usage": "dense 升级消融腿, 隔离编码器效应 (Table 9 重排消融)",
        "approx": "~440 MiB",
        "files": _COMMON_FILES,
        "st_files": _ST_FILES,
        "shipped": False,
    },
    "bge-reranker": {
        "repo": "BAAI/bge-reranker-base",
        "usage": "交叉编码器重排探针 (Table 9); 提交包已附带, GitHub 克隆需补",
        "approx": "~1.1 GiB",
        "files": _COMMON_FILES,
        "st_files": [],
        "shipped": True,
    },
}


def human(n: int) -> str:
    return "%.1f MiB" % (n / 1048576)


def _url(repo: str, fname: str, alt: bool = False) -> str:
    if alt:
        return "https://www.modelscope.cn/%s/resolve/master/%s" % (repo, fname)
    return ("https://www.modelscope.cn/api/v1/models/%s/repo?Revision=master&FilePath=%s"
            % (repo, fname))


def _fetch(url: str, dest: Path) -> bool:
    """下载单个文件到 dest(经 .part), 成功返回 True; 404/网络失败返回 False。"""
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
        if tmp.exists():
            tmp.unlink()
        # 404 等静默返回 False, 由调用方决定是否致命
        detail = str(exc)
        sys.stdout.write("\r    [跳过] %s (%s)%s\n" % (dest.name, detail[:80], " " * 20))
        return False
    tmp.replace(dest)
    return True


def _get_weight(repo: str, model_dir: Path, force: bool) -> bool:
    """按序尝试权重文件, 任一成功即 True。"""
    for wname in _WEIGHT_FILES:
        dest = model_dir / wname
        if dest.is_file() and dest.stat().st_size > 0 and not force:
            print("    [OK] %s (%s, 已存在)" % (wname, human(dest.stat().st_size)))
            return True
        print("    获取权重 %s ..." % wname)
        for alt in (False, True):
            if _fetch(_url(repo, wname, alt), dest):
                return True
        if dest.exists():
            dest.unlink()
    return False


def check_model(key: str, spec: dict, models_root: Path) -> bool:
    """校验: 必需文件存在 + 非零 + config.json 可解析。"""
    model_dir = models_root / key_dir(key)
    problems = []
    for fname in spec["files"]:
        p = model_dir / fname
        if not p.is_file():
            problems.append("缺 %s" % fname)
        elif p.stat().st_size == 0:
            problems.append("%s 为空" % fname)
    if not any((model_dir / w).is_file() and (model_dir / w).stat().st_size > 0
               for w in _WEIGHT_FILES):
        problems.append("缺权重 (model.safetensors / pytorch_model.bin)")
    if (model_dir / "config.json").is_file():
        try:
            json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
        except Exception as exc:
            problems.append("config.json 解析失败: %s" % exc)
    if problems:
        for pr in problems:
            print("    [缺失] %s" % pr)
        return False
    weight = next(w for w in _WEIGHT_FILES
                  if (model_dir / w).is_file() and (model_dir / w).stat().st_size > 0)
    size = sum(f.stat().st_size for f in model_dir.rglob("*") if f.is_file())
    print("    [OK] %s  权重=%s  总计 %s" % (model_dir.name, weight, human(size)))
    return True


def key_dir(key: str) -> str:
    """清单 key -> models/ 下的目录名。"""
    return {"bge-small": "bge-small-en-v1.5",
            "bge-base": "bge-base-en-v1.5",
            "bge-reranker": "bge-reranker-base"}[key]


def main() -> int:
    ap = argparse.ArgumentParser(description="下载消融实验所需的本地 bge 模型")
    here = Path(__file__).resolve()
    default_root = here.parents[1].parent / "models"        # code/scripts/ -> IsMyGo/models
    ap.add_argument("--dest", default=str(default_root), help="模型根目录 (默认 IsMyGo/models)")
    ap.add_argument("--check", action="store_true", help="只校验, 不下载")
    ap.add_argument("--only", choices=sorted(MANIFEST), default=None, help="只处理指定模型")
    ap.add_argument("--force", action="store_true", help="忽略已有文件, 强制重下")
    args = ap.parse_args()

    models_root = Path(args.dest).resolve()
    print("模型根目录：%s" % models_root)
    print("清单：%d 个模型（主表 Table 1-5 不需要任何一个；仅 Table 9/12 消融需要）\n"
          % len(MANIFEST))

    keys = [args.only] if args.only else sorted(MANIFEST)
    all_ok = True
    for key in keys:
        spec = MANIFEST[key]
        model_dir = models_root / key_dir(key)
        note = "已随提交包附带" if spec["shipped"] else "不在包内, 需下载"
        print("[%s] %s (%s)\n    用途: %s\n    体积: %s (%s)"
              % (key, spec["repo"], note, spec["usage"], spec["approx"], note))

        if args.check:
            all_ok &= check_model(key, spec, models_root)
            print()
            continue

        # 下载: 必需小文件 -> sentence-transformers 结构文件(可选) -> 权重
        for fname in spec["files"]:
            dest = model_dir / fname
            if dest.is_file() and dest.stat().st_size > 0 and not args.force:
                continue
            print("    获取 %s ..." % fname)
            for alt in (False, True):
                if _fetch(_url(spec["repo"], fname, alt), dest):
                    break
            else:
                print("    [致命] 必需文件 %s 下载失败" % fname)
                all_ok = False
                break
        for fname in spec.get("st_files", []):          # 可选: 404 容忍
            dest = model_dir / fname
            if dest.is_file() and dest.stat().st_size > 0 and not args.force:
                continue
            print("    获取 (可选) %s ..." % fname)
            for alt in (False, True):
                if _fetch(_url(spec["repo"], fname, alt), dest):
                    break
        if not _get_weight(spec["repo"], model_dir, args.force):
            print("    [致命] 权重文件全部下载失败")
            all_ok = False
        all_ok &= check_model(key, spec, models_root)
        print()

    print("=" * 72)
    print("结果：%s" % ("全部就绪" if all_ok else "存在缺失项, 见上"))
    print("=" * 72)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

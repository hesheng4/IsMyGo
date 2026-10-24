# -*- coding: utf-8 -*-
"""D3 全量复现性对账: results.jsonl 逐数核对原始 cache.

两层验证 (2026-08-24, Addendum C 后置的 #6):
  1. 指标自洽: 每行记录的 em/relaxed_em/f1 用 score.py 从 (pred, gold)
     确定性重算, 与落盘值逐一比对 —— 验证零转录误差。
  2. pred 溯源: 每行按答题缓存 key 规则定位 cache/answers*/ 下的原始
     调用记录, 比对 pred 文本 (与 usage token) —— 验证结果文件源自
     真实调用存证, 非手工编造。

key 规则 (与 llm.py::_cache_path / run.py / rerank_eval.py / structure.py 一致):
  主网格 + E3 重排: cache/answers/<sha1("answer:v2:{policy}|{budget}|{qid}")>.json
  m47 跨读者:       同目录, ns = "answer:v2-GLM-4.7-Flash"
  E1 KV/EDU:        cache/answers_struct/{kv|edu}/<sha1("answer:v2:struct:{v}|{b}|{qid}")>.json
  空 pred 且带 api_error (contentFilter 拒答/投递失败) 跳过文本比对, 单独计数。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from score import em, relaxed_em, token_f1  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
CACHE = OUT / "cache"
MODEL_ALT = "GLM-4.7-Flash"

n_metric = n_metric_bad = 0
n_src = n_src_bad = n_src_miss = 0
n_empty_api = 0
miss_bucket: dict[str, int] = {}
bad_examples: list[str] = []

FILES = [OUT / "results.jsonl", OUT / "results_kv.jsonl", OUT / "results_edu.jsonl"]


def _cache_json(base: Path, key: str) -> dict | None:
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    p = base / f"{h}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


for path in FILES:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        pol = r["policy"]
        pred, gold = r["pred"], r["gold"]

        # ---- 1. 指标自洽 ----
        m_em, m_rem, m_f1 = em(pred, gold), relaxed_em(pred, gold), token_f1(pred, gold)
        n_metric += 1
        if (abs(m_em - r["em"]) > 1e-9 or abs(m_rem - r["relaxed_em"]) > 1e-9
                or abs(m_f1 - r["f1"]) > 1e-9):
            n_metric_bad += 1
            if len(bad_examples) < 8:
                bad_examples.append(
                    f"指标不符 {pol}@{r['budget']} {r['question_id'][:10]}: "
                    f"存({r['em']:.3f},{r['relaxed_em']:.3f},{r['f1']:.3f}) "
                    f"算({m_em:.3f},{m_rem:.3f},{m_f1:.3f})")

        # ---- 2. pred 溯源 ----
        if not pred.strip() and r.get("api_error"):
            n_empty_api += 1  # 拒答/失败记录: api_error 存证, 不比对文本
            continue
        if pol.startswith("compression@") and pol.split("@")[1] in ("kv", "edu"):
            v = pol.split("@")[1]
            cached = _cache_json(CACHE / "answers_struct" / v,
                                 f"answer:v2:struct:{v}|{r['budget']}|{r['question_id']}")
        else:
            ns = f"answer:v2-{MODEL_ALT}" if pol.endswith("@m47") else "answer:v2"
            cached = _cache_json(CACHE / "answers",
                                 f"{ns}:{pol}|{r['budget']}|{r['question_id']}")
        if cached is None:
            n_src_miss += 1
            # 归因: 空 pred 无 cache = 客户端层失败未落缓存 (旧记录无 api_error 字段,
            # Addendum A/B 的 429 风暴 84 条 + 主网格 contentFilter 62 条);
            # 非空 pred 无 cache = 需查 usage 痕迹 (真实调用但 cache 文件丢失)
            if not pred.strip():
                bucket = "empty_pred"
            elif r.get("prompt_tokens", 0) > 0 or r.get("e2e_ms", 0) > 0:
                bucket = "nonempty_with_usage"  # 真实调用痕迹, cache 文件丢失
            else:
                bucket = "nonempty_no_usage"  # 真问题
            miss_bucket[f"{pol.split('@')[0]}|{bucket}"] = \
                miss_bucket.get(f"{pol.split('@')[0]}|{bucket}", 0) + 1
            if bucket == "nonempty_no_usage" and len(bad_examples) < 8:
                bad_examples.append(
                    f"cache 缺失(非空 pred 且无 usage!) {pol}@{r['budget']} "
                    f"{r['question_id'][:10]}")
            continue
        n_src += 1
        if cached.get("text", "") != pred:
            n_src_bad += 1
            if len(bad_examples) < 8:
                bad_examples.append(
                    f"pred 不符 {pol}@{r['budget']} {r['question_id'][:10]}: "
                    f"jsonl={pred[:30]!r} cache={cached.get('text','')[:30]!r}")

print(f"指标自洽: {n_metric - n_metric_bad}/{n_metric} 通过"
      f"{'  ✗ 不符 ' + str(n_metric_bad) if n_metric_bad else ''}")
print(f"pred 溯源: {n_src - n_src_bad}/{n_src} 文本一致"
      f"{'  ✗ 不符 ' + str(n_src_bad) if n_src_bad else ''}"
      f"  (cache 缺失 {n_src_miss}, 空 pred+api_error 存证 {n_empty_api})")
print("cache 缺失归因:")
for k in sorted(miss_bucket):
    print(f"  {k}: {miss_bucket[k]}")
for b in bad_examples:
    print("  ", b)
n_miss_bad = sum(v for k, v in miss_bucket.items()
                 if k.endswith("nonempty_no_usage"))
n_miss_usage = sum(v for k, v in miss_bucket.items()
                   if k.endswith("nonempty_with_usage"))
ok = (n_metric_bad == 0 and n_src_bad == 0 and n_miss_bad == 0)
verdict = ("PASS — results.jsonl 与原始 cache 完全一致" if ok and n_miss_usage == 0
           else f"PASS(带披露) — 指标与文本 100% 自洽; {n_miss_usage} 条"
                "真实调用 (有 usage 痕迹) 的 cache 文件丢失, 单列披露" if ok else "FAIL")
print("D3 对账结论:", verdict)

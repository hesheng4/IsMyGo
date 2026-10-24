# -*- coding: utf-8 -*-
"""匹配对分析 (审稿意见 #1 / R2-4): full-context 完成子集 (n=36) 上,
所有策略限定到相同题目集的 relaxed EM 对比 + 选择偏差诊断 + 配对统计。
v2: 新增 paired bootstrap 95% CI 与精确 McNemar (复用 score.py, 零新调用)。
只读 results.jsonl, 与 analyze.py 同口径 (分层 120 题 + 完成子集判定)。"""
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import load_questions  # noqa: E402
from score import paired_bootstrap, mcnemar_exact  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
BUDGETS = [512, 1024, 2048, 4096]
POLICIES = ["sliding_window", "retrieval", "retrieval_recency",
            "compression", "hierarchical"]

sample = {q.question_id for q in load_questions()}
rows = [json.loads(l) for l in (OUT / "results.jsonl").read_text(
    encoding="utf-8").splitlines() if l.strip()]
rows = [r for r in rows if r["question_id"] in sample]

fc = [r for r in rows if r["policy"] == "full_context"]
done_ids = sorted({r["question_id"] for r in fc
                   if r["pred"].strip() or r.get("prompt_tokens", 0) > 0})
fc_score = {r["question_id"]: r.get("relaxed_em", 0.0) for r in fc
            if r["question_id"] in set(done_ids)}
print(f"matched n = {len(done_ids)}")

# ---- 1) 逐策略×预算: 点估计 + 配对统计 (fc - policy) ----
print(f"\n{'policy':18s} {'B':>5s} {'fc':>6s} {'pol':>6s} {'delta':>7s} "
      f"{'CI95':>17s} {'p_mcn':>6s}")
cell_mean = {}
for pol in POLICIES:
    for b in BUDGETS:
        d = {r["question_id"]: r.get("relaxed_em", 0.0)
             for r in rows if r["policy"] == pol and r["budget"] == b}
        a = [fc_score[q] for q in done_ids]
        bb = [d.get(q, 0.0) for q in done_ids]
        (ma, mb, _), (lo, hi) = paired_bootstrap(a, bb)
        mc = mcnemar_exact(a, bb)
        cell_mean[(pol, b)] = mb
        print(f"{pol:18s} {b:5d} {ma:6.3f} {mb:6.3f} {ma-mb:+7.3f} "
              f"[{lo:+.3f},{hi:+.3f}] {mc['p_value']:6.3f}")

# ---- 2) 每预算最强受限策略 vs full-context 的配对统计 ----
print("\n--- strongest constrained per budget (matched subset) ---")
for b in BUDGETS:
    best_pol = max(POLICIES, key=lambda p: cell_mean[(p, b)])
    d = {r["question_id"]: r.get("relaxed_em", 0.0)
         for r in rows if r["policy"] == best_pol and r["budget"] == b}
    a = [fc_score[q] for q in done_ids]
    bb = [d.get(q, 0.0) for q in done_ids]
    (ma, mb, _), (lo, hi) = paired_bootstrap(a, bb)
    mc = mcnemar_exact(a, bb)
    print(f"B={b}: {best_pol} pol={mb:.3f} fc={ma:.3f} "
          f"delta={ma-mb:+.3f} CI=[{lo:+.3f},{hi:+.3f}] p={mc['p_value']:.3f}")

# ---- 3) 选择偏差诊断 (与 v1 相同) ----
def comp(ids):
    c = defaultdict(int)
    for r in fc:
        if r["question_id"] in ids:
            c[r["question_type"]] += 1
    return dict(sorted(c.items()))


empty_ids = {r["question_id"] for r in fc} - set(done_ids)
print("\ndone types  ", comp(set(done_ids)))
print("empty types ", comp(empty_ids))
diff_proxy = {r["question_id"]: r.get("relaxed_em", 0.0)
              for r in rows if r["policy"] == "retrieval" and r["budget"] == 4096}
dm = sum(v for k, v in diff_proxy.items() if k in set(done_ids)) / len(done_ids)
de = sum(v for k, v in diff_proxy.items() if k in empty_ids) / len(empty_ids)
print(f"difficulty proxy (retrieval@4096): done={dm:.4f} empty={de:.4f}")

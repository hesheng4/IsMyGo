# -*- coding: utf-8 -*-
"""写入/读取成本 break-even 重算 (审稿意见 #5): 从 results.jsonl 逐字计算
压缩策略的一次性写入成本需要多少次读取查询才能摊销。
只读已发布记录, 不做任何新调用。口径与 analyze.py 一致。"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import load_questions  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"

sample = {q.question_id for q in load_questions()}
rows = [json.loads(l) for l in (OUT / "results.jsonl").read_text(
    encoding="utf-8").splitlines() if l.strip()]
rows = [r for r in rows if r["question_id"] in sample]

# ---- 写入侧 (论文 Limitations 9 已披露的常量, 逐字对齐) ----
WRITE_TOKENS = 14_000_000        # 5,728 会话摘要总成本 (14.0M, 论文已载)
N_SESSIONS = 5_728

# ---- 读取侧: 每题 prompt_tokens 均值 (从记录重算, 不手抄) ----
def mean_pt(pol, budget=None):
    xs = [r["prompt_tokens"] for r in rows
          if r["policy"] == pol and r["budget"] == budget
          and r.get("prompt_tokens")]
    return sum(xs) / len(xs) if xs else 0.0, len(xs)

fc_pt, n_fc = mean_pt("full_context")                       # 完成调用
comp_pt, n_c = mean_pt("compression", 4096)                 # 压缩@4096
ret_pt, n_r = mean_pt("retrieval", 4096)                    # 检索@4096

print(f"full-context completed  : n={n_fc}, mean prompt_tokens={fc_pt:,.0f}")
print(f"compression@4096        : n={n_c}, mean prompt_tokens={comp_pt:,.0f}")
print(f"retrieval@4096          : n={n_r}, mean prompt_tokens={ret_pt:,.0f}")

# ---- break-even: 写入成本 / 每题读取节省 ----
saving_vs_fc = fc_pt - comp_pt
saving_vs_ret = ret_pt - comp_pt
be_fc = WRITE_TOKENS / saving_vs_fc
be_ret = WRITE_TOKENS / saving_vs_ret if saving_vs_ret > 0 else float("inf")

print(f"\nper-query saving vs full-context : {saving_vs_fc:,.0f} tokens")
print(f"per-query saving vs retrieval@4096: {saving_vs_ret:,.0f} tokens")
print(f"break-even queries vs full-context : {be_fc:,.0f}")
print(f"break-even queries vs retrieval    : {be_ret:,.1f}")

# 分预算的压缩读取成本 (正文引用区间)
for b in (512, 1024, 2048, 4096):
    pt, n = mean_pt("compression", b)
    print(f"compression@{b:<5}: mean prompt_tokens={pt:,.0f} (n={n})")

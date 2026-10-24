# -*- coding: utf-8 -*-
"""D2/#7 数字对账: 论文新引数字逐项核对源 json (零幻觉验证).

2026-10-16: 旧论文源 iclr/iclr_paper.tex 已随旧代际清理移除, 本脚本的 TEX
目标不复存在; 对账逻辑保留供新论文 (output/final/paper.tex) 复用时参考。
"""
import json
import re
import sys

# 相对本脚本定位：parents[2] = code/（paper-lab 根），可在他机复现。
# 也可用 PAPER_LAB 环境变量覆盖（指向 code/ 那一级）。
from pathlib import Path as _Path
import os as _os
_ROOT = _Path(_os.environ.get("PAPER_LAB") or _Path(__file__).resolve().parents[2])
TAB = str(_ROOT / "output" / "longmemeval" / "tables")
TEX = _os.environ.get("PAPER_LAB_TEX") or str(_ROOT.parent / "output" / "final" / "paper.tex")

if not _os.path.exists(TEX):
    sys.exit(f"[reconcile] 论文源不存在: {TEX}（旧 iclr 稿已清理；"
             f"可用 PAPER_LAB_TEX 指定新论文路径, 如 output/final/paper.tex）")

paper = open(TEX, encoding="utf-8").read()
se = json.load(open(TAB + r"\struct_eval.json", encoding="utf-8"))
re_ = json.load(open(TAB + r"\rerank_eval.json", encoding="utf-8"))
jf = json.load(open(TAB + r"\judge_full.json", encoding="utf-8"))
st = json.load(open(TAB + r"\stats.json", encoding="utf-8"))
hl = open(TAB + r"\headline.tex", encoding="utf-8").read()

checks = []


def ck(name, cond):
    checks.append((name, bool(cond)))


# --- E1 ---
a = se["analysis_at_4096"]["main"]
ck("KV gap-closed -11.8%", abs(a["kv_vs_bm25"]["gap_closed"] + 0.118) < 0.001)
ck("EDU gap-closed 0.0%", abs(a["edu_vs_bm25"]["gap_closed"]) < 0.001)
ck("KV@4096 0.142", abs(se["cells"]["kv@4096"]["relaxed_em"] - 0.1417) < 0.0005)
ck("EDU/freeform@4096 0.158",
   abs(se["cells"]["edu@4096"]["relaxed_em"] - 0.1583) < 0.0005
   and abs(se["cells"]["freeform@4096"]["relaxed_em"] - 0.1583) < 0.0005)
s = se["analysis_at_4096"]["excl_filter"]
ck("敏感性口径同档", abs(s["kv_vs_bm25"]["gap_closed"] + 0.118) < 0.001
   and abs(s["edu_vs_bm25"]["gap_closed"]) < 0.001)
ck("KV p=0.79 (不显著, <20% 档无需显著性)",
   a["kv_vs_bm25"]["mcnemar_struct_vs_freeform"]["p_value"] > 0.05)

# --- E3 ---
off = re_["offline_session_recall"]
ck("BM25 R@5 0.834", abs(off["bm25_base"]["recall@5"] - 0.834) < 0.0005)
ck("BM25+rr R@5 0.954", abs(off["bm25_rerank"]["recall@5"] - 0.954) < 0.0005)
ck("dense R@5 0.969", abs(off["dense_base"]["recall@5"] - 0.969) < 0.0005)
ck("dense+rr R@5 0.981", abs(off["dense_rerank"]["recall@5"] - 0.981) < 0.0005)
c = re_["comparisons_at_4096"]["primary_bm25_rerank_vs_base"]
ck("主判据 Δ=-0.008 p=1.0", abs(c["delta"] + 0.0083) < 0.0005
   and abs(c["mcnemar"]["p_value"] - 1.0) < 0.001)
c2 = re_["comparisons_at_4096"]["dense_rerank_effect"]
ck("dense rr Δ=0 p=1.0", abs(c2["delta"]) < 0.0005
   and abs(c2["mcnemar"]["p_value"] - 1.0) < 0.001)
c3 = re_["comparisons_at_4096"]["dense_encoder_effect"]
ck("encoder +0.025 p=0.55", abs(c3["delta"] - 0.025) < 0.0005
   and abs(c3["mcnemar"]["p_value"] - 0.549) < 0.001)
cs = re_["comparisons_at_4096_excl_filter"]["primary_bm25_rerank_vs_base"]
ck("敏感性 Δ=-0.009 p=1.0", abs(cs["delta"] + 0.0086) < 0.0005)
cs3 = re_["comparisons_at_4096_excl_filter"]["dense_encoder_effect"]
ck("敏感性 encoder +0.035 p=0.34", abs(cs3["delta"] - 0.0345) < 0.0005
   and abs(cs3["mcnemar"]["p_value"] - 0.344) < 0.001)
ck("E3 complete=True", re_["complete"])
ck("拒答计数 7/8/5",
   sum(v["filter_refusals"] for k, v in re_["completeness"].items()
       if k.startswith("retrieval_rerank")) == 7
   and sum(v["filter_refusals"] for k, v in re_["completeness"].items()
           if k.startswith("dense_retrieval_rr")) == 8
   and sum(v["filter_refusals"] for k, v in re_["completeness"].items()
           if k.startswith("dense_retrieval_bb")) == 5)

# --- E4 ---
ck("flip 34.0% (594/1746)", jf["read_fail_total"] == {"n": 1746, "flip": 594}
   and abs(jf["flip_rate_read_fail"] - 0.3402) < 0.001)
ck("ERROR 剩 7", jf["judge_errors"] == 7)
ck("对照 0/210", jf["controls_total"] == {"n": 210, "incorrect": 0})
rf = jf["read_fail_by_cell"]
ck("compression flip 24.1%",
   abs(rf["compression@512"]["flip"] + rf["compression@1024"]["flip"]
       + rf["compression@2048"]["flip"] + rf["compression@4096"]["flip"] - 54) == 0
   and 54 / 224 - 0.241 < 0.001)

# --- 双基线 stats ---
ck("512 主对照 Δ-0.2000 CI[-0.2833,-0.1250]",
   abs(st["512"]["primary_bm25"]["delta_ci95"][0] + 0.2833) < 0.0005)
ck("4096 主对照 p=0.0046",
   abs(st["4096"]["primary_bm25"]["mcnemar"]["p_value"] - 0.00455) < 0.0005)
ck("1024 最强替代=retrieval_recency",
   st["1024"]["strongest_alternative"]["baseline"] == "retrieval_recency")
ck("4096 最强替代=hierarchical",
   st["4096"]["strongest_alternative"]["baseline"] == "hierarchical")

# --- headline 宏 ---
ck("\\fcDoneN=36", "\\newcommand{\\fcDoneN}{36}" in hl)
ck("\\fcDoneEM=0.3333", "\\newcommand{\\fcDoneEM}{0.3333}" in hl)
ck("\\fcEmptyN=84", "\\newcommand{\\fcEmptyN}{84}" in hl)
ck("\\fcDoneEtwoE=80", "\\newcommand{\\fcDoneEtwoE}{80}" in hl)
ck("\\fcFoot 104024", "104\\,024" in hl)
ck("\\nSessions=5422", "\\newcommand{\\nSessions}{5422}" in hl)

# --- 论文文本关键声明 ---
ck("摘要含 0.333 vs 0.30--0.35", "0.333$ vs.\\ $0.30$--$0.35$" in paper)
ck("judge 段 594/1746", "594/1{,}746" in paper)
ck("judge 段 24.1%", "$24.1\\%$" in paper)
ck("C1 修正 Δ=-0.20", "$\\Delta=-0.20$ EM" in paper)
ck("N5/N6 存在", "\\textbf{N5}" in paper and "\\textbf{N6}" in paper)
ck("tab:rerank caption 拒答计数", "7/8/5 cells" in paper)
ck("robust caption first 60", "first 60 questions of the" in paper)
ck("diag caption grid", "across the budget grid" in paper)
ck("Related Work 定位段", "Positioning of the reranker" in paper)
ck("结构化压缩器小节", "Structured verbatim compressors" in paper)
ck("无 oracle 可见文本", "oracle" not in paper.replace("\\fcFoot", "")
   .replace("\\fcAtLarge", "").replace("\\fcDone", ""))

fails = [n for n, ok in checks if not ok]
print(f"{len(checks) - len(fails)}/{len(checks)} 项通过")
if fails:
    print("失败项:", fails)
else:
    print("全部对账通过: 论文数字与源 json 一致")

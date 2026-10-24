# -*- coding: utf-8 -*-
"""修订轮新表 (ANALYSIS_PROTOCOL.md §3/§5.1/§5.2, 评审回应 Q1/Q3/Q4).

从已有判读 json 生成论文表片段 (逐字溯源, 不重算):
  tables/struct_compressor.tex  E1 KV/EDU 结构化压缩器 (D2 判读已落 struct_eval.json)
  tables/rerank_eval.tex        E3 重排器 + dense 升级 (rerank_eval.json)
判读数字 (gap-closed / McNemar / Recall@k) 均取自对应 json, 论文正文引用同源。
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "output" / "longmemeval"
TAB = OUT / "tables"


def _cells(key: str) -> dict:
    se = json.loads((TAB / "struct_eval.json").read_text(encoding="utf-8"))
    return se


def struct_table() -> None:
    se = json.loads((TAB / "struct_eval.json").read_text(encoding="utf-8"))
    cells = se["cells"]

    def em(name: str, b: int) -> str:
        c = cells.get(f"{name}@{b}")
        return f"{c['relaxed_em']:.3f}" if c else "--"

    def gc(caliber: str, which: str) -> str:
        v = se["analysis_at_4096"][caliber][which]["gap_closed"]
        if v is None:
            return "--"
        return f"{v:+.1%}".replace("-", "$-$").replace("%", r"\%")

    rows = [
        ("free-form digest (w60)", "freeform", None),
        ("KV extract (verbatim)", "kv", "kv_vs_bm25"),
        ("EDU extract (verbatim)", "edu", "edu_vs_bm25"),
    ]
    lines = [r"\begin{tabular}{lccccc}", r"\toprule",
             r"Compressor & $B{=}512$ & $B{=}1024$ & $B{=}2048$ & $B{=}4096$ "
             r"& gap-closed@$4096$ \\",
             r"\midrule"]
    for label, name, which in rows:
        gc_txt = gc("main", which) if which else "--"
        lines.append(
            f"{label} & {em(name,512)} & {em(name,1024)} & {em(name,2048)} "
            f"& {em(name,4096)} & {gc_txt} \\\\")
    lines.append(r"\midrule")
    for label, name in (("retrieval (BM25)", "retrieval"),
                        ("hierarchical (3-tier)", "hierarchical")):
        lines.append(
            f"\\textit{{{label}}} & {em(name,512)} & {em(name,1024)} "
            f"& {em(name,2048)} & {em(name,4096)} & -- \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TAB / "struct_compressor.tex").write_text("\n".join(lines),
                                               encoding="utf-8")
    print("written struct_compressor.tex")


def rerank_table() -> None:
    re_ = json.loads((TAB / "rerank_eval.json").read_text(encoding="utf-8"))
    off = re_["offline_session_recall"]
    cmp4096 = re_["comparisons_at_4096"]

    def p(name):
        return f"{cmp4096[name]['mcnemar']['p_value']:.3f}"

    def d(name):
        return f"{cmp4096[name]['delta']:+.3f}".replace("-", "$-$")

    def online(pol):
        return f"{re_['cells'][f'{pol}@4096']['relaxed_em']:.3f}"

    def r5(key):
        return f"{off[key]['recall@5']:.3f}"

    lines = [r"\begin{tabular}{lcccc}", r"\toprule",
             r"Ranker & offline R@5 & online EM$_{\text{rel}}$@4096 "
             r"& $\Delta$ & McNemar $p$ \\",
             r"\midrule",
             f"BM25 & {r5('bm25_base')} & {online('retrieval')} & -- & -- \\\\",
             f"BM25 + reranker & {r5('bm25_rerank')} & {online('retrieval_rerank')} "
             f"& {d('primary_bm25_rerank_vs_base')} & {p('primary_bm25_rerank_vs_base')} \\\\",
             r"\midrule",
             f"dense (bge-small) & -- & {online('dense_retrieval')} & -- & -- \\\\",
             f"dense (bge-base) & {r5('dense_base')} & {online('dense_retrieval_bb')} "
             f"& {d('dense_encoder_effect')} & {p('dense_encoder_effect')} \\\\",
             f"dense (bge-base) + reranker & {r5('dense_rerank')} & {online('dense_retrieval_rr')} "
             f"& {d('dense_rerank_effect')} & {p('dense_rerank_effect')} \\\\",
             r"\bottomrule", r"\end{tabular}"]
    (TAB / "rerank_eval.tex").write_text("\n".join(lines), encoding="utf-8")
    print("written rerank_eval.tex")


if __name__ == "__main__":
    struct_table()
    rerank_table()

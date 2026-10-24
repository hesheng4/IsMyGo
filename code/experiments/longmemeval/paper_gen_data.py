# -*- coding: utf-8 -*-
"""确定性论文生成: 由 final_paper.md + results.jsonl 直接装配 iclr_paper.tex (零 LLM)。

数据纪律: 正文逐字来自 7 页定稿 final_paper.md (已通过数字审计) + tables/*.tex;
附录大表由 results.jsonl 程序化聚合; 生成后再次做小数白名单审计。
页数控制: 机械调参 (\\linespread 步进) 直到恰为 15 页。

用法: python paper_gen_data.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE = HERE.parents[1]
REPO = CODE.parent
FINAL7 = REPO / "output" / "final"
LM = CODE / "output" / "longmemeval"
TABLES = LM / "tables"
ICLR = CODE / "iclr"
AUDIT_OUT = CODE / "output" / "final_15p"

TARGET = 15
BANNED_TABLES = {"robustness_m53.tex", "robustness_model.tex", "matched_analysis.tex"}

CHARMAP = {
    "×": r"$\times$", "≤": r"$\le$", "≥": r"$\ge$", "→": r"$\rightarrow$",
    "²": r"$^2$", "³": r"$^3$", "Δ": r"$\Delta$", "…": r"\ldots",
    "†": r"\textdagger{}", "‡": r"\textddagger{}", "§": r"\S{}",
    "−": "-", "–": "--", "—": "---", "“": "``", "”": "''",
    "‘": "`", "’": "'", "~": r"\textasciitilde{}", "±": r"$\pm$",
}


def whitelist() -> set[str]:
    wl: set[str] = set()
    corpus = (FINAL7 / "final_paper.md").read_text(encoding="utf-8")
    for p in TABLES.glob("*.tex"):
        if p.name not in BANNED_TABLES:
            corpus += "\n" + p.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"\d+\.\d+", corpus):
        wl.add(m.group(0))
    return wl


def grid_values() -> set[str]:
    """附录全格表程序化聚合出的小数 (合法派生: results.jsonl 直算)。"""
    agg: dict[tuple, dict] = {}
    for line in (LM / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        k = (r["policy"], r["budget"])
        a = agg.setdefault(k, {"n": 0, "em": 0.0, "rel": 0.0, "f1": 0.0,
                               "tok": 0.0, "acc": 0.0, "e2e": 0.0})
        a["n"] += 1
        for key, src in (("em", "em"), ("rel", "relaxed_em"), ("f1", "f1"),
                         ("tok", "memory_footprint_tokens"), ("acc", "access_ms"),
                         ("e2e", "e2e_ms")):
            a[key] += float(r[src])
    vals: set[str] = set()
    for a in agg.values():
        n = a["n"]
        vals.add(f"{a['em']/n:.4f}"); vals.add(f"{a['rel']/n:.4f}")
        vals.add(f"{a['f1']/n:.4f}"); vals.add(f"{a['acc']/n:.1f}")
        vals.add(f"{a['e2e']/n:.2f}")
    return vals


def audit(text: str, wl: set[str]) -> list[str]:
    bad = []
    for m in re.finditer(r"(?<![\w.])-?(\d+\.\d+)", text):
        if m.group(1) not in wl:
            bad.append(m.group(1))
    return sorted(set(bad))


# --------------------------------------------------------------------------- #
# inline 转换
# --------------------------------------------------------------------------- #
def inline(s: str) -> str:
    # 1) 提取行内代码与数学, 占位保护
    codes: list[str] = []
    def _code(m):
        codes.append(m.group(1))
        return f"\x00{len(codes)-1}\x01"
    s = re.sub(r"`([^`]+)`", _code, s)
    maths: list[str] = []
    def _math(m):
        maths.append(m.group(1))
        return f"\x02{len(maths)-1}\x03"
    s = re.sub(r"\$([^$]+)\$", _math, s)
    # 2) 转义 LaTeX 特殊字符
    s = s.replace("\\", r"\textbackslash{}")
    for ch, rep in (("&", r"\&"), ("%", r"\%"), ("#", r"\#"), ("_", r"\_"),
                    ("{", r"\{"), ("}", r"\}")):
        s = s.replace(ch, rep)
    # 3) 特殊符号映射
    for ch, rep in CHARMAP.items():
        s = s.replace(ch, rep)
    # 4) 强调与行内格式
    s = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\\textit{\1}", s)
    # 5) 还原占位
    def _code_back(m):
        c = codes[int(m.group(1))]
        c = c.replace("\\", r"\textbackslash{}")
        for ch, rep in (("&", r"\&"), ("%", r"\%"), ("#", r"\#"), ("_", r"\_"),
                        ("{", r"\{"), ("}", r"\}")):
            c = c.replace(ch, rep)
        return r"\texttt{" + c + "}"
    s = re.sub(r"\x00(\d+)\x01", _code_back, s)
    def _math_back(m):
        return r"\(" + maths[int(m.group(1))] + r"\)"
    s = re.sub(r"\x02(\d+)\x03", _math_back, s)
    return s


def md_table_to_tex(lines: list[str]) -> str:
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")]
            for ln in lines if not re.match(r"^\s*\|[\s:|-]+\|\s*$", ln)]
    if not rows:
        return ""
    ncol = len(rows[0])
    aligns = []
    sep = next((ln for ln in lines if re.match(r"^\s*\|[\s:|-]+\|\s*$", ln)), "")
    for cell in [c.strip() for c in sep.strip().strip("|").split("|")]:
        l, r = cell.startswith(":"), cell.endswith(":")
        aligns.append("c" if (l and r) else ("r" if r else "l"))
    aligns += ["l"] * (ncol - len(aligns))
    out = ["\\begin{tabular}{" + "".join(aligns[:ncol]) + "}", "\\toprule"]
    for i, row in enumerate(rows):
        cells = [inline(c) for c in row] + [""] * (ncol - len(row))
        out.append(" & ".join(cells[:ncol]) + r" \\")
        if i == 0:
            out.append("\\midrule")
    out += ["\\bottomrule", "\\end{tabular}"]
    return "\n".join(out)


def md_to_tex(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i, title = 0, ""
    mode = "body"  # body | refs
    while i < len(lines):
        ln = lines[i]
        if i == 0 and ln.startswith("# "):
            title = ln[2:].strip()
            i += 1
            continue
        if ln.startswith("## References"):
            out.append("\\section*{References}")
            mode = "refs"
            i += 1
            continue
        if ln.startswith("## "):
            mode = "body"
            out.append("\\section{" + inline(ln[3:].strip()) + "}")
            i += 1
            continue
        if ln.startswith("### "):
            out.append("\\subsection{" + inline(ln[4:].strip()) + "}")
            i += 1
            continue
        if re.match(r"^\s*---\s*$", ln):
            i += 1
            continue
        if ln.startswith("|"):
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                block.append(lines[i])
                i += 1
            pre = out.pop() if out and out[-1].startswith("\\textbf{Table") else None
            if pre:
                out.append(pre.replace("\\textbf{", "\\paragraph{").rstrip("}") + "}")
            out.append("\\begin{center}\\small")
            out.append(md_table_to_tex(block))
            out.append("\\end{center}")
            continue
        if ln.startswith("- "):
            out.append("\\begin{itemize}")
            while i < len(lines) and lines[i].startswith("- "):
                item = inline(lines[i][2:].strip())
                if mode == "refs":
                    out.append("\\item[] " + item)
                else:
                    out.append("\\item " + item)
                i += 1
            out.append("\\end{itemize}")
            continue
        if ln.startswith("> "):
            out.append("\\begin{quote}" + inline(ln[2:].strip()) + "\\end{quote}")
            i += 1
            continue
        if ln.strip():
            if mode == "refs":
                out.append("\\noindent\\hangindent=1.5em " + inline(ln.strip()) + "\\par")
            else:
                out.append(inline(ln.strip()) + "\n")
        i += 1
    return title, "\n".join(out)


def full_grid_tex() -> str:
    agg: dict[tuple, dict] = {}
    for line in (LM / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        k = (r["policy"], r["budget"])
        a = agg.setdefault(k, {"n": 0, "em": 0.0, "rel": 0.0, "f1": 0.0,
                               "tok": 0.0, "acc": 0.0, "e2e": 0.0})
        a["n"] += 1
        a["em"] += float(r["em"]); a["rel"] += float(r["relaxed_em"])
        a["f1"] += float(r["f1"]); a["tok"] += float(r["memory_footprint_tokens"])
        a["acc"] += float(r["access_ms"]); a["e2e"] += float(r["e2e_ms"])
    order = {"full_context": 0, "sliding_window": 1, "retrieval": 2,
             "retrieval_recency": 3, "compression": 4, "hierarchical": 5}
    rows = []
    for (pol, bud), a in sorted(agg.items(), key=lambda kv: (order.get(kv[0][0], 9),
                                                             kv[0][1] or 0)):
        n = a["n"]
        bud_s = "--" if bud in (None, "null") else str(bud)
        rows.append(f"{pol.replace('_', chr(92)+'_')} & {bud_s} & {n} & "
                    f"{a['em']/n:.4f} & {a['rel']/n:.4f} & {a['f1']/n:.4f} & "
                    f"{a['tok']/n:,.0f} & {a['acc']/n:.1f} & {a['e2e']/n:.2f} \\\\")
    return ("\\begin{center}\\small\n"
            "\\begin{tabular}{llrrrrrrr}\\toprule\n"
            "Policy & Budget & $n$ & EM & EM$_{\\text{rel}}$ & token-F1 & mem-tok & "
            "access (ms) & e2e (s) \\\\\n\\midrule\n" + "\n".join(rows) +
            "\n\\bottomrule\n\\end{tabular}\n\\end{center}\n")


PREAMBLE = """\\documentclass[%(pt)s]{article}
\\usepackage[margin=1in]{geometry}
\\usepackage[utf8]{inputenc}
\\usepackage[T1]{fontenc}
\\usepackage{lmodern}
\\usepackage{booktabs}
\\usepackage{graphicx}
\\usepackage{amsmath,amssymb}
\\usepackage{microtype}
\\usepackage{hyperref}
\\linespread{%(spread)s}
\\title{%(title)s}
\\author{Anonymous\\thanks{Reproduction study. All numbers trace to \\texttt{results.jsonl} (2{,}520 question-level records; answerer mimo-v2.6-flash, greedy decoding).}}
\\date{}
\\begin{document}
\\maketitle
"""

TABLE_FILES = [
    ("main.tex", "Table 1: main grid (EM / EM\\_rel / token-F1 per cell)"),
    ("consolidated_emrel.tex", "Table 2: relaxed EM with bootstrap 95\\% CIs"),
    ("bytype.tex", "Table 3: strict EM by question-type family"),
    ("latency.tex", "Table 4: access / end-to-end latency and memory footprint"),
    ("stats.tex", "Table 5: paired bootstrap CI + exact McNemar"),
    ("retrieval_diagnosis.tex", "Table 7: gold recall and read/retrieve failure split"),
    ("retrieval_ranking.tex", "Table 8: session-level Recall@k / NDCG@k"),
    ("rerank_eval.tex", "Table 9: reranker + dense upgrade probe"),
    ("struct_compressor.tex", "Table 6: structured verbatim compressors"),
    ("ablation_summary_len.tex", "Table 10: summary-length ablation"),
    ("ablation_allocation.tex", "Table 11: hierarchical allocation ablation"),
    ("ablation_retrieval.tex", "Table 12: retriever-family ablation"),
    ("ablation_readside.tex", "Table 14: read-side selection ablation"),
    ("plug_baselines.tex", "Table 15: plug-in baselines"),
    ("fc_archive_absolutes.tex", "Table 16: full-context archive delivery"),
]

FIGBLOCK = """
\\begin{figure}[h]\\centering
\\includegraphics[width=0.48\\linewidth]{../output/final/tables/fig_accuracy_vs_budget.pdf}
\\hfill\\includegraphics[width=0.48\\linewidth]{../output/final/tables/fig_latency_vs_budget.pdf}
\\caption{Accuracy (relaxed EM) and end-to-end latency vs.\\ token budget across the
five budgeted strategies; full-context shown as the lossless oracle.}
\\label{fig:curves}
\\end{figure}
"""


def build_tex(pt: str, spread: str) -> str:
    md = (FINAL7 / "final_paper.md").read_text(encoding="utf-8")
    title, body = md_to_tex(md)
    # 在 Results 节末尾(即 Analysis 节之前)插图
    idx = body.find("\\section{Analysis")
    if idx > 0:
        body = body[:idx] + FIGBLOCK + "\n" + body[idx:]
    grid = full_grid_tex()
    # 内联全部真实数据表 (bare tabular -> resizebox 包裹防溢出)
    tparts = []
    for fname, cap in TABLE_FILES:
        content = (TABLES / fname).read_text(encoding="utf-8", errors="replace").strip()
        tparts.append("\\paragraph{" + cap + "}\n"
                      "\\begin{center}\\resizebox{\\textwidth}{!}{\n"
                      + content + "\n}\n\\end{center}\n")
    tex = (PREAMBLE % {"pt": pt, "spread": spread, "title": inline(title)}
           + body
           + "\n\\appendix\n\\section{Full Grid Aggregate (programmatic)}\n"
           + "All 21 cells, aggregated directly from \\texttt{results.jsonl} "
             "(2{,}520 rows; no LLM in the loop):\n\n" + grid
           + "\n\\section{Complete Generated Tables}\n"
           + "Every table below is the verbatim generated artifact under "
             "\\texttt{output/tables/} (analyze.py, post-re-run aggregation):\n\n"
           + "\n".join(tparts)
           + "\n\\end{document}\n")
    return tex


def compile_pages() -> int:
    r = subprocess.run(["pdflatex", "-interaction=nonstopmode", "iclr_paper.tex"],
                       cwd=ICLR, capture_output=True, text=True, errors="replace",
                       shell=(sys.platform == "win32"))
    m = re.search(r"Output written on iclr_paper\.pdf \((\d+) pages", r.stdout or "")
    return int(m.group(1)) if m else -1


def main() -> None:
    wl = whitelist()
    wl |= grid_values()  # 附录全格表为 results.jsonl 直算的合法派生值
    # 第一遍编译(引用/资源无关, 两遍足够)
    tried = []
    best = None
    for pt in ("11pt", "12pt", "10pt"):
        spread = 1.00
        while spread <= 1.42:
            sp = f"{spread:.2f}"
            tex = build_tex(pt, sp)
            (ICLR / "iclr_paper.tex").write_text(tex, encoding="utf-8")
            pages = compile_pages()
            tried.append((pt, sp, pages))
            print(f"  {pt} spread={sp} -> {pages} 页", flush=True)
            if pages == TARGET:
                best = (pt, sp)
                break
            if pages < 0:
                print("编译失败, 最后日志:", flush=True)
                log = (ICLR / "iclr_paper.log")
                if log.exists():
                    print("\n".join(log.read_text(errors="replace").splitlines()[-30:]))
                return
            if pages > TARGET:
                # 超页: 在本档内回退细调
                fine = spread - 0.02
                while fine >= max(1.0, spread - 0.06):
                    spf = f"{fine:.2f}"
                    tex = build_tex(pt, spf)
                    (ICLR / "iclr_paper.tex").write_text(tex, encoding="utf-8")
                    pages = compile_pages()
                    tried.append((pt, spf, pages))
                    print(f"  细调 {pt} spread={spf} -> {pages} 页", flush=True)
                    if pages <= TARGET:
                        break
                    fine -= 0.01
                if pages == TARGET:
                    best = (pt, spf)
                break
            spread += 0.02
        if best:
            break
    pages = compile_pages()
    final_tex = (ICLR / "iclr_paper.tex").read_text(encoding="utf-8")
    # 只审计正文 (跳过导言区: \linespread 参数等构建配置)
    body_only = final_tex.split("\\begin{document}", 1)[-1]
    bad = audit(body_only, wl)
    AUDIT_OUT.mkdir(parents=True, exist_ok=True)
    report = (f"AUDIT (iclr data-driven)\nconfig: {best or tried[-1]}\n"
              f"pages: {pages} (target {TARGET})\n"
              f"out-of-whitelist decimals: {len(bad)}\n" + "\n".join(bad[:80]))
    (AUDIT_OUT / "audit_report_data.txt").write_text(report, encoding="utf-8")
    print(report, flush=True)


if __name__ == "__main__":
    main()

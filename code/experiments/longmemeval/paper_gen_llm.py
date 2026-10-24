# -*- coding: utf-8 -*-
"""真实 LLM 论文生成路径: 依据 2026-10-16 复现数据生成 15 页论文 (不参考旧论文)。

数据纪律 (与 swarmflow paper-writer 同一红线):
  - 每一个数值必须来自 FACTBASE (tables/*.tex + final_paper.md 事实底稿 +
    results.jsonl 程序化聚合), 禁止编造/推算新数值;
  - 生成完成后程序化审计: 正文中出现的所有小数必须在白名单内, 越界即重写;
  - 跨读者历史表 (robustness_m53/model, matched_analysis) 不进入论文。

LLM 路径: 复用 llm.py 真实调用 (_chat -> mimo-v2.6-flash, 退避重试,
网关伪成功识别), 每次调用落 logs/calls.jsonl (RUN_LOG_DIR 启用时)。

用法:
    python paper_gen_llm.py            # 全流程: 生成 -> 编译 -> 迭代到 15 页
    python paper_gen_llm.py --audit-only
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # code/experiments/longmemeval
CODE = HERE.parents[1]                           # code/
REPO = CODE.parent                               # IsMyGo/
LM = CODE / "output" / "longmemeval"             # 实验落盘根
TABLES = LM / "tables"
FINAL7 = REPO / "output" / "final"               # 7 页定稿 (事实底稿)
TEAM = REPO / ".team" / "swarm-flow-optimization"
OUT = REPO / "output" / "final_15p"              # 15 页产物

TARGET_PAGES = 15
MAX_ROUNDS = 5

sys.path.insert(0, str(HERE))
from llm import _chat  # noqa: E402  真实 LLM 路径 (mimo-v2.6-flash)

# 跨读者历史表: 排除出论文与白名单
BANNED_TABLES = {"robustness_m53.tex", "robustness_model.tex", "matched_analysis.tex"}

SECTIONS = [
    # (key, heading, target_words, max_tokens, iclr 行号切片起止)
    ("introduction", "Introduction", 1100, 6000, (78, 145)),
    ("related", "Related Work", 900, 5200, (146, 237)),
    ("method", "Method: Six Policies under One Budget Definition", 1500, 6000, (238, 369)),
    ("setup", "Experimental Setup", 1200, 6000, (370, 430)),
    ("results", "Results", 1600, 6000, (431, 521)),
    ("analysis", "Analysis", 2200, 6000, (522, 982)),
    ("negative", "Negative Results and Diagnostic Analysis", 700, 5200, (983, 1022)),
    ("limitations", "Limitations", 800, 5200, (1023, 1115)),
    ("conclusion", "Conclusion", 420, 2600, (1116, 1151)),
]

SYS_PROMPT = (
    "You are an expert ICLR-style LaTeX paper writer. You will be given a LEGACY "
    "SECTION from an earlier 15-page paper of the same project: use it ONLY as a "
    "structural and stylistic blueprint (section flow, depth, table placement). "
    "Its numbers come from an OLD experiment generation and are FORBIDDEN. "
    "ABSOLUTE DATA DISCIPLINE: every number in your output MUST appear verbatim in "
    "the CURRENT FACT MATERIAL (2026-10-16 rerun: answerer mimo-v2.6-flash, 2,520 "
    "records). Never invent, extrapolate, or reuse legacy numbers. If a legacy claim "
    "has no support in the FACT MATERIAL, drop it. "
    "Output ONLY LaTeX body content for the requested section (no preamble, no "
    "comments). Do not write tabular environments; reference tables in prose, the "
    "build system inserts them."
)


# --------------------------------------------------------------------------- #
# 事实底稿与数据加载
# --------------------------------------------------------------------------- #
def load_factbase() -> dict:
    fb: dict = {}
    fb["draft"] = (FINAL7 / "final_paper.md").read_text(encoding="utf-8")
    tables = {}
    for p in sorted(TABLES.glob("*.tex")):
        if p.name in BANNED_TABLES:
            continue
        tables[p.name] = p.read_text(encoding="utf-8", errors="replace")
    fb["tables"] = tables
    bib = (FINAL7 / "paper.bib").read_text(encoding="utf-8")
    fb["bib"] = bib
    fb["bibkeys"] = re.findall(r"^@\w+\{([^,]+),", bib, re.M)
    # stage 报告 (存在才加载, 各截 6KB)
    for tag in ("stage1_literature_review", "stage2_hypothesis_filter"):
        p = TEAM / f"{tag}.md"
        fb[tag] = p.read_text(encoding="utf-8")[:6000] if p.exists() else ""
    # 可用 PAPER_LAB_LEGACY_TEX 指定任意参考稿, 缺省时仅凭章节骨架生成。
    legacy_tex = os.environ.get("PAPER_LAB_LEGACY_TEX",
                                str(CODE / "iclr" / "iclr_paper.tex"))
    fb["legacy"] = {}
    if Path(legacy_tex).exists():
        iclr_src = Path(legacy_tex).read_text(encoding="utf-8", errors="replace")
        lines = iclr_src.splitlines()
        for key, _, _, _, (a, b) in SECTIONS:
            chunk = "\n".join(lines[a - 1:b])[:9000]
            fb["legacy"][key] = chunk
    return fb


def number_whitelist(fb: dict) -> set[str]:
    """白名单: 底稿与全部合法表格中出现过的所有小数 (字符串精确匹配)。"""
    wl: set[str] = set()
    corpus = fb["draft"] + "\n" + "\n".join(fb["tables"].values())
    for m in re.finditer(r"\d+\.\d+", corpus):
        wl.add(m.group(0))
    return wl


def audit_numbers(tex_body: str, wl: set[str]) -> list[str]:
    """返回正文中不在白名单内的小数 (整数不查: 章节号/引用/年份噪声过大)。"""
    bad = []
    for m in re.finditer(r"(?<![\w.])-?(\d+\.\d+)", tex_body):
        tok = m.group(1)
        if tok not in wl:
            bad.append(tok)
    return sorted(set(bad))


def latex_balance_ok(chunk: str) -> bool:
    for env in re.findall(r"\\begin\{(\w+\*?)\}", chunk):
        if chunk.count(f"\\begin{{{env}}}") != chunk.count(f"\\end{{{env}}}"):
            return False
    if chunk.count("$") % 2:
        return False
    return True


# --------------------------------------------------------------------------- #
# 程序化聚合: 21 格完整大表 (附录用, 不经 LLM, 数字保证精确)
# --------------------------------------------------------------------------- #
def build_full_grid_tex() -> str:
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
    rows = []
    order = {"full_context": 0, "sliding_window": 1, "retrieval": 2,
             "retrieval_recency": 3, "compression": 4, "hierarchical": 5}
    for (pol, bud), a in sorted(agg.items(), key=lambda kv: (order.get(kv[0][0], 9),
                                                             kv[0][1] or 0)):
        n = a["n"]
        bud_s = "--" if bud in (None, "null") else str(bud)
        rows.append(
            f"{pol.replace('_', chr(92)+'_')} & {bud_s} & {n} & "
            f"{a['em']/n:.4f} & {a['rel']/n:.4f} & {a['f1']/n:.4f} & "
            f"{a['tok']/n:,.0f} & {a['acc']/n:.1f} & {a['e2e']/n:.2f} \\\\")
    body = "\n".join(rows)
    return (
        "\\begin{table}[h]\\centering\\small\n"
        "\\caption{Full grid: all 21 cells aggregated from the 2{,}520-question-level "
        "records in \\texttt{results.jsonl} (answerer mimo-v2.6-flash, greedy). "
        "mem-tok = mean memory tokens presented to the answerer; access = mean "
        "memory-access latency (ms); e2e = mean end-to-end latency (s). "
        "Generated programmatically; no LLM in the loop.}\\label{tab:fullgrid}\n"
        "\\begin{tabular}{llrrrrrrr}\\toprule\n"
        "Policy & Budget & $n$ & EM & EM$_{\\text{rel}}$ & token-F1 & mem-tok & "
        "access (ms) & e2e (s) \\\\\n\\midrule\n"
        f"{body}\n\\bottomrule\n\\end{{tabular}}\n\\end{{table}}\n")


# --------------------------------------------------------------------------- #
# LLM 章节生成
# --------------------------------------------------------------------------- #
async def gen_section(key: str, heading: str, target_words: int,
                      material: str, fb: dict, extra_task: str = "") -> str:
    material = material[:16000]  # 防 prompt 超限 (过长会导致空响应)
    _legacy = fb["legacy"].get(key, "")
    legacy_block = (
        "LEGACY SECTION (STRUCTURAL BLUEPRINT ONLY -- its numbers are from an old "
        "experiment generation and are FORBIDDEN; mirror its structure, subsection "
        "flow and depth, but rewrite all content around the CURRENT facts):\n"
        "<<<<<<< LEGACY\n" + _legacy + "\n>>>>>>>\n"
    ) if _legacy.strip() else (
        "No legacy blueprint is available for this section: structure it yourself "
        "with clear \\subsection flow appropriate for an ICLR-style paper.\n"
    )
    user = (
        "TASK: Write the LaTeX body for one section of a research paper titled "
        "\"When Does Memory Compression Pay Off? A Budget-Controlled Study of "
        "Memory Policies for LLM Agents on LongMemEval\". Section: " + heading + ".\n"
        "Target length: about " + str(target_words) + " words of prose (tables are "
        "included separately by the build system -- do NOT write tabular environments, "
        "just reference them in prose, e.g. Table~\\ref{tab:main} reports the "
        "headline grid).\n"
        + legacy_block +
        "CURRENT FACT MATERIAL (the ONLY allowed source of numbers):\n"
        "<<<<<<< FACTS\n" + material + "\n>>>>>>>\n"
        "CITE with \\citep{key} / \\citet{key} using ONLY these bibtex keys:\n"
        + ", ".join(fb["bibkeys"]) + "\n"
        "Remember: every decimal number in your output MUST appear verbatim in the "
        "CURRENT FACT MATERIAL. No legacy numbers, no new numbers."
        + ("\n" + extra_task if extra_task else "")
    )
    last = ""
    for attempt in range(3):
        out = await _chat(SYS_PROMPT, user, max_tokens=4000, temperature=0.2,
                          purpose=f"论文生成Agent({key})")
        text = out["text"].strip()
        text = re.sub(r"^```(?:latex)?\s*|\s*```$", "", text, flags=re.S).strip()
        last = text
        if latex_balance_ok(text) and text.count("\\section") <= 1:
            return text
    return last  # 平衡检查失败也返回, 由编译错误回路兜底


async def rewrite_section(key: str, heading: str, old: str, task: str,
                          material: str, fb: dict) -> str:
    material = material[:16000]
    user = (
        f"TASK: Rewrite the LaTeX section \"{heading}\" of the paper. {task}\n"
        f"CURRENT VERSION:\n<<<<<<<\n{old[:9000]}\n>>>>>>>\n"
        f"FACT MATERIAL (the ONLY allowed source of numbers):\n"
        f"<<<<<<<\n{material}\n>>>>>>>\n"
        f"Keep the same \\section heading. Output ONLY the rewritten LaTeX body."
    )
    for attempt in range(3):
        out = await _chat(SYS_PROMPT, user, max_tokens=4000, temperature=0.2,
                          purpose=f"论文修订Agent({key})")
        text = re.sub(r"^```(?:latex)?\s*|\s*```$", "", out["text"].strip(),
                      flags=re.S).strip()
        if latex_balance_ok(text):
            return text
    return old


# --------------------------------------------------------------------------- #
# 拼装与编译
# --------------------------------------------------------------------------- #
PREAMBLE = """\\documentclass{article}
\\usepackage[margin=1in]{geometry}
\\usepackage{iclr2025_conference}
\\usepackage{booktabs}
\\usepackage{graphicx}
\\usepackage{amsmath,amssymb}
\\usepackage{xcolor}
\\title{When Does Memory Compression Pay Off?\\\\ A Budget-Controlled Study of Memory Policies for LLM Agents on LongMemEval}
\\author{Anonymous\\thanks{Reproduction study. All numbers trace to \\texttt{results.jsonl} (2{,}520 question-level records; answerer mimo-v2.6-flash, greedy decoding).}}
\\newcommand{\\longmemN}{120}
\\begin{document}
\\maketitle
"""


def assemble(sections: dict, abstract: str, appendix_narrative: str,
             full_grid: str) -> str:
    inject_after = {
        "results": ["tables/main.tex", "tables/consolidated_emrel.tex",
                    "tables/stats.tex", "tables/bytype.tex", "tables/latency.tex"],
        "analysis": ["tables/retrieval_diagnosis.tex", "tables/rerank_eval.tex",
                     "tables/struct_compressor.tex", "tables/ablation_summary_len.tex",
                     "tables/ablation_allocation.tex", "tables/ablation_retrieval.tex",
                     "tables/ablation_readside.tex", "tables/plug_baselines.tex",
                     "tables/fc_archive_absolutes.tex"],
    }
    parts = [PREAMBLE, "\\begin{abstract}\n" + abstract + "\n\\end{abstract}\n"]
    for key, heading, _, _, _ in SECTIONS:
        body = sections[key]
        if not body.lstrip().startswith("\\section"):
            parts.append("\\section{" + heading + "}\n")
        parts.append(body + "\n")
        for f in inject_after.get(key, []):
            parts.append("\n\\begin{table}[h]\\centering\n\\input{" + f +
                         "}\n\\end{table}\n")
    tex = "\n".join(parts)
    # 图
    tex += ("\n\\begin{figure}[h]\\centering\n"
            "\\includegraphics[width=0.48\\linewidth]{tables/fig_accuracy_vs_budget.pdf}"
            "\\hfill\\includegraphics[width=0.48\\linewidth]{tables/fig_latency_vs_budget.pdf}\n"
            "\\caption{Accuracy and end-to-end latency vs.\\ token budget across the "
            "five budgeted strategies (from \\texttt{results.jsonl} aggregation).}\n"
            "\\label{fig:curves}\n\\end{figure}\n")
    # 附录
    tex += ("\n\\appendix\n\\section{Full Grid Aggregate}\n" + full_grid +
            "\n\\section{Reproducibility Notes}\n" + appendix_narrative +
            "\n\\bibliography{paper}\\bibliographystyle{iclr2025_conference}\n"
            "\\end{document}\n")
    return tex


def compile_pdf(build_dir: Path) -> tuple[int, str]:
    log = ""
    for cmd in (["pdflatex", "-interaction=nonstopmode", "paper.tex"],
                ["bibtex", "paper"],
                ["pdflatex", "-interaction=nonstopmode", "paper.tex"],
                ["pdflatex", "-interaction=nonstopmode", "paper.tex"]):
        r = subprocess.run(cmd, cwd=build_dir, capture_output=True, text=True,
                           errors="replace", shell=(sys.platform == "win32"))
        log = r.stdout or ""
    m = re.search(r"Output written on paper\.pdf \((\d+) pages", log)
    return (int(m.group(1)) if m else -1), log


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def section_material(key: str, fb: dict) -> str:
    """给每章注入对应事实素材 (最终数字来源)。"""
    d = fb["draft"]
    t = fb["tables"]

    def cut(a: str, b: str) -> str:
        i, j = d.find(a), d.find(b)
        return d[i:j] if (i >= 0 and j > i) else d

    seg = {
        "introduction": d[:6000] + "\n" + fb.get("stage1_literature_review", ""),
        "related": cut("## 2", "## 3") + "\n" + fb["bib"][:4000],
        "method": cut("## 3", "## 5"),
        "setup": cut("## 4", "## 5") + "\n" + t.get("headline.tex", ""),
        "results": cut("## 5", "## 6") + "\n" + "\n".join(
            t.get(k, "") for k in ("main.tex", "consolidated_emrel.tex",
                                   "stats.tex", "bytype.tex")),
        "analysis": cut("## 6", "## 7")[:9000] + "\n" + "\n".join(
            t.get(k, "")[:2500] for k in ("retrieval_diagnosis.tex", "rerank_eval.tex",
                                          "struct_compressor.tex",
                                          "ablation_readside.tex",
                                          "plug_baselines.tex")),
        "negative": cut("## 6", "## 7")[:6000] + "\n" + "\n".join(
            t.get(k, "")[:2500] for k in ("rerank_eval.tex", "struct_compressor.tex")),
        "limitations": cut("## 7", "## 8"),
        "conclusion": cut("## 8", "## References"),
    }[key]
    return seg


async def main() -> None:
    fb = load_factbase()
    wl = number_whitelist(fb)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tables").mkdir(exist_ok=True)
    for f in FINAL7.glob("*.sty"):
        shutil.copy(f, OUT / f.name)
    for f in FINAL7.glob("*.bst"):
        shutil.copy(f, OUT / f.name)
    shutil.copy(FINAL7 / "paper.bib", OUT / "paper.bib")
    for p in TABLES.glob("*.tex"):
        if p.name not in BANNED_TABLES:
            shutil.copy(p, OUT / "tables" / p.name)
    for p in TABLES.glob("fig_*.pdf"):
        shutil.copy(p, OUT / "tables" / p.name)

    print("[1/4] 生成各章节 (真实 LLM 路径: mimo-v2.6-flash) ...", flush=True)
    # 摘要单独生成 (无 legacy 参考, 从 7 页定稿事实压缩)
    abstract = await gen_section(
        "abstract", "Abstract (one paragraph, plain text, no citations commands)",
        220, fb["draft"][:3500], fb,
        extra_task=("Do NOT output any \\section; output ONLY the abstract paragraph "
                    "text. Do not use the legacy blueprint."))
    sections: dict[str, str] = {}
    for key, heading, words, _, _ in SECTIONS:
        mat = section_material(key, fb)
        sections[key] = await gen_section(key, heading, words, mat, fb)
        print(f"    {key}: {len(sections[key])} chars", flush=True)

    # 附录叙述 (复现说明)
    d0 = fb["draft"].find("## Appendix")
    appx_mat = fb["draft"][d0:] if d0 > 0 else fb["draft"][-3000:]
    appendix_narrative = await gen_section(
        "appendix", "Reproducibility Notes (appendix)", 550, appx_mat, fb,
        extra_task=("Describe the reproduction pipeline, caching/breakpoint-resume "
                    "design and data discipline in prose. No \\section. Do not use "
                    "the legacy blueprint."))
    full_grid = build_full_grid_tex()

    print("[2/4] 拼装 + 编译 ...", flush=True)
    tex = assemble(sections, abstract, appendix_narrative, full_grid)
    (OUT / "paper.tex").write_text(tex, encoding="utf-8")
    pages, log = compile_pdf(OUT)
    print(f"    初版页数: {pages}", flush=True)

    print("[3/4] 页数迭代 ...", flush=True)
    round_ = 0
    while pages != TARGET_PAGES and round_ < MAX_ROUNDS:
        if pages <= 0:
            print("    编译失败, 跳过页数迭代 (检查 paper.log)", flush=True)
            break
        round_ += 1
        diff = TARGET_PAGES - pages
        if diff > 0:
            pool = ["analysis", "results", "method", "related", "introduction", "setup"]
            key = pool[(round_ - 1) % len(pool)]
            heading = dict((k, h) for k, h, _, _, _ in SECTIONS)[key]
            task = (f"The compiled paper is {pages} pages but the hard requirement is "
                    f"{TARGET_PAGES} pages. EXPAND this section substantially (about "
                    f"{600 + 250 * min(diff, 4)} more words), deepening the argument "
                    f"with analysis of the SAME fact material. Do not add new numbers.")
        else:
            pool = ["related", "introduction", "analysis", "method"]
            key = pool[(round_ - 1) % len(pool)]
            heading = dict((k, h) for k, h, _, _, _ in SECTIONS)[key]
            task = (f"The compiled paper is {pages} pages but it must be EXACTLY "
                    f"{TARGET_PAGES} pages. CONDENSE this section by about "
                    f"{-diff * 350} words while keeping all key results.")
        sections[key] = await rewrite_section(key, heading, sections[key],
                                              task, section_material(key, fb), fb)
        tex = assemble(sections, abstract, appendix_narrative, full_grid)
        (OUT / "paper.tex").write_text(tex, encoding="utf-8")
        pages, log = compile_pdf(OUT)
        print(f"    round {round_}: 扩缩 {key} -> {pages} 页", flush=True)

    print("[4/4] 数字纪律审计 ...", flush=True)
    # 编译成功的前提下, 逐章修复越界数字 (最多 2 轮)
    fix_round = 0
    while pages > 0 and fix_round < 2:
        sec_bad = {k: audit_numbers(v, wl) for k, v in sections.items()}
        sec_bad = {k: v for k, v in sec_bad.items() if v}
        if not sec_bad:
            break
        fix_round += 1
        print(f"    修复越界数字 round {fix_round}: {list(sec_bad)}", flush=True)
        for key, bads in sec_bad.items():
            heading = dict((k, h) for k, h, _, _, _ in SECTIONS)[key]
            task = ("DATA DISCIPLINE VIOLATION: your version contains numbers that "
                    "are NOT in the fact material: " + ", ".join(bads[:40]) +
                    ". Rewrite the section REMOVING or correcting every such number "
                    "(use only numbers from the fact material; if a sentence depends "
                    "on an unsupported number, delete the sentence). Keep everything "
                    "else unchanged. Output ONLY the rewritten LaTeX body.")
            sections[key] = await rewrite_section(key, heading, sections[key],
                                                  task, section_material(key, fb), fb)
        tex = assemble(sections, abstract, appendix_narrative, full_grid)
        (OUT / "paper.tex").write_text(tex, encoding="utf-8")
        pages, log = compile_pdf(OUT)
        print(f"    修复后: {pages} 页", flush=True)

    bad = audit_numbers(tex, wl)
    audit = ("AUDIT REPORT (final_15p)\n"
             f"pages: {pages} (target {TARGET_PAGES})\n"
             f"out-of-whitelist decimals: {len(bad)}\n")
    if bad:
        audit += "\n".join(bad[:80]) + "\n"
    (OUT / "audit_report.txt").write_text(audit, encoding="utf-8")
    print(audit, flush=True)
    print(f"DONE: pages={pages}, audit={'PASS' if not bad else f'{len(bad)} BAD'}",
          flush=True)


if __name__ == "__main__":
    asyncio.run(main())

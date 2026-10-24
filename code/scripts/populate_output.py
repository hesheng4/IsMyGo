
"""populate_output.py —— 把「logs/run.json 那一次运行」的产物整理进 output/。

按 样例说明/output/README.md 的要求：
  * 只放本次 run_id 运行写出的结果；
  * 生成稿 + PDF、论文表格所依据的结果文件、流程跑完的中间结果；
  * 不放依赖包 / 虚拟环境 / 模型权重 / 无关缓存。

链路：run.py --full --log-run  ->  results.jsonl
      analyze.py               ->  tables/*.tex,*.json,fig_*.pdf
      pdflatex x3 + bibtex     ->  paper.pdf
      本脚本                    ->  output/{paper.tex,paper.pdf,results.jsonl,tables/,draft/,README.md}
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PKG = Path(os.environ.get("PAPER_PKG", str(Path(__file__).resolve().parents[2])))
CODE = PKG / "code"
OUTD = PKG / "output"
PY = os.environ.get("PAPER_PY", sys.executable)

ICLR = CODE / "iclr"
if not (ICLR / "iclr_paper.tex").exists():
    # 2026-10-16 旧代际清理: iclr_paper.tex 及旧成稿 (output/paper.*) 已移除,
    # 本脚本的成稿/编译步骤随之失效; 当前论文定稿见 output/final/。
    sys.exit(
        "[populate_output] 旧论文源 code/iclr/iclr_paper.tex 已随 2026-10-16 "
        "旧代际清理移除, 本脚本成稿链失效。\n"
        "  当前论文定稿: output/final/ (paper.tex + paper.pdf + final_paper.md)\n"
        "  论文实验表格仍可复现: run.py --full -> analyze.py")


def _resolve_texbin():
    """定位 pdflatex/bibtex 所在目录（跨环境可迁移）：
    PAPER_TEXBIN 环境变量 > PATH 解析 > 常见安装位置逐个探测；找不到返回 None（依赖 PATH）。"""
    env = os.environ.get("PAPER_TEXBIN")
    if env:
        return env
    import shutil
    w = shutil.which("pdflatex")
    if w:
        return str(Path(w).parent)
    exe = "pdflatex.exe" if os.name == "nt" else "pdflatex"
    for cand in (r"D:\MikTex\miktex\bin\x64",
                 str(Path.home() / "AppData/Local/Programs/MiKTeX/miktex/bin/x64"),
                 "/usr/bin", "/usr/local/bin"):
        if (Path(cand) / exe).exists():
            return cand
    return None


TEXBIN = _resolve_texbin()

LM = CODE / "experiments" / "longmemeval"
TABLES_SRC = CODE / "output" / "longmemeval" / "tables"
RES_SRC = CODE / "output" / "longmemeval" / "results.jsonl"
ICLR = CODE / "iclr"


def sha(p: Path, n: int = 16) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:n]


def step(msg: str) -> None:
    print("\n=== %s ===" % msg, flush=True)


def main() -> int:
    OUTD.mkdir(parents=True, exist_ok=True)
    for sub in ("tables", "draft"):
        (OUTD / sub).mkdir(exist_ok=True)

    # ---------- 1) 结果文件（本次运行的逐题记录） ----------
    step("1) 结果文件")
    if not RES_SRC.exists():
        print("!! 缺少 %s，请先跑 run.py --full --log-run" % RES_SRC)
        return 1
    shutil.copyfile(RES_SRC, OUTD / "results.jsonl")
    n = sum(1 for l in open(RES_SRC, encoding="utf-8") if l.strip())
    print("results.jsonl: %d 条记录 -> output/results.jsonl  sha256=%s" % (n, sha(RES_SRC)))

    # ---------- 1b) 从本次运行的 results.jsonl 重新生成表格 ----------
    step("1b) analyze.py 生成表格")
    env_lm = dict(os.environ)
    # tiktoken BPE 缓存目录：尊重外部指定；默认落到包内 .tmp/（不依赖外部目录布局）
    env_lm.setdefault("TIKTOKEN_CACHE_DIR", str(PKG / ".tmp" / "tiktoken-cache"))
    Path(env_lm["TIKTOKEN_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)
    pr = subprocess.run([PY, "analyze.py"], cwd=str(LM), env=env_lm,
                        capture_output=True, text=True, errors="replace")
    tail = (pr.stdout or "").strip().splitlines()[-1:] or [""]
    print("  analyze.py exit=%d  %s" % (pr.returncode, tail[0][:90]))
    if pr.returncode != 0:
        print("\n".join((pr.stdout or "").splitlines()[-12:]))
        print("\n".join((pr.stderr or "").splitlines()[-12:]))
        return 1
    # ---------- 2) 表格（论文 \\input 的直接依据） ----------
    step("2) 论文表格")
    tex = sorted(TABLES_SRC.glob("*"))
    for f in tex:
        shutil.copyfile(f, OUTD / "tables" / f.name)
    print("复制 %d 个表格/图件 -> output/tables/" % len(tex))

    # 2b) 生成 CSV（便于人工核对表 2）
    step("2b) 表 2 的 CSV 版")
    recs = [json.loads(l) for l in open(RES_SRC, encoding="utf-8").read().splitlines() if l.strip()]
    import collections
    g = collections.defaultdict(list)
    for r in recs:
        g[(r["policy"], r.get("budget"))].append(r)
    rows = ["policy,budget,n,em,em_rel,token_f1,mem_tokens,e2e_ms"]
    for (pol, b) in sorted(g, key=lambda x: (x[0], -1 if x[1] is None else x[1])):
        rs = g[(pol, b)]
        if pol == "full_context":
            rs = [r for r in rs if (r.get("pred") or "").strip() or r.get("prompt_tokens", 0) > 0]
        if not rs:
            continue
        m = lambda k: sum(r[k] for r in rs) / len(rs)
        rows.append("%s,%s,%d,%.4f,%.4f,%.4f,%.0f,%.1f" % (
            pol, "" if b is None else b, len(rs), m("em"), m("relaxed_em"), m("f1"),
            m("memory_footprint_tokens"), m("e2e_ms")))
    (OUTD / "tables" / "main.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print("main.csv: %d 行" % len(rows))

    # ---------- 3) 生成稿 ----------
    step("3) 生成稿 paper.tex")
    # 原稿 \input 指向 code/output/longmemeval/tables/（编译源目录）。复制进 output/
    # 后改写成相对 output/ 自身的 tables/，使 output/ 成为自洽目录：
    # PDF 由 output/tables/ 编译，与交付视图同一代际。
    _tex_src = (ICLR / "iclr_paper.tex").read_text(encoding="utf-8")
    _n_path = _tex_src.count("../output/longmemeval/tables/")
    (OUTD / "paper.tex").write_text(
        _tex_src.replace("../output/longmemeval/tables/", "tables/"), encoding="utf-8")
    print("paper.tex <- code/iclr/iclr_paper.tex (改写 %d 处路径为相对 output/)  sha256=%s"
          % (_n_path, sha(OUTD / "paper.tex")))
    for _f in ("iclr2025_conference.sty", "iclr2025_conference.bst", "iclr_paper.bib"):
        if (ICLR / _f).exists():
            shutil.copyfile(ICLR / _f, OUTD / _f)

    # ---------- 4) 编译 PDF ----------
    step("4) 编译 paper.pdf")
    env = dict(os.environ)
    if TEXBIN:  # 找到 TeX 工具链目录时前置 PATH；否则沿用系统 PATH
        env["PATH"] = TEXBIN + os.pathsep + env.get("PATH", "")
    # 直接在 output/ 下编译：paper.tex 的 \input 已指向同目录的 tables/，
    # 因此 PDF 与 output/ 的表格严格同一代际，不依赖 code/ 目录。

    for i in range(1, 4):
        args = ["pdflatex", "-interaction=nonstopmode", "paper.tex"]
        if i == 2:
            subprocess.run(["bibtex", "paper"], cwd=str(OUTD), env=env,
                           capture_output=True, text=True, errors="replace")
        p = subprocess.run(args, cwd=str(OUTD), env=env, capture_output=True,
                           text=True, errors="replace")
        print("  pdflatex pass %d: exit=%d" % (i, p.returncode))
        if p.returncode != 0 and i == 1:
            print("  编译失败，尾部输出：")
            print("\n".join((p.stdout or "").splitlines()[-15:]))
            return 1
    pdf = OUTD / "paper.pdf"
    if not pdf.exists():
        print("!! PDF 未生成")
        return 1
    print("paper.pdf: %.0f KB  sha256=%s" % (pdf.stat().st_size / 1024, sha(pdf)))

    # ---------- 4b) 页数硬性校验（必须 15 页） ----------
    import re as _re
    _pages = 0
    _log = OUTD / "paper.log"
    if _log.exists():
        _m = _re.search(r"Output written on paper\.pdf \((\d+) pages",
                        _log.read_text(encoding="utf-8", errors="replace"))
        if _m:
            _pages = int(_m.group(1))
    REQUIRED_PAGES = 15
    if _pages != REQUIRED_PAGES:
        print("!! 页数硬性校验失败：实测 %d 页，要求正好 %d 页" % (_pages, REQUIRED_PAGES))
        print("   请调整正文篇幅（加深分析补页 / 压缩冗余减页）后重跑本脚本。")
        return 1
    print("页数校验通过：15 页")

    # ---------- 5) 中间结果（草稿/大纲） ----------
    step("5) 中间结果")
    draft = OUTD / "draft"
    # 5a) 论文大纲：从 tex 抽 \section 结构
    texsrc = (ICLR / "iclr_paper.tex").read_text(encoding="utf-8")
    import re
    outline = ["# 论文大纲（由 iclr_paper.tex 的章节结构抽取）", ""]
    for m in re.finditer(r"\\(section|subsection)\{([^}]+)\}", texsrc):
        lvl = "  " if m.group(1) == "subsection" else ""
        outline.append("%s- %s" % (lvl, m.group(2)))
    (draft / "outline.md").write_text("\n".join(outline) + "\n", encoding="utf-8")
    print("draft/outline.md: %d 个章节" % (len(outline) - 2))
    # 5b) 运行摘要
    run = json.loads((PKG / "logs" / "run.json").read_text(encoding="utf-8"))
    (draft / "run_summary.md").write_text(
        "# 本次运行摘要\n\n" + "\n".join("- %s: %s" % (k, v) for k, v in run.items()) + "\n",
        encoding="utf-8")
    print("draft/run_summary.md")

    # ---------- 6) 运行清单 ----------
    step("6) 运行清单 run_manifest.json")
    manifest = {
        "run_id": run["run_id"],
        "command": run["command"],
        "model": run["model"],
        "llm_calls": run["llm_calls"],
        "token_total": run["token_total"],
        "wall_seconds": run["wall_seconds"],
        "artifacts": {},
    }
    for p in sorted(OUTD.rglob("*")):
        if p.is_file() and p.name != "run_manifest.json":
            manifest["artifacts"][str(p.relative_to(OUTD))] = {
                "bytes": p.stat().st_size, "sha256_16": sha(p)}
    (OUTD / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("run_manifest.json: %d 个产物" % len(manifest["artifacts"]))
    print("\nDONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""整合表 (审稿意见: 论文数字密集): 策略 × 预算 的 relaxed EM 单表汇总,
每格附 per-cell percentile bootstrap 95% CI (10,000 次重采样, seed 42)。

输入:
  results.jsonl            本次运行的逐题记录 (主网格, 必读)
  ARCHIVE_RESULTS 指向的归档流水 (可选, 用于补出归档代际的
                           full-context 完成子集行; 未设置或文件不存在时
                           该行整行写为 "--")
输出:
  tables/consolidated_emrel.tex

本次运行与归档代际分开成行，不合并口径。"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import load_questions  # noqa: E402

OUT = HERE.parents[1] / "output" / "longmemeval"
TAB = OUT / "tables"

# 归档代际流水 (可选): 交付包 results.jsonl 只含本次主网格, 归档 full-context
# 完成子集行需从归档流水补出。未设置时该行写 "--"。
import os  # noqa: E402
# 归档代际流水的默认位置: IsMyGo/output/archive/results_archive.jsonl
# (OUT = code/output/longmemeval, 故 parents[2] 为包根 IsMyGo)
_DEFAULT_ARCHIVE = OUT.parents[2] / "output" / "archive" / "results_archive.jsonl"
ARCHIVE = os.environ.get("ARCHIVE_RESULTS") or str(_DEFAULT_ARCHIVE)

POLICY_ROWS = [
    ("sliding_window", r"sliding window"),
    ("retrieval", r"retrieval (BM25)"),
    ("retrieval_recency", r"retrieval+recency"),
    ("compression", r"compression (window+summ.)"),
    ("hierarchical", r"hierarchical (3-tier)"),
]
BUDGETS = [512, 1024, 2048, 4096]
DASH = "--"


def mean_ci(xs: list[float], n_boot: int = 10000, seed: int = 42):
    """单格均值的 percentile bootstrap 95% CI (与 score.py 同随机数协议)。"""
    rng = random.Random(seed)
    n = len(xs)
    point = sum(xs) / n
    boots = []
    for _ in range(n_boot):
        boots.append(sum(xs[rng.randrange(n)] for _ in range(n)) / n)
    boots.sort()
    return point, boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot)]


def fmt(point: float, lo: float, hi: float) -> str:
    return f"{point:.3f} [{lo:.2f}, {hi:.2f}]"


def main() -> None:
    sample = {q.question_id for q in load_questions()}
    rows = [json.loads(l) for l in (OUT / "results.jsonl").read_text(
        encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r["question_id"] in sample]

    cell: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        if r["policy"] != "full_context" and r["budget"] in BUDGETS:
            cell[(r["policy"], r["budget"])].append(r.get("relaxed_em", 0.0))
    fc_done = [r.get("relaxed_em", 0.0) for r in rows
               if r["policy"] == "full_context"
               and (r["pred"].strip() or r.get("prompt_tokens", 0) > 0)]

    arch_done: list[float] = []
    if ARCHIVE and Path(ARCHIVE).is_file():
        for line in Path(ARCHIVE).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if (r["policy"] == "full_context" and r["question_id"] in sample
                    and r.get("pred", "").strip()):
                arch_done.append(r.get("relaxed_em", 0.0))
        print(f"[consolidated] archive rows: {len(arch_done)} "
              f"(from {ARCHIVE})")
    else:
        print("[consolidated] ARCHIVE_RESULTS not set or missing; "
              "archive row written as --")

    lines = [r"\begin{tabular}{lcccc}", r"\toprule",
             r"Policy & $B{=}512$ & $B{=}1024$ & $B{=}2048$ & $B{=}4096$ \\",
             r"\midrule"]
    for pol, label in POLICY_ROWS:
        vals = [fmt(*mean_ci(cell[(pol, b)]))
                if cell.get((pol, b)) else "--" for b in BUDGETS]
        lines.append(label + " & " + " & ".join(vals) + r" \\")
    lines.append(r"\midrule")
    lines.append(
        rf"full-context (this run, $n{{=}}{len(fc_done)}$) & "
        rf"\multicolumn{{4}}{{c}}{{{fmt(*mean_ci(fc_done)) if fc_done else DASH}}} \\")
    lines.append(
        rf"full-context (archive completed, $n{{=}}{len(arch_done)}$) & "
        rf"\multicolumn{{4}}{{c}}{{{fmt(*mean_ci(arch_done)) if arch_done else DASH}}} \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    TAB.mkdir(parents=True, exist_ok=True)
    (TAB / "consolidated_emrel.tex").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    print(f"[consolidated] written: {TAB / 'consolidated_emrel.tex'} "
          f"(full-context completed n={len(fc_done)})")


if __name__ == "__main__":
    main()

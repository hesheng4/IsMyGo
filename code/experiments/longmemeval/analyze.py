# -*- coding: utf-8 -*-
"""从 results.jsonl 聚合出论文所需的全部表格与统计检验。

输出: tables/ 目录下的 .tex 片段 (主表/分题型/延迟/足迹) + stats.json
(bootstrap CI 与 McNemar), 论文用 \\input 引入, 保证数字逐字可溯源。
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from common import resolve_model_names
from score import mcnemar_exact, paired_bootstrap

n_sessions = 0

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "output" / "longmemeval"
TAB = OUT / "tables"

POLICY_ORDER = [
    "full_context", "sliding_window", "retrieval",
    "retrieval_recency", "compression", "hierarchical",
]
POLICY_TEX = {
    "full_context": r"full-context (verbatim)$^{\dagger}$",
    "sliding_window": r"sliding window",
    "retrieval": r"retrieval (BM25)",
    "retrieval_recency": r"retrieval+recency",
    "compression": r"compression (window+summ.)",
    "hierarchical": r"hierarchical (3-tier)",
}


def _fc_completed(rs: list[dict]) -> list[dict]:
    """full-context 完成子集 (A1): 84/120 条客户端层失败空记录 (429 风暴)
    不入均值; 完成判定 = 有答案或有 API token 计数。"""
    return [r for r in rs
            if r["pred"].strip() or r.get("prompt_tokens", 0) > 0]


def load_records(answerer: str | None = None) -> list[dict]:
    """只保留规范全量样本 (分层 120 题, seed 42) 内的记录——
    冒烟运行的额外题目不进入论文统计。

    answerer: 只取该答题器模型生成的记录（主网格按答题器分组，答题器随配置变化）；
    缺省取数据中占比最大的答题器（历史归档 = GLM-4-Flash）。"""
    from common import load_questions, record_model

    sample_ids = {q.question_id for q in load_questions()}
    recs = []
    for line in (OUT / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r["question_id"] in sample_ids:
                recs.append(r)
    if answerer is None:
        from collections import Counter
        # 主网格（无跨读者后缀）记录的答题器众数 = 本次表格的主答题器
        main_cnt = Counter(record_model(r) for r in recs if "@" not in str(r["policy"]))
        answerer = (main_cnt.most_common(1)[0][0] if main_cnt else record_model({}))
    recs = [r for r in recs if record_model(r) == answerer]
    return recs


def by_key(recs: list[dict]) -> dict[tuple, list[dict]]:
    g: dict[tuple, list[dict]] = defaultdict(list)
    for r in recs:
        g[(r["policy"], r["budget"])].append(r)
    return g


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def main() -> None:
    TAB.mkdir(parents=True, exist_ok=True)
    recs = load_records()
    g = by_key(recs)
    budgets = sorted({b for (_, b) in g if b is not None})
    # 去重会话数取自数据集 (缓存目录含 w20/w60/w120 三变体文件, 不能直接数文件)
    from common import load_questions, unique_sessions
    n_sessions = len(unique_sessions(load_questions()))

    # ---------- 主表: EM / F1 (均值), 每策略一行, 每预算一列 ----------
    # full-context 行按 A1 完成子集口径 (dagger 脚注在论文 caption 中说明)
    rows = []
    for pol in POLICY_ORDER:
        if pol == "full_context":
            rs = _fc_completed(g.get(("full_context", None), []))
            if rs:
                rows.append(
                    (pol, None, mean([r["em"] for r in rs]),
                     mean([r.get("relaxed_em", 0.0) for r in rs]),
                     mean([r["f1"] for r in rs]), len(rs))
                )
            continue
        for b in budgets:
            rs = g.get((pol, b), [])
            if rs:
                rows.append((pol, b, mean([r["em"] for r in rs]),
                             mean([r.get("relaxed_em", 0.0) for r in rs]),
                             mean([r["f1"] for r in rs]), len(rs)))

    lines = [
        r"\begin{tabular}{llcccc}", r"\toprule",
        r"Policy & Budget & $n$ & EM & EM$_{\text{rel}}$ & token-F1 \\",
        r"\midrule",
    ]
    for pol, b, em, rem, f1, n in rows:
        btxt = "--" if b is None else str(b)
        lines.append(
            f"{POLICY_TEX[pol]} & {btxt} & {n} & {em:.4f} & {rem:.4f} & {f1:.4f} \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TAB / "main.tex").write_text("\n".join(lines), encoding="utf-8")

    # ---------- 分题型表 (每策略在 4 预算聚合, 附 full_context) ----------
    lines = [
        r"\begin{tabular}{lcccccc}", r"\toprule",
        r"Policy & single-* & multi & temporal & update & overall \\",
        r"\midrule",
    ]
    for pol in POLICY_ORDER:
        rs = [r for r in recs if r["policy"] == pol]
        if pol == "full_context":
            rs = _fc_completed(rs)
        if not rs:
            continue

        def acc(filt, key="relaxed_em"):
            xs = [r.get(key, 0.0) for r in rs if filt(r)]
            return f"{mean(xs):.3f}" if xs else "--"

        lines.append(
            f"{POLICY_TEX[pol]} & "
            f"{acc(lambda r: r['question_type'].startswith('single'))} & "
            f"{acc(lambda r: r['question_type'] == 'multi-session')} & "
            f"{acc(lambda r: r['question_type'] == 'temporal-reasoning')} & "
            f"{acc(lambda r: r['question_type'] == 'knowledge-update')} & "
            f"{mean([r['em'] for r in rs]):.3f} \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TAB / "bytype.tex").write_text("\n".join(lines), encoding="utf-8")

    # ---------- 延迟/足迹表 ----------
    lines = [
        r"\begin{tabular}{llcccc}", r"\toprule",
        r"Policy & Budget & access (ms) & e2e (s) & mem.\ tokens \\",
        r"\midrule",
    ]
    for pol, b, *_ in rows:
        rs = g[(pol, b)]
        if pol == "full_context":
            rs = _fc_completed(rs)  # A1: 空调用 (e2e=0) 不污染延迟均值
        lines.append(
            f"{POLICY_TEX[pol]} & {'--' if b is None else b} & "
            f"{mean([r['access_ms'] for r in rs]):.3f} & "
            f"{mean([r['e2e_ms'] for r in rs])/1000:.2f} & "
            f"{mean([r['memory_footprint_tokens'] for r in rs]):.0f} \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TAB / "latency.tex").write_text("\n".join(lines), encoding="utf-8")

    # ---------- 统计检验: 双基线 (Q8 决议) ----------
    # 主对照 = retrieval (BM25) 固定; 第二对照 = 最强非压缩替代策略 (现行口径)。
    stats: dict[str, dict] = {}
    qids = sorted({r["question_id"] for r in recs})

    def vec(pol: str, b, metric: str = "relaxed_em") -> list[float]:
        d = {r["question_id"]: r[metric] for r in g.get((pol, b), [])}
        return [d.get(q, 0.0) for q in qids]

    def compare(b, base_pol):
        a, base = vec("compression", b), vec(base_pol, b)
        (ma, mb, p_gt), ci = paired_bootstrap(a, base)
        return {
            "baseline": base_pol,
            "compression_em": ma,
            "baseline_em": mb,
            "delta_ci95": ci,
            "p_boot_greater": p_gt,
            "mcnemar": mcnemar_exact(a, base),
        }

    for b in budgets:
        comps = {
            p: mean(vec(p, b)) for p in POLICY_ORDER[1:] if g.get((p, b))
        }
        if "compression" not in comps:
            continue
        best_base = max(
            (p for p in comps if p != "compression"), key=comps.get
        )
        stats[str(b)] = {
            "primary_bm25": compare(b, "retrieval"),
            "strongest_alternative": compare(b, best_base),
        }
    (TAB / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---------- stats.tex: 双基线 (主对照 BM25 + 最强替代) ----------
    lines = [r"\begin{tabular}{llcccc}", r"\toprule",
             r"Budget & Baseline & $\Delta$EM & 95\% CI & McNemar $p$ \\",
             r"\midrule"]
    for b in budgets:
        s = stats.get(str(b))
        if not s:
            continue
        pairs = [("primary_bm25", "retrieval (BM25)")]
        alt = s["strongest_alternative"]
        if alt["baseline"] != "retrieval":  # 最强替代≠主对照时才加第二行
            pairs.append(("strongest_alternative", POLICY_TEX[alt["baseline"]]))
        for kind, name in pairs:
            c = s[kind]
            lo, hi = c["delta_ci95"]
            lines.append(
                f"{b} & {name} & "
                f"{c['compression_em']-c['baseline_em']:+.4f} & "
                f"[{lo:+.4f}, {hi:+.4f}] & {c['mcnemar']['p_value']:.4f} \\\\"
            )
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TAB / "stats.tex").write_text("\n".join(lines), encoding="utf-8")

    # ---------- headline.tex: 摘要/引言用的数字宏 ----------
    def fmt_pol(p: str) -> str:
        return POLICY_TEX[p].replace("\\", "").split(" (")[0]

    n_q = len({r["question_id"] for r in recs})
    fc = g.get(("full_context", None), [])
    fc_done = _fc_completed(fc)
    fc_foot = round(mean([r["memory_footprint_tokens"] for r in fc])) if fc else 0
    e2e_typ = f"{mean([r['e2e_ms'] for r in recs])/1000:.0f}" if recs else "0"
    access_typ = f"{max(mean([r['access_ms'] for r in g[(p, b)]]) for (p, b) in g if b):.0f}" if g else "0"
    comp_small = max(
        ((p, mean(vec(p, b))) for b in budgets[:1] for p in POLICY_ORDER[1:]
         if g.get((p, b))),
        key=lambda x: x[1], default=(None, 0),
    )
    large = budgets[-1] if budgets else None
    comp_large_em = mean(vec("compression", large)) if large else 0
    base_large = max(
        ((p, mean(vec(p, large))) for p in POLICY_ORDER[1:-1] if g.get((p, large))),
        key=lambda x: x[1], default=("retrieval_recency", 0),
    )
    fc_done_em = (mean([r.get("relaxed_em", 0.0) for r in fc_done])
                  if fc_done else 0.0)
    fc_done_e2e = mean([r["e2e_ms"] for r in fc_done]) / 1000 if fc_done else 0.0
    macros = [
        r"% auto-generated by analyze.py -- do not edit",
        rf"\newcommand{{\longmemN}}{{{n_q}}}",
        rf"\newcommand{{\compSmallWinner}}{{{fmt_pol(comp_small[0])}}}",
        rf"\newcommand{{\compLargeEM}}{{{comp_large_em:.4f}}}",
        rf"\newcommand{{\compLargeBaseEM}}{{{base_large[1]:.4f}}}",
        rf"\newcommand{{\compLargeBaseName}}{{{fmt_pol(base_large[0])}}}",
        rf"\newcommand{{\eTwoETypical}}{{{e2e_typ}}}",
        rf"\newcommand{{\accessTypical}}{{{access_typ}}}",
        rf"\newcommand{{\fcFoot}}{{{fc_foot:,}}}".replace(",", "\\,"),
        rf"\newcommand{{\nSessions}}{{{n_sessions}}}",
        rf"\newcommand{{\fcAtLarge}}{{{round(4096/max(fc_foot,1)*100, 1)}}}",
        # A1 完成子集口径: full-context 84/120 空调用不入均值
        rf"\newcommand{{\fcDoneN}}{{{len(fc_done)}}}",
        rf"\newcommand{{\fcDoneEM}}{{{fc_done_em:.4f}}}",
        rf"\newcommand{{\fcEmptyN}}{{{len(fc) - len(fc_done)}}}",
        rf"\newcommand{{\fcDoneEtwoE}}{{{fc_done_e2e:.0f}}}",
    ]
    (TAB / "headline.tex").write_text("\n".join(macros) + "\n", encoding="utf-8")

    # ---------- 图: relaxed EM vs budget + e2e 延迟 vs budget ----------
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(6, 4))
        for pol in POLICY_ORDER:
            bs = [b for b in budgets if g.get((pol, b))]
            if not bs:
                continue
            ys = [mean([r.get("relaxed_em", 0.0) for r in g[(pol, b)]]) for b in bs]
            if pol == "full_context":
                fc_done = _fc_completed(g.get(("full_context", None), []))
                if fc_done:
                    ax.axhline(mean([r.get("relaxed_em", 0.0) for r in fc_done]),
                               ls="--", lw=1, color="gray",
                               label="full-context (completed subset)")
                continue
            ax.plot(bs, ys, marker="o", label=pol)
        ax.set_xscale("log", base=2)
        ax.set_xticks(budgets)
        ax.set_xticklabels([str(b) for b in budgets])
        ax.set_xlabel("memory budget (cl100k tokens)")
        ax.set_ylabel("relaxed EM")
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(TAB / "fig_accuracy_vs_budget.pdf")
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(6, 4))
        for pol in POLICY_ORDER:
            bs = [b for b in budgets if g.get((pol, b))]
            if not bs or pol == "full_context":
                continue
            ys = [mean([r["e2e_ms"] for r in g[(pol, b)]]) / 1000 for b in bs]
            ax.plot(bs, ys, marker="s", label=pol)
        fc_done = _fc_completed(g.get(("full_context", None), []))
        if fc_done:
            ax.axhline(mean([r["e2e_ms"] for r in fc_done]) / 1000, ls="--",
                       lw=1, color="gray",
                       label="full-context (completed subset)")
        ax.set_xscale("log", base=2)
        ax.set_xticks(budgets)
        ax.set_xticklabels([str(b) for b in budgets])
        ax.set_xlabel("memory budget (cl100k tokens)")
        ax.set_ylabel("end-to-end latency (s)")
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(TAB / "fig_latency_vs_budget.pdf")
        plt.close(fig)
        print("figures written: fig_accuracy_vs_budget.pdf / fig_latency_vs_budget.pdf")
    except Exception as e:
        print(f"figure generation skipped: {e}")

    # ---------- 消融表 (评审回应) ----------
    # 写表保护: results.jsonl 只含主网格时, 消融/跨读者表会被写成退化版并覆盖
    # 此前由完整证据生成的产物。先登记本次记录里实际存在的策略, 再按表校验。
    _present_pols = {r["policy"] for r in recs}
    _warnings: list = []

    def _warn(msg: str) -> None:
        _warnings.append(msg)
        print("WARN " + msg)

    def cell(pol, b, metric="relaxed_em"):
        rs = g.get((pol, b), [])
        return mean([r.get(metric, 0.0) for r in rs]) if rs else None

    def row_of(pols, budgets_ab, label_map=None):
        rows_out = []
        for pol in pols:
            vals = [cell(pol, b) for b in budgets_ab]
            if all(v is None for v in vals):
                continue
            name = (label_map or {}).get(pol, pol)
            rows_out.append((name, budgets_ab, vals))
        return rows_out

    def emit_table(fname, header, rows_out, col_fmt="{v:.4f}",
                    required_pols=()):
        """写一张表；缺策略时保留上一版产物并告警。

        results.jsonl 只含主网格时，消融表会被写成单行或全 "--" 的退化版，
        覆盖掉此前由完整证据生成的表格。评审方「重跑复现」时不应破坏交付物，
        因此这里先检查该表依赖的策略是否齐备，不齐备就不落盘。
        """
        missing = [p for p in required_pols if p not in _present_pols]
        if missing:
            kept = "保留原文件" if (TAB / fname).exists() else "原文件不存在, 不生成"
            _warn(f"{fname}: 缺少策略 {missing}, 跳过写表({kept})")
            return
        if not rows_out:
            _warn(f"{fname}: 无可用数据行, 跳过写表")
            return
        lines = ["\\begin{tabular}{l" + "c" * len(header[1:]) + "}", "\\toprule",
                 " & ".join(header) + " \\\\", "\\midrule"]
        for name, bs, vals in rows_out:
            cells = [col_fmt.format(v=v) if v is not None else "--" for v in vals]
            lines.append(f"{name} & " + " & ".join(cells) + r" \\")
        lines += ["\\bottomrule", "\\end{tabular}"]
        (TAB / fname).write_text("\n".join(lines), encoding="utf-8")

    # ① 摘要长度
    emit_table(
        "ablation_summary_len.tex",
        ["Summarizer", "B=1024", "B=2048", "B=4096"],
        row_of(["compression@w20", "compression", "compression@w120"],
               (1024, 2048, 4096),
               {"compression@w20": "compression (20-word digests)",
                "compression": "compression (60-word digests)",
                "compression@w120": "compression (120-word digests)"}),
        required_pols=("compression@w20", "compression@w120"),
    )
    # ② 层级分配
    emit_table(
        "ablation_allocation.tex",
        ["Allocation (rec/sum/retr)", "B=2048", "B=4096"],
        row_of(["hierarchical_sumheavy", "hierarchical", "hierarchical_evidence"],
               (2048, 4096),
               {"hierarchical_sumheavy": "15/70/15 (summary-heavy)",
                "hierarchical": "25/50/25 (default)",
                "hierarchical_evidence": "40/20/40 (evidence-heavy)"}),
        required_pols=("hierarchical_sumheavy", "hierarchical_evidence"),
    )
    # ③ 检索族
    emit_table(
        "ablation_retrieval.tex",
        ["Retriever", "512", "1024", "2048", "4096"],
        row_of(["retrieval", "dense_retrieval", "hybrid_retrieval",
                "retrieval_recency"], tuple(budgets),
               {"retrieval": "BM25 (sparse)",
                "dense_retrieval": "dense (bge-small-en-v1.5, local)",
                "hybrid_retrieval": "hybrid (BM25+dense, RRF)",
                "retrieval_recency": "BM25 + recency half-budget"}),
        required_pols=("dense_retrieval", "hybrid_retrieval"),
    )
    # ③b 读取侧相关性感知 + 事件锚定检索 (评审回应新增的两条设计)
    #    compression_select : 摘要按与问题的相关性排序后装填, 而非纯取最近
    #    hierarchical_ev    : 三层分割不变, 检索腿换成事件锚定/时间信号排序
    emit_table(
        "ablation_readside.tex",
        ["Design", "512", "1024", "2048", "4096"],
        row_of(["compression", "compression_select",
                "hierarchical", "hierarchical_ev"], tuple(budgets),
               {"compression": "compression (newest digests)",
                "compression_select": "compression + relevance-ranked digests",
                "hierarchical": "hierarchical (BM25 leg)",
                "hierarchical_ev": "hierarchical + event-anchored leg"}),
        required_pols=("compression_select", "hierarchical_ev"),
    )

    # ③c 插件式强基线对比表 (评审弱点回应: 细粒度检索 / 先取后总结 / 相关性摘要 /
    #    事件锚定, 统一放在一张表里与各自父策略配对比较)
    plug_specs = [
        ("compression", "compression (window+summ.)", None),
        ("compression_select", "compression-select (relevance-ranked summ.)", "compression"),
        ("compression_fetch", "fetch-then-summarize (2-stage)", "compression"),
        ("retrieval", "retrieval (BM25, turn-level)", None),
        ("retrieval_sentence", "retrieval (BM25, sentence-level)", "retrieval"),
        ("hierarchical", "hierarchical (3-tier)", None),
        ("hierarchical_ev", "hierarchical + event/time-aware leg", "hierarchical"),
    ]
    _plug_missing = [p for p, _, par in plug_specs if par and p not in _present_pols]
    if _plug_missing:
        kept = "保留原文件" if (TAB / "plug_baselines.tex").exists() else "原文件不存在, 不生成"
        _warn(f"plug_baselines.tex: 缺少策略 {_plug_missing}, 跳过写表({kept})")
    else:
        lines = [
            r"\begin{tabular}{lcccc}", r"\toprule",
            r"Strategy & EM@512 & EM@2048 & EM@4096 & $\Delta$@4096 vs.\ parent "
            r"(95\% CI) \\", r"\midrule",
        ]
        for pol, label, parent in plug_specs:
            cells = []
            for b in (512, 2048, 4096):
                v = cell(pol, b, "em")
                cells.append(f"{v:.4f}" if v is not None else "--")
            if parent:
                a, base = vec(pol, 4096, "relaxed_em"), vec(parent, 4096, "relaxed_em")
                if a and base and len(a) == len(base):
                    (ma, mb_, _), ci = paired_bootstrap(a, base)
                    cells.append(f"{ma - mb_:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]")
                else:
                    cells.append("--")
            else:
                cells.append("(parent)")
            lines.append(f"{label} & " + " & ".join(cells) + r" \\")
        lines += [r"\bottomrule", r"\end{tabular}"]
        (TAB / "plug_baselines.tex").write_text("\n".join(lines), encoding="utf-8")

    # ④ 跨读者稳健性 (@m47/@m51/...): 用全部跨读者记录 (独立 60 题子集, 不受 120 样本过滤)
    import re as _re
    all_raw = [json.loads(l) for l in
               (OUT / "results.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rb = defaultdict(list)
    rb_models = {}   # 后缀 -> 记录里的 model 名（历史记录无 model 字段时留空走回退表）
    for r in all_raw:
        m = _re.match(r"^(.*)@(m\d+)$", r["policy"])
        if not m or not r["pred"].strip():
            continue
        pol, suffix = m.group(1), m.group(2)
        rb[(pol, r["budget"], suffix)].append(r["relaxed_em"])
        if r.get("model"):
            rb_models[suffix] = r["model"]

    def rb_cell(pol, b, suffix):
        v = rb.get((pol, b, suffix), [])
        return (sum(v) / len(v), len(v)) if v else None

    # 历史记录无 model 字段时的表头回退标签（仅展示用；新记录自带 model 字段）
    _LEGACY_SUFFIX_MODEL = {"m47": "GLM-4.7-Flash", "m51": "zai-org/GLM-5.1",
                            "m53": "glm5.3-flash"}

    BS = chr(92)  # 反斜杠, 避免源码转义歧义
    _suffixes = sorted({s for (_, _, s) in rb})
    if _suffixes:
        # 每个跨读者模型一张表 robustness_<suffix>.tex（不覆盖归档产物 robustness_model.tex）
        for suffix in _suffixes:
            alt_name = (rb_models.get(suffix)
                        or _LEGACY_SUFFIX_MODEL.get(suffix)
                        or resolve_model_names()["alt"])
            lines = [BS + "begin{tabular}{lcc}", BS + "toprule",
                     f"Policy ({alt_name}) & relaxed EM & $n$ " + BS + BS, BS + "midrule"]
            rb_rows = [("full_context", None, "full-context (verbatim)"),
                       ("retrieval_recency", 4096, "retrieval+recency @4096"),
                       ("hierarchical", 4096, "hierarchical (3-tier) @4096"),
                       ("retrieval", 4096, "retrieval (BM25) @4096"),
                       ("compression", 4096, "compression (window+summ.) @4096"),
                       ("retrieval_sentence", 4096, "retrieval (sentence-level) @4096"),
                       ("compression_select", 4096, "compression-select @4096"),
                       ("compression_fetch", 4096, "fetch-then-summarize @4096"),
                       ("hierarchical_ev", 4096, "hierarchical (event-aware) @4096")]
            for pol, b, label in rb_rows:
                c = rb_cell(pol, b, suffix)
                if c:
                    lines.append(f"{label} & {c[0]:.3f} & {c[1]} " + BS + BS)
                else:
                    lines.append(f"{label} & -- & -- " + BS + BS)
            lines += [BS + "bottomrule", BS + "end{tabular}"]
            fname = f"robustness_{suffix}.tex"
            (TAB / fname).write_text("\n".join(lines), encoding="utf-8")
    else:
        kept = "保留原文件" if (TAB / "robustness_model.tex").exists() else "原文件不存在, 不生成"
        _warn(f"robustness_model.tex: 无跨读者记录, 跳过写表({kept})")

    # ---------- 双指标统计 (relaxed 与 strict EM 各一套, 双基线) ----------
    # ③c 两处设计变更是否真的移动了结果: 配对 McNemar + bootstrap CI
    #    回答评审「可能低估了更具竞争力的设计」——直接测出来, 不靠推断
    # mcnemar_exact / paired_bootstrap 由模块顶部 import 提供；
    # 此处不再 import，否则同名会成为 main() 的局部变量，
    # 令上方 compare() 在 import 执行前取到未绑定的闭包单元。
    v2: dict = {}
    for new_p, base_p in (("compression_select", "compression"),
                          ("hierarchical_ev", "hierarchical"),
                          ("retrieval_sentence", "retrieval"),
                          ("compression_fetch", "compression")):
        per_b = {}
        for b in budgets:
            a, base = vec(new_p, b, "relaxed_em"), vec(base_p, b, "relaxed_em")
            if not a or not base or len(a) != len(base):
                continue
            (ma, mb_, p_gt), ci = paired_bootstrap(a, base)
            per_b[str(b)] = {"new": ma, "baseline": mb_, "delta": ma - mb_,
                             "delta_ci95": ci, "p_boot_greater": p_gt,
                             "mcnemar": mcnemar_exact(a, base)}
        if per_b:
            v2[f"{new_p}_vs_{base_p}"] = per_b
    if v2:
        (TAB / "readside_stats.json").write_text(
            json.dumps(v2, ensure_ascii=False, indent=2), encoding="utf-8")

    for metric, fname in (("em", "stats_strict.json"),):
        st = {}
        for b in budgets:
            comps = {p: mean(vec(p, b, metric)) for p in POLICY_ORDER[1:]
                     if g.get((p, b))}
            if "compression" not in comps:
                continue
            best_base = max((p for p in comps if p != "compression"),
                            key=comps.get)

            def cmp_strict(base_pol):
                a, base = vec("compression", b, metric), vec(base_pol, b, metric)
                (ma, mb_, p_gt), ci = paired_bootstrap(a, base)
                return {"baseline": base_pol, "metric": metric,
                        "compression": ma, "baseline": mb_,
                        "delta_ci95": ci, "p_boot_greater": p_gt,
                        "mcnemar": mcnemar_exact(a, base)}

            st[str(b)] = {"primary_bm25": cmp_strict("retrieval"),
                          "strongest_alternative": cmp_strict(best_base)}
        (TAB / fname).write_text(json.dumps(st, ensure_ascii=False, indent=2),
                                 encoding="utf-8")

    n_by = {f"{p}|{b}": len(v) for (p, b), v in g.items()}
    print(f"records={len(recs)} cells={n_by}")
    print(f"written: main/bytype/latency/stats.tex + headline.tex + stats.json -> {TAB}")
    if _warnings:
        print(f"guarded {len(_warnings)} table(s) (缺策略/缺记录, 已保留上一版产物):")
        for w in _warnings:
            print("  - " + w)
    else:
        print("all tables fully populated from current records")


if __name__ == "__main__":
    main()

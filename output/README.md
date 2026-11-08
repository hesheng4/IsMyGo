# 运行产物

本目录放 `logs/run.json` 那一次运行（run_id `agent-sci-2026-full500-015`）所依托的论文数字
结果文件，`run_id` 与日志、资源报告相同；`paper/paper.pdf` 是提交论文。按样例格式说明本次产物：

## 本次产物

- run_id：`agent-sci-2026-full500-015`（full500 复跑终扫批；论文主表数字 = 该轮全量 500 题累计）
- 生成稿：`final/paper.tex`（+ `final/paper.bib` / `.bbl` / `iclr2025_conference.{sty,bst}` / `final/tables*/`）
> **当前口径（2026-11-07 复核）**：定稿标题为 *The Memory Trilemma Under a Fixed Token Budget*，
> 主网格为 deepseek-v4.1-flash 500 题 / 25 格 / 12,500 条（`code/output/longmemeval/results.jsonl` 的 21 格 10,500 条
> + `results_r8.jsonl` / `results_r9.jsonl` 的读时压缩 4 格）；修复排版故障后 `final/paper.pdf` 为 **15 页 / 349,537 字节**，并另出**补充材料 3 页 / 174,106 字节**
> （`final/supplementary.pdf`）：评审窗口只读前 15 页，故 §8 Negative Results、§9 Selection Guideline
> 与 4 个实现细节附录移入补充材料；更早的 18 页版本是修复 8 处控制字符后的诚实排版。
> 本文件下面各节是历史沿革，凡与本节冲突处以本节为准。

- 提交的 PDF 如何来自该生成稿：`final/paper.tex` 经 pdflatex ×3 + bibtex 编译为 `final/paper.pdf`（15 页）+ `final/supplementary.pdf`（3 页），
  正文同步至提交位 `paper/paper.pdf`，补充材料留在本目录（`final/supplementary.pdf`）；正文数字全部来自下方结果文件，可重编译、可逐格复算
- 结果文件：本目录 `results.jsonl` 为**上一代** mimo-v2.6-flash 120 题 / 21 格 / 2,520 条；
  论文主网格的 14,066 条逐题记录在 `code/output/longmemeval/results.jsonl`
  （deepseek-v4.1-flash 10,500 + mimo 2,520 + 弃用代际 glm5.3-flash 1,046）、`tables/`（论文全部表格的 tex/json 源）
- 中间结果：`run_manifest.json`（实验段产物清单与 SHA256）、`glm_supplementary/`（第二/第三读者补充证据）、
  `archive/`（历史归档：GLM-4-Flash 主网格、引擎运行时日志）

> 以下为各目录的历史口径与详细说明（含 10-16 重写轮与 10-18 主网格升级轮的沿革）：

> **2026-10-16 全新结构重写（mimo 主数据 + GLM 补充）**：`final/` 已更新为**全新 11 章结构定稿**
> （章节由 9 → 11：原 Method+Setup 合并为 §3 Study Design；原 Analysis 拆为 §5 机制解读 +
> §6「读侧瓶颈」独立章；选型规则升为 §9 独立章。主数据 mimo-v2.6-flash 2,520 条；GLM-4-Flash
> 整张主网格作第二读者鲁棒性、GLM-4.7-Flash 冻结产物作第三读者探针，均为补充、从不与主网格混用）。
> **正文全部重写，数字与表格未变**：本轮离线重聚合三代际（mimo/GLM/archive）并逐格独立复算，
> 与论文/README 完全一致；8 张主表重跑后与重写前**逐字节相同**（SHA256）。`paper/paper.pdf` 同步更新。
> 重写前 9 章版及原始产物备份于工作区根 `_backup_qwenwork_20261016/`（未随包提交；更早的 7 页
> mimo 单读者版备份同未随包）。GLM 补充证据原始记录见 `glm_supplementary/`。
> 编译：本机以 **tectonic 0.17（XeTeX）** 编译得 **15 页 / 0 错误 / 0 未定义引用 / 0 overfull / 23 文献**
> （重写轮当轮口径；10-18 轮主网格升级后扩至 35 篇，见 `resource_report.md` 更新注）；
> **2026-10-25 两轮评审回应**：pdflatex 重编译（第二轮后 15 页整，含 per-type 配对表/构造 token 账目/
> at-a-glance 表/Proxy-scope 局限/judge 按型表/compselect 按型分解；零 API 消耗）。早期记录见 git 历史。正文 15 页现由 **pdflatex 实测**得到（不再有 tectonic 推断成分）：
> `\linespread{0.97}`，正文已无附录，§8/§9 与 4 个实现细节附录移入 `final/supplementary.pdf`（3 页）。
> 验收见 `final/audit_report.txt`（2026-11-08 重写：§3 编译实测 / §4 修复清单 / §5 页数口径）。
>
> 以下为重构前的历史说明（`run_manifest.json` 为 2026-10-15 运行时点清单）。

本目录放两段产物：①**实验段**（run_id `agent-sci-2026-comp-001`，`run.py --full`）写出的结果文件
（`results.jsonl` + `tables/` + `run_manifest.json`），即论文全部数字的来源；②**论文写作段**
（run_id `paper-gen-15p-20261016`，`paper_gen_llm.py`）的定稿 `final/`。`logs/run.json` 记录的是
**写作段**那次运行（样例口径：产生论文的那一次），其 `output_paper` = `paper/paper.pdf` = `final/paper.pdf`。

---

## 本次产物

| 项 | 值 |
|---|---|
| 实验段 run_id | `agent-sci-2026-comp-001`（`run.py --full`，产生 `results.jsonl` 论文数字） |
| 写作段 run_id | `paper-gen-15p-20261016`（`paper_gen_llm.py`，= `logs/run.json`，产生论文） |
| 生成稿 | `final/paper.tex`（15 页定稿源）→ 编译为 `final/paper.pdf` = `paper/paper.pdf` |
| 结果文件 | `results.jsonl`（2,520 条逐题记录）、`tables/main.csv`（主表 CSV 版） |
| 中间结果 | `draft/outline.md`（大纲）、`draft/run_summary.md` |
| 运行清单 | `run_manifest.json`（实验段产物字节数 + SHA256；`README.md` 与自身不计入） |
| 归档代际流水 | `archive/results_archive.jsonl`（7,399 条） |
| GLM 补充证据 | `glm_supplementary/`（第二读者 `results_glm.jsonl` + GLM `tables/`，见其 README） |

**一致性**：`results.jsonl` 与 `tables/main.tex` 逐格一致（20/20 单元格），两者同属**实验段**
`agent-sci-2026-comp-001` 运行；**写作段** `paper-gen-15p-20261016`（= `logs/run.json`）据此生成定稿。

---

## 目录结构

```
output/
├── final/                    论文定稿（15 页，mimo 主数据 + GLM 补充，= paper/paper.pdf）
├── results.jsonl             实验段逐题记录（2,520 条，mimo-v2.6-flash）
├── run_manifest.json         产物清单 + 校验和（实验段 agent-sci-2026-comp-001）
├── glm_supplementary/        GLM 第二/第三读者补充证据（results_glm.jsonl + GLM tables/）
├── archive/                  归档代际流水（results_archive.jsonl，限流风暴代际）
├── draft/
│   ├── outline.md            论文大纲
│   └── run_summary.md        实验段运行摘要
└── tables/                   25 个文件（论文 \input 的表格/图件 + 判读 json）
    ├── main.csv              表 2 的 CSV 版
    ├── headline.tex          正文引用的宏（\fcDoneN / \fcDoneEM 等）
    ├── main.tex              Table 1（EM / EM_rel / token-F1）
    ├── consolidated_emrel.tex Table 2（relaxed EM + 95% CI）
    ├── bytype.tex            Table 3（分题型）
    ├── latency.tex           Table 4（访问延迟 / 端到端延迟 / 内存足迹）
    ├── stats.tex             Table 5（配对 bootstrap CI + McNemar）
    ├── struct_compressor.tex Table 6（结构化压缩器）
    ├── retrieval_diagnosis.tex Table 7（失败定位）
    ├── retrieval_ranking.tex Table 8（session 级排名）
    ├── rerank_eval.tex       Table 9（重排器探针）
    ├── ablation_*.tex        Table 10–12（敏感性消融）
    ├── robustness_model.tex  Table 13（跨读者复跑）
    ├── fig_accuracy_vs_budget.pdf   Figure 1 左
    ├── fig_latency_vs_budget.pdf    Figure 1 右
    └── *.json                判读结果（judge / rerank / struct / ranking / stats）
```

---

## 与提交论文 `paper/paper.pdf` 的关系

`paper/paper.pdf` = `final/` 定稿（15 页，mimo 主数据 + GLM 补充）。本目录的 `results.jsonl`
（**2,520 条，mimo-v2.6-flash**）与 `tables/` 是论文全部数字的来源，与论文主表逐格一致。

本目录实验运行是真实 LLM 全量重跑（120 题 × 6 策略 × 4 预算 + full-context = 21 格，
答题器 mimo-v2.6-flash，零空预测）。主网格 relaxed EM（与论文 Table 1/2 逐格一致）：

| 策略 | B=512 | B=1024 | B=2048 | B=4096 |
|---|---|---|---|---|
| sliding window | 0.025 | 0.025 | 0.058 | 0.050 |
| retrieval (BM25) | 0.283 | 0.342 | 0.350 | 0.408 |
| retrieval+recency | 0.258 | 0.308 | 0.325 | 0.342 |
| compression | 0.067 | 0.125 | 0.175 | 0.317 |
| hierarchical | 0.150 | 0.258 | 0.333 | 0.417 |
| full-context（无预算，参照上界） | — | — | — | 0.475 |

**论文主结论在本次 mimo 运行中成立：**

1. 压缩单独使用在 512–2048 每档显著劣于 BM25（McNemar p≤0.0002），4096 与 retrieval
   不可区分（p=0.099）但仍低于 hierarchical（p=0.036）。
2. 分层引擎随预算单调上升（0.150 → 0.258 → 0.333 → 0.417），4096 为受限策略中最优。
3. full-context 精度最高（0.475）但 ~25× token / ~5× 延迟，为参照上界而非可部署策略。

> **代际说明**：本目录 `results.jsonl` 为 **mimo 代际**（2,520 条，论文主数据，与 `tables/`
> 同源）。GLM-4-Flash 第二读者全网格作补充证据存于 `glm_supplementary/`；GLM 代际主网格历史值
> （full-context 0.2917、hierarchical@4096 0.325 等）仅用于论文 §6.7 跨读者对比，**不进入主表**。
> 归档限流风暴代际（full-context 完成 36/120）见 `archive/results_archive.jsonl` 与
> `tables/fc_archive_absolutes.tex`，正文 Table 2 用两行并列呈现，可复核。

---

## 哪些文件来自本次运行

| 来源 | 文件 | 说明 |
|---|---|---|
| **本次运行新产出**（21 个） | `results.jsonl`、`main.csv`、`headline.tex`、`main.tex`、`consolidated_emrel.tex`、`bytype.tex`、`latency.tex`、`stats.tex`、`stats.json`、`stats_strict.json`、`fig_*.pdf`、`draft/*` | 由 `run.py --full --log-run` → `analyze.py` 生成 |
| **归档代际重算**（5 个） | `ablation_summary_len.tex`、`ablation_allocation.tex`、`ablation_retrieval.tex`、`robustness_model.tex`、`fc_archive_absolutes.tex` | 这四张表需要摘要词长消融 / 层级分配变体 / dense·hybrid 检索 / 跨读者复跑，本次 `--full` 未跑这些策略；由 2026-10-16 复现的实验阶段从真实记录重新聚合核验（重生成表见 `code/output/longmemeval/tables/`，表注标注来源） |
| **沿用原证据**（8 个） | `struct_compressor.tex`、`struct_eval.json`、`retrieval_diagnosis.*`、`retrieval_ranking.*`、`rerank_*.{tex,json}`、`judge_full.json`、`token_accounting.json` | 由独立的修订轮实验（E1–E4）产出，本次未重跑，内容未变（哈希一致） |

---

## 生成链路（两段式）

```bash
# ① 实验段（真实 LLM，mimo-v2.6-flash，约 3 小时 / 23,194,392 token）
#    产生论文全部数字；该段 run.json 备份未随包提交，对账见 resource_report.md §1.2
cd code/experiments/longmemeval
python run.py --full --log-run --fresh   # -> code/output/longmemeval/results.jsonl（2,520 条）
python analyze.py                        # -> code/output/longmemeval/tables/*
#    （results.jsonl 与 tables/ 同步到本 output/ 目录）

# ② 论文写作段（真实 LLM，约 14 分钟 / 113,530 token）——= logs/run.json 记录的那次运行
RUN_ID=paper-gen-15p-20261016 RUN_LOG_DIR=../../logs python paper_gen_llm.py
#    -> output/final_15p/（定稿三件套），归档为 output/final/ 并同步 paper/paper.pdf
#    -> logs/{run.json,calls.jsonl}（17 次逐章生成/修订调用）
```

> `logs/run.json`+`calls.jsonl` 记录的是**写作段**（产生论文的那一次运行，样例口径）；
> 实验段消耗见 `resource_report.md` §1（累计）与 §1.1 注③。

---

## 未打包的内容及原因

| 内容 | 大小 | 未打包原因 |
|---|---|---|
| `code/output/longmemeval/cache/`（LLM 调用缓存） | 5,409 个 JSON | 断点续跑用中间缓存，非论文依据；可由 `run.py` 重建 |
| LongMemEval 数据集 | 264.5 MiB | 超提交包体积上限；获取方式见 `data/README.md` |
| 本地向量/重排模型（bge-*） | 数百 MB | 仅 E1/E2/E3 消融需要；获取方式见 `data/README.md` §2.2 |
| `code/output/longmemeval/results_kv.jsonl` / `results_edu.jsonl` | 各 ~198 KB | 结构化压缩器（Table 6）的独立记录，本次未重跑，仍在 `code/output/longmemeval/` |

> 论文引用的全部表格与图件均已在 `output/tables/` 内，无缺失。

---

## 2026-10-16 定稿：`final/`（15 页，mimo 主数据 + GLM 补充）

`final/` 为当前提交定稿（= `paper/paper.pdf`）。其章节正文由**论文写作段**
`paper-gen-15p-20261016`（`paper_gen_llm.py`，见 `logs/`）用真实 LLM 逐章生成，随后一次编辑
pass 重构为「mimo 主数据 + GLM 补充」并定稿：

| 文件 | 说明 |
|---|---|
| `final/paper.pdf` | 定稿正文 PDF（**349,537 字节**，2026-11-08 构建，pdflatex 编译 **15 页**）= `paper/paper.pdf` |
| `final/paper.tex` + `paper.bbl` + `paper.bib` + `iclr2025_conference.{sty,bst}` + `final/tables/` | 可独立重编译源（pdflatex ×3 + bibtex 实测 **15 页** / 0 错误 / 0 未定义引用 / 0 overfull；补充材料另 3 页，页数口径见 `final/audit_report.txt` §5） |
| `final/audit_report.txt` | 验收审计（页数、引用、GLM 仅作补充、数字溯源） |
| `final/README.md` | 数据口径与 `tables/` 清单 |

- **结构**（全新 11 章）：摘要 + §1 Introduction + §2 Related Work and Positioning +
  §3 Study Design（合并原 Method+Setup）+ §4 The Accuracy–Cost–Latency Frontier（Results 四小节）+
  §5 Why No Strategy Dominates（机制 C1–C4）+ §6 The Bottleneck Is Reading, Not Retrieval（核心洞见独立章）+
  §7 Robustness（消融 + 跨读者）+ §8 Negative Results（N1–N6）+ §9 A Practical Selection Guideline（独立章）+
  §10 Limitations + §11 Conclusion + 参考文献（**23 条**）+ 附录 A–E（含 Appendix C 第二读者 GLM-4-Flash 全网格）。
- **主数据**：mimo-v2.6-flash，`results.jsonl` 2,520 条（21 格 × 120，零空预测）；正文
  Table 1–5、Figure 1、Appendix B 全网格逐格溯源到 `tables/`。
- **补充数据**：GLM-4-Flash 整张主网格（第二读者，原始记录在 `glm_supplementary/`，派生表
  `final/tables/second_reader_glm.tex`、`reader_comparison.tex`）；GLM-4.7-Flash 冻结产物
  60 题探针（第三读者，`robustness_model.tex`）。均为补充、从不与主网格混用。
- 历史 7 页 mimo 单读者版（旧 `final/`）与旧 `final_15p/` 已不在包内；相关备份目录亦未随包提交。

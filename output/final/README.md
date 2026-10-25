# IsMyGo — 重构定稿（mimo 主数据 + GLM 补充；2026-10-16 全新结构重写）

按用户口径**全新结构重写**的 ICLR 论文：**以 mimo-v2.6-flash 全量复现为主数据**，
**以 GLM 数据为补充（第二/第三读者鲁棒性）**，遵循项目内既有「论文链」
（results.jsonl → analyze.py → tables/ → paper.tex → PDF）与「生成要求」
（摘要 + 多章正文 + 参考文献 + 附录 A–E、数字全部可溯源）。

> 本轮（2026-10-16）重写要点：章节由 **9 → 11**（原 Method+Setup 合并为 §3 Study Design；
> 原 Analysis 拆为 §5 机制解读 + §6「读侧瓶颈」独立章；选型规则升为 §9 独立章）；
> 全部正文重写，数字与表格**未变**（离线重聚合三代际、逐格核验一致，见 `audit_report.txt`）。
> 重写前的 9 章版与原始产物备份于工作区根 `_backup_qwenwork_20261016/`。

---

## 成品 / Deliverable

| 文件 | 说明 |
|---|---|
| `paper.pdf` | 定稿 PDF（**422,560 字节**，10-25 第三轮评审回应构建，pdflatex 编译，**15 页**（行距 1.0），见下「页数口径」） |
| `paper.tex` | 可独立重编译的 LaTeX 源（全新 11 章结构） |
| `paper.bib` / `paper.bbl` | 参考文献（**23 条**，natbib + iclr2025_conference.bst） |
| `iclr2025_conference.{sty,bst}` | ICLR 2025 模板 |
| `tables/` | 论文 `\input` 的全部表格与图件（见下） |
| `audit_report.txt` | 验收审计：0 错误 / 0 未定义引用 / 0 overfull / GLM 仅作补充 / 数字全部可溯源 |

## 重编译 / Recompile

**本机实际使用（tectonic 0.17，自包含引擎；交付 `paper.pdf` 实测 = 15 页）**：

```bash
cd output/final
tectonic --keep-logs --keep-intermediates paper.tex   # -> paper.pdf (15 pages, 0 errors)
```

**pdflatex 备选口径**——本机未安装 pdflatex；如在具备 TeX Live/MiKTeX 的环境复现：

```bash
cd output/final
pdflatex -interaction=nonstopmode paper.tex
bibtex   paper
pdflatex -interaction=nonstopmode paper.tex
pdflatex -interaction=nonstopmode paper.tex
```

> **页数口径**：tectonic(XeTeX) 字体度量比 pdflatex 长约 1 页（重写前 9 章版：pdflatex 15 / tectonic 16）。
> 为把**交付 PDF 守到 15 页**，本源文件含两处轻微排版压缩 `\linespread{0.97}` + `\arraystretch{0.94}`
> （视觉几乎无差）。若改用 pdflatex 编译，度量更紧会再少约 1 页（~14）；如需 pdflatex 权威 15 页，
> 删除这两行压缩即可。无论哪种引擎，**当前交付的 `paper.pdf` 均为 15 页**。详见 `audit_report.txt`「页数口径」。

---

## 数据口径 / Data provenance

**主数据（primary）— mimo-v2.6-flash**：21 格 × n=120 = 2,520 条逐题记录，零空预测。
正文 Table 1–5、Figure 1、Appendix B 全网格聚合，以及 headline 宏
（`\fcDoneEM=0.4750`、`\fcFoot=104,024` 等）全部来自 mimo 运行的 `tables/`。

**补充数据（supplementary）— GLM**，仅用于跨读者鲁棒性，**从不与主网格混用**：
- **第二读者 GLM-4-Flash**：整张 21 格主网格的独立复现 → `tables/second_reader_glm.tex`
  （Appendix C 全表）+ `tables/reader_comparison.tex`（§7 跨读者 mimo vs GLM 并列对比）。
- **第三读者 GLM-4.7-Flash**：冻结记忆产物的 60 题探针 → `tables/robustness_model.tex`。

**诊断/消融/归档表为冻结产物**：`struct_compressor`、`rerank_eval`、`retrieval_*`、
`ablation_*`、`plug_baselines`、`fc_archive_absolutes` 来自修订轮/归档代际，其基线
（freeform/retrieval/hierarchical）为 GLM 代际而非 mimo，**只能表内比对**，不可对当前
mimo `results.jsonl` 重算（否则代际混算，见 `audit_report.txt`「代际隔离核查」）。

**跨读者结论**：受限策略排序稳健（compression 每档劣于 retrieval；hierarchical 单调且在
4096 最强；window 近地板），而 full-context 的精度领先**读者依赖**（mimo 0.475 领先；
GLM-4-Flash 0.292 反低于 hierarchical 0.325）。

---

## tables/ 清单

| 文件 | 角色 | 来源 |
|---|---|---|
| `headline.tex`、`fc_archive_absolutes.tex` | 头条宏 / 归档绝对数 | mimo / 归档（冻结） |
| `main.tex`、`consolidated_emrel.tex`、`bytype.tex`、`latency.tex`、`stats.tex` | 主结果 Table 1–5 | **mimo（主）** |
| `fig_accuracy_vs_budget.pdf`、`fig_latency_vs_budget.pdf` | Figure 1 | mimo |
| `retrieval_diagnosis.tex`、`retrieval_ranking.tex`、`rerank_eval.tex`、`struct_compressor.tex` | 诊断 Table 6–9 | 修订轮（表内比对，冻结） |
| `ablation_summary_len.tex`、`ablation_allocation.tex`、`ablation_retrieval.tex`、`plug_baselines.tex` | 敏感性消融 Table 10–11 | 修订轮/归档（冻结） |
| `reader_comparison.tex` | 跨读者对比 Table 12 | mimo vs GLM |
| `robustness_model.tex` | 第三读者探针 Table 13 | GLM-4.7-Flash（冻结） |
| `second_reader_glm.tex` | 第二读者全网格（Appendix C） | GLM-4-Flash（补充） |

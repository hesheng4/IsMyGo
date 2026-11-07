# output/final — 论文定稿（当前代际）

**标题**：The Memory Trilemma Under a Fixed Token Budget: Accuracy, Cost, and Latency
Trade-offs on LongMemEval-S
**源文件**：`paper.tex`（1,179 行）；**构建产物**：`paper.pdf`（18 页 / 423,892 字节 / 0 错误）
**打包副本**：`paper/paper.pdf`

## 1. 数据口径（2026-11-07 校准）

主网格 = **deepseek-v4.1-flash，500 题，25 格 × 500 = 12,500 条习题级记录**，分布在三个文件：

| 文件 | 内容 | 行数 |
|---|---|---|
| `code/output/longmemeval/results.jsonl` | 21 格 × 500（5 策略 × 4 预算 + full-context 1 格） | 10,500 |
| `results_r8.jsonl` | 读时压缩变体 `compression_select` 的 1024 / 4096 两格 | 1,000 |
| `results_r9.jsonl` | 读时压缩变体 `compression_select` 的 512 / 2048 两格 | 1,000 |

`results.jsonl` 内另有 mimo-v2.6-flash 120 题 21 格（2,520 条）与 glm5.3-flash 未跑完的 1,046 条，
**它们不参与正文主表**，只在与 `results_glm*` 相关的补充段落里使用。

上一代（mimo 120 题 / 21 格 / 2,520 条）的表格已冻结到 `tables/legacy_120q/`，见该目录 `NOTE.md`。

## 2. 目录结构

| 路径 | 角色 |
|---|---|
| `paper.tex` | 唯一论文源；主表全部来自 `tables500/` |
| `tables500/` | **当前代际**主表（11 个 `\input`：headline, main, latency, stats, bytype, type_paired, diag, tight, probes, cross, reader_comparison） |
| `tables/` | 6 个仍被引用的**冻结消融件**（fc_archive_absolutes, ablation_summary_len, ablation_allocation, ablation_retrieval, plug_baselines, judge_type）+ `legacy_120q/` |
| `paper.bib` / `paper.bbl` | 参考文献；`iclr2025_conference.{sty,bst}` ICLR 模板 |
| `reviewer_response_r9.md` | 对审稿意见的答复（含 21→25 格扩容说明，§327） |
| `audit_report.txt` | 2026-10 的旧审计快照；其「0 errors」结论**只对旧构建成立**，见 §4 |

## 3. 构建

```
pdflatex -interaction=nonstopmode paper.tex
bibtex paper
pdflatex -interaction=nonstopmode paper.tex
pdflatex -interaction=nonstopmode paper.tex
```

- pdflatex：`D:\MikTex\miktex\bin\x64\pdflatex.exe`（本机已装，`output/final/README` 旧版「本机未安装 pdflatex」为误记）。
- 历史教训：2026-11-07 之前的源码带 8 处控制字节损坏，加 `-halt-on-error` 会让首轮中断并留下
  半截 `.aux`，随后 `bibtex` 报 `I found no \bibstyle command` 并级联出 27 个假错误。
  这 8 处已全部修好（见 §4），现在 `-halt-on-error` 也可用，但仍建议 nonstopmode。
- 期望结果：`Output written on paper.pdf (18 pages, ...)`，`^!` 计数 0，未定义引用 0。

## 4. 2026-11-07 修复记录

| 位置 | 缺陷 | 处理 |
|---|---|---|
| `tables500/type_paired.tex` | 每行之间夹空行（`tabular` 被提前结束）→ `Misplaced \noalign`、`\begin{document} ended by \end{table}` 等 25 个错误；末行缺 `\\` | 去空行、补行尾 `\\` |
| `paper.tex`（行 ~590） | `<0x08>egin{table}` 控制字节，`\begin{table}` 丢失 → `\centering\scriptsize` 泄漏到正文，第 9 页起整段变 6–8 千字符/页的小字 | 恢复为 `\begin{table}[htbp]` |
| `paper.tex` | `$<0x07>pprox$57`、`i.e.\ \approx$57\,k$`、`\approx$4$\,h`、`\approx$57$\,k` | 统一为 `$\approx 57\,k$` 等规范写法 |
| `paper.tex` | `Table~` + 换行 + `ef{tab:typepaired}`（`\r` 吞掉 `\ref` 的反斜杠） | 恢复 `Table~\ref{tab:typepaired}` |
| `paper.tex`（5 处） | `<0x09>` 控制字节：`\t` 被当成 TAB 写回，`\texttt` → `texttt`、`\times` → `times`，PDF 里印成 “exttttype paired.py”“2.6imes” | 恢复为 `\texttt` / `\times` |
| 附录 D 溯源段 | 声称「The main grid is results.jsonl (12,500 rows)」——没有文件有 12,500 行 | 改为 21 格 × 500 = 10,500 在 results.jsonl，读时压缩 4 格在 r8/r9，合计 25 格 / 12,500 行跨三个文件 |

**页数变化 15 → 18**：旧 PDF 的 15 页是靠上述 `\scriptsize` 泄漏「压」出来的
（旧构建 p9–p15 每页 6,619–8,258 字符，新构建 4,413–5,103 字符；两版提取文本总量
82,354 vs 83,423 字符，内容未增删）。新构建是同一份论文的诚实排版。
若提交确需 15 页，应删减附录而非恢复故障排版。

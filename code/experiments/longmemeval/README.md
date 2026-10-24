# longmemeval/ 目录导读（核心链路 vs 一次性脚本）

本目录共 58 个 py 文件：**复现论文只需要下面 7 个核心文件**，其余是历轮评审回应
（E1–E4、r7–r9、rebuttal）与诊断遗留的一次性脚本，保留作审计线索，不参与主链路。

## 核心链路（论文数字与成稿）

| 文件 | 职责 |
|---|---|
| `common.py` | 抽样（120 题分层 / `--full500` 全量）与预算切分、模型配置解析 |
| `llm.py` | LLM 调用 / 缓存命名空间 / 用量日志 |
| `policies.py` | 六策略实现（full-context / 滑窗 / BM25 检索 / recency 检索 / 压缩 / 分层） |
| `score.py` | EM / relaxed EM / token-F1、bootstrap 与 McNemar |
| `run.py` | 主网格执行（`--full` 120 题 / `--full500` 全量 / `--smoke` 冒烟） |
| `analyze.py` | 从 `results.jsonl` 生成全部表格与图（论文数字唯一聚合入口） |
| `paper_gen_llm.py` | 论文写作段（逐章生成 + 修订，产 15 页定稿） |

## 一次性 / 诊断脚本（按前缀识别）

- `_*.py`：私有探针（`_breakeven`、`_d3_audit`、`_matched_pair`、`_reconcile` 等）
- `r8_*` / `r9_*`：第 8/9 轮评审回应的表格与复算脚本
- `*_probe.py` / `*_audit.py` / `*_diag*.py`：单点诊断（oracle、迭代、JSON、qexp 等）
- `rebuttal_*` / `revision_tables.py`：rebuttal 阶段表格
- `cleanup_mimo.py` / `e0_cleanup.py` / `refill_empty.py` / `summaries_fill.py`：数据清理与补全
- `locomo_*` / `f500_*`：跨数据集（LoCoMo）探针与全量 500 题网格脚本
- 其余（`gen_policy_fig`、`latency_calib`、`regen_figures` 等）：图表与标定辅助

对应的探针产物在 `../../output/longmemeval/`（`results_*.jsonl`、`r8/r9_*.json` 等），
与主产物 `results.jsonl`（14,066 条，主读者 deepseek-v4.1-flash 10,500 条）并列存放；
各轮消耗对账见包根 `resource_report.md` §1.2/§1.3。

## locomeval/（同级输出目录）

`../../output/locomeval/` 是 **LoCoMo 跨数据集探针**的产物（deepseek-v4.1-flash 读者，
retrieval/compression/hierarchical × 1024/2048/4096），由 `locomo_probe.py` 产出、
`locomo_analyze.py` 聚合——属泛化性补充证据，非论文主网格。

# IsMyGo · Agent 科研短论文自动生成系统

CCF BDCI 2026 华为 openJiuwen 赛题三「Agent 科研短论文自动生成」参赛项目。
选题方向：**Agent 记忆引擎设计**——长程流式任务中的记忆策略权衡。

论文：*The Memory Trilemma Under a Fixed Token Budget: Accuracy, Cost, and Latency
Trade-offs on LongMemEval-S*（ICLR 模板，正文 15 页，`paper/paper.pdf`；补充材料 3 页，`output/final/supplementary.pdf`）

## 这是什么

一套**两段式科研流水线**：实验段在 LongMemEval-S 上对 6 种记忆策略
（full-context / 滑窗 / BM25 检索 / recency 检索 / 压缩 / 分层）做同预算受控对比，
写作段依据实验落盘数据生成零幻觉论文。数字纪律是核心约束：无论哪条成稿路径，
论文数字必须溯源到逐题记录：主网格在 `code/output/longmemeval/results.jsonl`
（21 格 × 500 = 10,500 条），读时压缩变体的 4 格在 `results_r8.jsonl` / `results_r9.jsonl`。

**主数据口径**：deepseek-v4.1-flash 全量 500 题主网格（25 格 × 500 = 12,500 条，跨上述三个文件）
为主读者，mimo-v2.6-flash（120 题整网格，2,520 条）为副读者。

**核心发现**：预算受限下无全能策略——小预算检索领先、分层策略随预算单调上升、
压缩单独使用劣于 BM25；瓶颈在**读取侧**而非检索排序（重排器把离线 Recall@5 从
0.834 提到 0.954，在线准确率却不变）。

## 目录结构（按复赛提交样例）

```
IsMyGo/
├── Agentic Reviewer/        # PaperReview access token（有意公开，供评审验证）
├── paper/paper.pdf          # 提交论文（正文 15 页）+ 补充材料（3 页）
├── code/                    # 源码；复现说明见 code/README.md（八节，与样例对应）
├── data/                    # 数据说明与获取方式（数据集 264.5 MiB 可重获）
├── logs/                    # 产生论文结果那次运行的程序日志（run.json + calls.jsonl）
├── output/                  # 运行产物：定稿源与表格；results.jsonl 为上一代 120 题（2,520 条）
├── docs/                    # 架构设计 / 模块调用 / 创新点
├── resource_report.md       # 资源报告（按 终扫批 run_id 逐项对账；披露写作段日志被覆盖）
└── framework_contribution.md # openJiuwen 框架贡献（paper_guard Rails，MR !5577）
```

## 快速开始

```bash
pip install -r code/requirements.txt

# ① 零 LLM 确定性路径（约 10 秒，验证环境，无需密钥）
python code/main.py

# ② 离线测试套件（不访问网络）
python -m pytest code/tests -q        # 69 passed / 1 skipped（需先装 requirements）

# ③ 完整复现（真实 LLM，两段式）——命令与环境见 code/README.md §6
python code/main.py --paper-run
```

统一 LLM 配置只读一处：`~/.jiuwenswarm/config/config.yaml`
（模板 `code/config/config.yaml.example`，密钥不入库）。

大数据与本地模型按需获取（带校验、幂等）：

```bash
python code/scripts/fetch_data.py --check      # LongMemEval-S 数据集（SHA256 校验）
python code/scripts/fetch_models.py --check    # 三个 bge 模型（仅 Table 9/12 消融需要）
```

## 更多文档

| 想了解 | 看 |
|---|---|
| 完整复现指南（环境/命令/换模型/换题/对账） | [`code/README.md`](code/README.md) |
| 分步复现（含引擎 SwarmFlow 路径） | [`code/run_guide.md`](code/run_guide.md) |
| 架构设计（四模块 + 调度 + FARS 三优化） | [`docs/architecture.md`](docs/architecture.md) |
| openJiuwen 模块调用 / 创新点 | [`docs/module_call.md`](docs/module_call.md) · [`docs/innovation.md`](docs/innovation.md) |
| 资源消耗与运行对账 | [`resource_report.md`](resource_report.md) |
| 运行产物构成 | [`output/README.md`](output/README.md) |
| 框架贡献与 MR | [`framework_contribution.md`](framework_contribution.md) |

按提交样例打包：`python code/scripts/make_submission.py --name 队伍名`
（自动排除 git/IDE/临时文件，核验样例 9 项必备成员）。

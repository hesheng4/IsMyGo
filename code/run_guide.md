# 复现指南（Reproduction Guide）

> 目标：从零复现本技术包的四个层次——①确定性实验真值、②主系统全流程
> （论文+图表+日志）、③离线测试套件、④JiuwenSwarm 引擎内 agentic 运行
> 与 Rail 生效证明。每步均给出预期输出，便于逐层验收。

## 0. 环境要求

| 层次 | 解释器 | 依赖 | 实测版本 |
|------|--------|------|----------|
| ①②③ 主系统/实验/测试 | Python ≥ 3.10 | **纯标准库**（`requirements.txt` 仅开发工具） | CPython 3.14.0（Windows 11） |
| ④ 引擎 agentic 路径 | Python ≥ 3.11 且 < 3.14 | `jiuwenswarm` 0.2.3 + `openjiuwen`（pip 自动带入） | miniconda base 3.11+ |
| PDF 编译（可选） | — | pdflatex + bibtex（本仓库实测 MiKTeX 26.5）或 pandoc | MiKTeX (Windows) |

两套解释器互不冲突：主系统代码不依赖引擎，引擎代码不在主系统 venv 内运行。

## 1. 复现实验真值（output/results.json）

```bash
cd paper-lab
python experiments/run_all.py            # 或 --quick 快速档
type output\results.json
```

预期：`meta.deterministic=true`；六策略 × 三预算 × 三种子（42/43/44），
关键值 `full_context@64 accuracy=1.0000`、`compression@64 accuracy=0.5245`、
`hierarchical@64 accuracy=0.3136`。同机重复运行数值逐位一致。

## 2. 复现主系统（论文 + 图表 + 运行日志，零 LLM）

```bash
python system/run_system.py              # 约 1.7s
```

预期产出：
- `paper_system/paper_memory_engine.md`（含 `## 摘要`…`## 参考文献` 九段式）
- `charts_system/fig1–fig4_*.png`
- `logs_system/run_log.json`（含 FARS 三优化指标：Token 降本 84.1%、
  假设门控 novelty=7.2/feasibility=8.0、4 条因果洞察）

## 3. 复现测试套件

```bash
python -m pytest tests/ -q
```

预期：**64 tests collected**、**64 passed**（含论文数值可溯源断言、Rail 阴性对照、
Stanford Reviewer 复现 8.43 > 4.21 阈值断言）。

> 注（2026-10-12 实测，CPython 3.14.0 / Windows 11）：**64 passed in 1.27s，退出码 0**。
> 早期版本的两项失败已分别解决：`test_reviewer_language_agnostic_iclr_tex` 的溯源断言
> 由判据修正解决（现 ICLR 稿 `cov_d` 98.48% ≥ 90% 门槛，见 `docs/architecture.md` §5）；
> `test_paper_builder_no_hallucination` 在**受限沙箱**下会退化为 `63 passed / 1 failed`
> —— 该用例经 `tempfile.mkdtemp()` 取系统临时目录写入，受限环境下报
> `PermissionError: [Errno 13] Permission denied` at `system\paper_builder.py:190`，
> 属**环境性失败**（临时目录权限）而非代码缺陷：临时目录恢复可写后即为 64 passed。
> 实测口径对照：
> | 运行条件 | 结果 |
> |---|---|
> | 临时目录可写（本机放开后） | `64 passed in 1.27s`，退出码 0 |
> | 临时目录不可写（受限沙箱） | `63 passed, 1 failed`，退出码 1，唯一失败项即上述用例 |

## 4. 复现引擎 agentic 路径 + Rail 生效

```bash
# 4.1 安装并初始化引擎（独立于上面的 venv）
pip install jiuwenswarm jiuwenswarm-tui
jiuwenswarm-init
jiuwenswarm-start                       # 前端 http://localhost:5173

# 4.2 配置模型：config/config.yaml.example → ~/.jiuwenswarm/config/config.yaml
#     填 api_base / api_key / model_name / client_provider（热加载）

# 4.3 挂载 Skills 与 Rail 扩展（复制）
#     skills/*      → ~/.jiuwenswarm/agent/workspace/skills/
#     extensions/*  → ~/.jiuwenswarm/agent/workspace/extensions/
#     deploy/research_pipeline.py → ~/.jiuwenswarm/agent/workspace/swarmflow/

# 4.4 引擎内端到端校验（MockBackend，不耗 token）
python deploy/engine_e2e_check.py       # 预期 ALL_ENGINE_E2E_PASS

# 4.5 Rail 显式裁决演示（真 results.json 基准）
python deploy/rail_verdict.py paper_system\paper_memory_engine.md
#     预期：真实论文 双 PASS；三个阴性对照（伪造数字/缺章节/悬空引用）全部 WARN

# 4.6 TUI 集群模式跑完整流水线（耗 token，可选）
jiuwenswarm-tui
#   /swarmflow on --budget 500000
#   Leader: swarmflow(script_path=".../swarmflow/research_pipeline.py",
#                      args={"topic": "Agent 记忆引擎策略权衡"})
#   /swarmflows 查看运行树；Rail 每次钩子留痕 rail_runtime.log
```

## 5. 复现框架补丁（paper_guard，红线证明）

```bash
git clone https://gitcode.com/openJiuwen/jiuwenswarm.git && cd jiuwenswarm   # atomgit.com/openJiuwen/jiuwenswarm.git 为同源镜像
git checkout develop
git apply paper-lab/framework-contribution/paper_guard.patch   # 或 git am
# 验证：新增 agents/harness/common/rails/paper_guard/ 包 + 4 处注册修改
# 详见 FRAMEWORK_PATCH.md（新增 3 文件、修改 4 文件、默认 enabled=false）
# 已发起的 MR：jiuwenswarm!5577（open，链接见 framework_contribution.md 第 3 节）
```

## 6. 已知事项

- `engine_e2e_check.py` / 框架补丁需在 miniconda 环境运行（openjiuwen 依赖
  钉在 Python ≥3.11,<3.14）；主系统对版本无要求。
- `rail_verdict.py` 首参可传任意论文路径；对无摘要/缺章节/编造数字的输入
  必然告警，属预期行为（阴性对照设计）。
- SwarmFlow 无独立 SDK 入口，必须经团队模式 Leader 的 `SwarmflowTool` 执行。

---

## 2026-08-22 新增：LongMemEval 真实 LLM 实验复现指南

### 数据
```bash
# ModelScope (HF 被墙时的替代源, cleaned 版已剔除干扰会话)
git clone --depth 1 https://www.modelscope.cn/datasets/evalscope/longmemeval-cleaned.git data/longmemeval-cleaned
```

### 依赖
```bash
pip install tiktoken rank_bm25 openai ruamel.yaml pyyaml matplotlib
```

### 运行
```bash
cd experiments/longmemeval
python run.py --smoke     # 11 题冒烟 (约 10 分钟)
python run.py --full      # 120 题全量: 6 策略 x 4 预算 (512/1024/2048/4096) + full-context
python analyze.py         # 生成论文表格/宏/统计/图 -> output/longmemeval/tables/
```

- 模型配置读 `~/.jiuwenswarm/config/config.yaml` 的 `models.defaults[0]`，与 JiuwenSwarm
  框架共用密钥。当前配置为 `mimo-v2.6-flash`。
- 断点续跑：LLM 调用按 key 落盘缓存（`cache/summaries/`、`cache/answers/`），
  中断后重跑命令自动跳过已完成部分。
- 逐题流水 `output/longmemeval/results.jsonl` 含 EM/relaxed-EM/F1、
  memory 足迹、纯内存访问延迟、端到端延迟、每次调用 token 用量。

### 论文编译
```bash
cd ../../output/final                 # 定稿目录（2026-10-16 mimo 单读者版）
pdflatex -interaction=nonstopmode paper.tex && bibtex paper \
  && pdflatex -interaction=nonstopmode paper.tex \
  && pdflatex -interaction=nonstopmode paper.tex   # -> paper.pdf
```
表格由 `analyze.py` 生成后复制进 `final/tables/`，论文 `\input` 引入——数字与
results.jsonl 逐字一致。

### 评审回应消融复现（2026-08-23）

```bash
cd experiments/longmemeval
python run.py --ablate       # 摘要长度(20/120词) + 层级分配(15/70/15, 40/20/40) + dense/hybrid 检索
python local_embed.py        # 本地 bge-small-en-v1.5 向量化 (模型: ../../../models/)
python local_embed.py --answers   # dense/hybrid 答题
python run.py --robustness   # GLM-4.7-Flash 跨读者复跑 (并发3, 摘要冻结)
python analyze.py            # 重生成全部表格/统计/图 (含消融表与双指标统计)
```

- 本地向量模型: ModelScope `BAAI/bge-small-en-v1.5`（33M 参数, 384 维, CPU 批量编码）
- API embedding-3 额度耗尽后切换本地推理，缓存与 API 向量目录隔离
  （`cache/embeddings_bge/` vs `cache/embeddings/`，后者为弃用的部分 API 向量）
- GLM-4.7-Flash 调用必须 `thinking: {"type": "disabled"}`，否则思考 token
  吃满输出预算导致空答案（harness 已内置）

### 修订轮实验复现（2026-08-24，预注册协议 ANALYSIS_PROTOCOL.md）

```bash
cd experiments/longmemeval

# E0-cleanup: 空记录重跑定性 (62 条全部为确定性 contentFilter 拒答, Addendum B)
python e0_cleanup.py

# E2 检索排名指标 (零 API): session 级 Recall@k / NDCG@k
python retrieval_ranking.py       # -> tables/retrieval_ranking.{json,tex}

# E1 结构化压缩器 KV/EDU (预注册判据: gap-closed 三档, §3)
python structure.py --variant kv --phase all   # 摘要+答题, 断点续跑
python structure.py --variant edu --phase all
python struct_summary.py           # 判读 -> tables/struct_eval.json

# E3 重排器 + dense 升级 (需先放模型到 ../../../models/)
#   bge-base-en-v1.5 / bge-reranker-base (ModelScope)
python _bge_base_embed.py          # bge-base 向量化 55,207 条 (CPU ~5.5h)
python rerank_eval.py              # 离线重排 + 在线答题 (3 策略 x 4 预算 x 120)
python rerank_summary.py           # 双口径判读 -> tables/rerank_eval.json

# E4 judge 全量扩容 (GLM-4.7-Flash, 并发 4 + 深重试; 幂等可重跑补 ERROR)
python judge_full.py               # -> tables/judge_full.json

# 表格再生成 + 数字对账
python analyze.py                  # 双基线 stats / 完成子集口径
python revision_tables.py          # struct_compressor.tex / rerank_eval.tex
python _reconcile.py               # 论文引数 vs 源 json, 42 项断言
python _d3_audit.py                # results.jsonl vs 原始 cache 全量对账
```

- E1/E3/E4 的判读规则在 `ANALYSIS_PROTOCOL.md` 预注册（lock 2026-08-24），
  执行记录与结论见其 Addendum B/C；全部脚本断点续跑（缓存幂等）。
- E3 的向量化与交叉编码器重排为纯 CPU（无 GPU 依赖），与 API 批次并行。
- provider 侧 contentFilter 拒答（4/120 题，62 格）按 0 计分并带
  `api_error` 存证；敏感性口径（排除 4 题）与主口径并列报告。

---

## 2026-10-16 全量复现记录（swarmflow 多智能体路径）

按 `README.md` §6.3 以 JiuwenSwarm 技能驱动引擎多智能体完成一次端到端全量复现
（`/swarmflow on` + 五技能任务链：literature-review → hypothesis-filter →
experiment-runner → paper-writer → paper-proofread），复用既有落盘数据、仅对
213 个缺失格断点续跑补齐（受限策略 165 格 + full_context 48 题，跳过 2,307 条
已完成记录、零重复 LLM 调用）。

- 结果：`experiments/longmemeval/results.jsonl` 共 **2,520 条**（21 格 × 120 题
  全满、零空预测），答题器统一为 **`mimo-v2.6-flash`**（贪心解码）；摘要预计算
  5,421/5,422（1 个历史失败项按截断摘要兜底，不阻塞）。
- 统计表由 `analyze.py` 从上述记录重新聚合（`tables/` 23:49–23:57 批次），
  主表数值与 results.jsonl 逐格一致；`pytest tests/` 69 passed, 1 skipped。
- 论文定稿（单读者版本，无跨读者表）：
  **`../output/final/`**（`paper.tex` + `paper.pdf` 7 页 + `final_paper.md` +
  `tables/` + `paper.bib`，可独立重编译）。

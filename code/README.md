# 代码与复现

`code/` 的目录结构自定，不要求固定入口文件名。**复现以本文命令为准。**

本文与提交样例说明的八节一一对应。第 6 节的命令在本包根目录 `IsMyGo/` 下执行。
本项目为**两段式流水线**：①实验段（run_id `agent-sci-2026-comp-001`，`run.py --full` 产出
`output/results.jsonl`，即论文全部数字来源）；②论文写作段（run_id `paper-gen-15p-20261016`，
`paper_gen_llm.py` 产出定稿 `paper/paper.pdf`）。按样例口径「产生论文**结果**的那次运行」，
`logs/run.json`+`calls.jsonl` 记录**实验段 full500 复跑**（run_id `agent-sci-2026-full500-015`，
deepseek-v4.1-flash 主读者全量 500 题的终扫批，2026-10-24 结构优化时归位于此）。
⚠ 写作段 `paper-gen-15p-20261016` 的原始日志曾于 2026-10-17 被该复跑覆盖且无备份，
其账目以 `resource_report.md` §1.1 为准（披露见 `logs/README.md`）。

---

## 1. 对应的运行

- run_id：**logs/ 所记录的运行** `agent-sci-2026-full500-015`（full500 终扫批，= `logs/run.json`+`calls.jsonl`，
  `verify_logs` 8 项断言通过）；**论文数字来源链** `agent-sci-2026-comp-001`（mimo 120 题初网格）→
  `agent-sci-2026-full500-011/013/015`（deepseek 全量 500 题主网格，= `output/results.jsonl`）；
  **论文写作段** `paper-gen-15p-20261016`（原始日志已覆盖，账目见 `resource_report.md` §1.1）
- 论文中要复现的结果：**第 5 节 Table 1–5 与 Figure 1**（论文数字的全部来源），延伸到第 6 节 Table 6–13。

| 论文位置 | 内容 | 生成文件（`output/tables/`） |
|---|---|---|
| §5 Table 1 | 六策略 × 四档预算的 EM / token-F1 主网格 | `main.tex`、`main.csv` |
| §5 Table 2 | 每格 relaxed EM 与 bootstrap 95% CI（10,000 次，seed 42） | `consolidated_emrel.tex` |
| §5 Table 3 | 按题型家族（EM） | `bytype.tex` |
| §5 Table 4 | 记忆访问延迟 / 端到端延迟 / 记忆足迹 | `latency.tex` |
| §5 Table 5 | compression 策略的逐档配对统计（bootstrap + McNemar） | `stats.tex`、`stats.json`、`stats_strict.json` |
| §5 Figure 1 | 准确率-预算、延迟-预算双曲线 | `fig_accuracy_vs_budget.pdf`、`fig_latency_vs_budget.pdf` |
| §6 Table 6–9 | 结构化逐字压缩器 / 失败定位 / 会话级排序 / 重排探针 | `struct_compressor.tex`、`retrieval_diagnosis.tex`、`retrieval_ranking.tex`、`rerank_eval.tex` + 同名 `.json` |
| §6 Table 10–12 | 摘要词长消融 / 分层分配消融 / 检索器家族 | `ablation_summary_len.tex`、`ablation_allocation.tex`、`ablation_retrieval.tex` |
| §6 Table 13 | 跨读者复跑（GLM-4.7-Flash） | `robustness_model.tex` |
| 成稿 | 论文定稿（正文 15 页 + 补充材料 3 页，deepseek 500 题主网格 + GLM 补充） | `output/final/`（`paper.tex` + `paper.pdf` + `tables500/` + `tables/`）= `paper/paper.pdf` |

> 复现第 5 节主表即第 6.1 节的一条命令；第 6 节 Table 6–13 需要额外子命令（`run.py --ablate` / `--robustness`
> 与 `data/README.md` §1.2 列出的证据文件），不是主表的必要条件。
>
> 其中 Figure 1 的两张 `fig_*.pdf` 由 `run.py` 在每格测得的 `e2e_ms` 聚合而来，需要在真实 LLM 路径下产出；
> 只用离线记录复算（`analyze.py` 单跑）时该文件不参与数值，缺失只会打印 `figure generation skipped: …`。

- 使用的模型：**主读者 `deepseek-v4.1-flash`**（本地代理，贪心解码，`temperature=0.0`，
  全量 500 题）；**副读者 `mimo-v2.6-flash`**（120 题整网格复跑）与 GLM-4-Flash（第二读者补充）。
  配置入口见第 4 节；语义 judge / 跨读者脚本用 `MODEL_ALT`（`common.resolve_model_names()`，
  默认 GLM-4.7-Flash，thinking disabled）。
- **主数据口径（2026-10-24 裁定）**：论文主网格以 **`deepseek-v4.1-flash` 全量 500 题记录为准**
  （`run.py --full500`，10,500 条），**mimo-v2.6-flash 为副读者**（2026-10-16 的 120 题 × 21 格
  整网格复跑，2,520 条，格子全满、无空预测），GLM-4-Flash 整张主网格作第二读者鲁棒性补充
  （原始记录见 `output/glm_supplementary/`）。换模型只需改配置或环境变量。

---

## 2. 环境

- Python：3.10 及以上（实测 CPython 3.14.0 / Windows 11）。①②④ 为纯标准库路径；③ 需要第三方包。
  可选的引擎 agentic 路径需 3.11 ≤ 版本 < 3.14。
- 安装：本包**不使用虚拟环境快照**，实际安装方式为按依赖文件安装：

  ```bash
  pip install -r code/requirements.txt
  ```

  ③ LongMemEval 主实验需要 `tiktoken` / `rank_bm25` / `openai`（`matplotlib` + `numpy` 仅供 Figure 1 与消融表；
  缺失时 `analyze.py` 打印 `figure generation skipped: …` 后继续，不中断表格与复现）；测试需要 `pytest` + `PyYAML`；
  `sentence-transformers` + `torch` 只服务 Table 9/12 的重排器消融。
  **零 LLM 路径（①②）无需安装任何第三方包；④ 只额外需要 `tiktoken` 与数据集（见 3.3）。**
- openJiuwen 版本或 commit：`jiuwenswarm 0.2.3`（`pip install jiuwenswarm jiuwenswarm-tui`，自动带入 `openjiuwen`）；
  本包框架贡献补丁基于上游 `develop@3f3dd75c`（`code/framework-contribution/paper_guard.patch`，10 文件 +843 行）。
  该路径只演示多智能体编排与 Rail 护栏，**不是复现论文数字的必要条件**，详见 `run_guide.md` §4。
- 其他系统依赖：**MiKTeX 或 TinyTeX**（`pdflatex` + `bibtex`），仅编译论文（`output/final/` 定稿或论文生成路径）时使用；
  零 LLM 路径无此依赖。

### 双后端（agent-core 基础类复用，零 LLM 路径仍纯标准库）

`system/` 基建与编排层（scheduler/contracts/context_cache/orchestrator）经
`system/backends.py` 做**双后端适配**：优先复用 openJiuwen (agent-core) 的基础类
（`hash_text` 内容哈希、`task_manager` 任务树、`core.workflow` 组件化编排、
`BranchRouter` 门控路由），agent-core 不可用时**自动回退内置同款实现并告警**，
故 ①②④ 零 LLM 路径无需安装任何第三方包即可运行（产物逐字节等价）。

- 开关：`PAPER_LAB_BACKEND = auto`(默认，能加载 agent-core 就用) | `agentcore` | `stdlib`
- agent-core 来源：`pip install openjiuwen`，或设 `OPENJIUWEEN_SRC=<agent-core 源码树>`
  （源码树加载不受 `requires-python<3.14` 限制，Python 3.14 实测可用）
- 等价性保证：`code/tests/test_backend_equivalence.py`（哈希逐位一致、双后端
  产物 accuracy 语义等价、Workflow 组件图端到端）；复用清单见 `docs/module_call.md` §0

---

## 3. 数据

数据说明见 `data/README.md`。包内已有的数据直接使用；需要下载的，先执行其中的获取命令。

### 3.1 包内已有（本包已随附，直接用）

| 路径 | 大小 / 校验 | 在复现中做什么 |
|---|---|---|
| `data/longmemeval-cleaned/longmemeval_s_cleaned.json` | 277,383,467 字节（264.5 MiB）<br>SHA256 `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`<br>MD5 `9b009af4084c6207e9d41aa0dcb6506c` | ③ 的全部输入：500 题 / 246,750 轮 / 19,195 session；`common.py:load_questions()` 按 `seed=42` 分层抽 120 题（配额 32/32/19/17/13/7），再按 512/1024/2048/4096 cl100k token 切记忆预算 |
| `code/output/longmemeval/results.jsonl` | 14,066 条逐题记录（**主读者 deepseek-v4.1-flash：500 题 × 21 格 = 10,500 条**；副读者 mimo-v2.6-flash：120 题复跑 = 2,520 条；弃用代际 glm5.3-flash：1,046 条） | ④ 表格与 ⑤ 成稿的**唯一数值来源**（聚合时只读这一份，按答题器模型分组）；**论文主表取 deepseek 主读者记录，mimo 为副读者** |

一行校验（大小 + SHA256 + 随包产物存在性）：

```bash
python code/scripts/fetch_data.py --check
```

结构自检（期望 500 题）：

```bash
python -c "import json;d=json.load(open('data/longmemeval-cleaned/longmemeval_s_cleaned.json',encoding='utf-8'));print(len(d),'questions')"
```

### 3.2 不在包内、需要自行获取

1. **数据集本体**——若包内文件缺失或需重新下载（同一份数据的可重复获取方式，带大小与 SHA256 双重校验）：

   ```bash
   python code/scripts/fetch_data.py --dest data/            # 下载 + 校验
   python code/scripts/fetch_data.py --check                 # 只校验
   # 手工等价命令（无需脚本）：
   curl -L -o data/longmemeval-cleaned/longmemeval_s_cleaned.json \
     "https://www.modelscope.cn/api/v1/datasets/evalscope/longmemeval-cleaned/repo?Revision=master&FilePath=longmemeval_s_cleaned.json"
   # 或 git（git-lfs，需再执行 git lfs pull）：
   git -c http.sslBackend=openssl clone --depth 1 https://www.modelscope.cn/datasets/evalscope/longmemeval-cleaned.git
   ```

   来源：ModelScope `evalscope/longmemeval-cleaned`，Revision `master`；许可随上游 LongMemEval（研究用途）。
   路径由 `code/experiments/longmemeval/common.py:16-19` 的 `DATASET_PATH` 决定：
   `Path(__file__).resolve().parents[3] / "data" / "longmemeval-cleaned" / "longmemeval_s_cleaned.json"`（即 `IsMyGo/data/…`）。

2. **三个本地编码/重排模型**——仅第 6 节 Table 9 与 Table 12 的消融需要，**主表（Table 1–5）不需要**。
   其中 **`models/bge-reranker-base` 已随包附带**（1.1 GiB），无需再下载；
   `bge-small-en-v1.5` 与 `bge-base-en-v1.5` 两个编码器不在包内。**推荐一条命令获取**：

   ```bash
   python code/scripts/fetch_models.py            # 下载全部缺失模型（幂等，已存在即跳过）
   python code/scripts/fetch_models.py --check    # 只校验
   python code/scripts/fetch_models.py --only bge-small   # 只下某一个
   ```

   或手工 git 克隆（等效）：

   ```bash
   mkdir -p models
   git -c http.sslBackend=openssl clone --depth 1 https://www.modelscope.cn/BAAI/bge-small-en-v1.5.git  models/bge-small-en-v1.5
   git -c http.sslBackend=openssl clone --depth 1 https://www.modelscope.cn/BAAI/bge-base-en-v1.5.git   models/bge-base-en-v1.5
   # bge-reranker-base 已在包内（models/bge-reranker-base），如需重新获取：
   # git -c http.sslBackend=openssl clone --depth 1 https://www.modelscope.cn/BAAI/bge-reranker-base.git  models/bge-reranker-base
   ```

   各目录需 `config.json` + 权重文件 + `tokenizer.json`；详见 `data/README.md` §2.2。
   **运行时预检**：四个加载点（`local_embed.py` / `_bge_base_embed.py` / `rerank_eval.py` /
   `rerank_latency.py`）经 `common.require_model()` 预检，模型缺失时打印修复命令后退出，
   不会再抛出晦涩的网络异常。

3. **LLM 凭据**——见第 4 节。

### 3.3 复现的「输入」到底是什么

| 层 | 输入 | 是否依赖外部数据 |
|---|---|---|
| ① `experiments/run_all.py`（实验真值） | 只有题面字段 `payload["meta"]["topic"]` | 否，合成数据，纯标准库 |
| ③ `experiments/longmemeval/run.py`（论文数字） | LongMemEval-S 数据集 + `~/.jiuwenswarm/config/config.yaml` 的模型凭据 | 是（见 3.1 / 3.2） |
| ④ `experiments/longmemeval/analyze.py`（表格） | ③ 的 `results.jsonl`；另调 `common.load_questions()` 复算 120 题抽样 ID 用于过滤，因此还需数据集与 `tiktoken` | 是（数据集/tiktoken 只做抽样比对，**不参与任何数值计算**） |
| ⑤ `code/scripts/populate_output.py`（成稿；当前守卫退出，见脚本说明） | ④ 产出的 `tables/` + `logs/run.json` | 否 |

---

## 4. 模型配置

复现使用统一的 LLM。模型名、接口地址、密钥**只从下面这一处读取**，仓库中不得写入密钥。
复现时只替换这一处，不修改算法代码。

- 文件：`~/.jiuwenswarm/config/config.yaml` 的 `models.defaults[0].model_client_config`
  （Windows：`C:\Users\<用户名>\.jiuwenswarm\config\config.yaml`；模板见 `code/config/config.yaml.example`）

  ```yaml
  models:
    defaults:
      - model_client_config:
          api_base: ${API_BASE}                # 例如 https://open.bigmodel.cn/api/paas/v4
          api_key: ${API_KEY}
          model_name: ${MODEL_NAME}            # 例如 glm-4.7-flash
        is_default: true
  ```

  读取代码：`code/experiments/longmemeval/common.py` 的 `load_model_config()`——只读这一个文件，
  取 `models.defaults[0].model_client_config` 的 `api_base` / `api_key` / `model_name`。
  若该文件里写成 `${VAR}` 形式，由同函数 `resolve()`（`os.path.expandvars`）展开为同名环境变量。

> **模型名解析入口**（`code/experiments/longmemeval/common.py` 的 `resolve_model_names()`）：
> `MODEL_MAIN`（主读者/摘要/答题器）优先级为 `PAPER_LAB_MODEL` 环境变量 → `config.yaml` 的 `model_name`
> → 默认 `glm-4.7-flash`；`MODEL_ALT`（跨读者/裁判）优先级为 `PAPER_LAB_ALT_MODEL` 环境变量
> → 默认 `GLM-4.7-Flash`。`llm.py` 不再钉死模型名，换模型只需改配置或环境变量。
>
> **答题器随所用模型变化（普遍性）**：答题器 = 当前配置的模型（config.yaml 是什么模型，
> 答题器就是什么模型）。断点续跑与表格聚合均按记录的答题器模型归属判定
> （`common.record_matches_model` / `record_model`，新记录带 `model` 字段、历史记录按
> 生成时读者回退）——**换模型后旧答案不会被误用**，未由当前答题器作答的格子自动重答；
> `analyze.py` 表格按实际答题器分组（多模型并列时各出一组，单模型输出与原格式一致）。
> 答题缓存命名空间带模型标签（历史 GLM-4-Flash 主网格保留 `answer:v2` 旧命名空间）。
>
> **答题器行为旋钮**（回应输出长度/解码方式的普遍性质疑，默认与历史网格同口径）：
> `PAPER_LAB_ANSWER_MAX_TOKENS`（输出上限，默认 64；思考型 GLM-5.x 自适应 240）、
> `PAPER_LAB_ANSWER_TEMPERATURE`（解码温度，默认 0.0 贪心）、
> `PAPER_LAB_DISABLE_THINKING=1`（强制关闭思考模式，陌生推理型模型兜底）。
> GLM-4.7/5.x 系列调用自动关闭思考模式（否则思考 token 吃满输出预算致空答案）。
>
> **全新流程（换任意模型重跑）**：所有 LLM 产物缓存（摘要 `summary:{ns}:…`、
> 先取后总结 `fetch:{ns}:…`、答题 `answer:{ns}:…`）均按生成模型隔离命名空间
> （`common.model_cache_ns`：GLM-4-Flash 归档保留 `v2`，其余 `v2-{model}`）——
> **换模型即换命名空间，摘要/答题全部由新模型重新生成**，不复用旧模型产物；
> 同模型内支持断点续跑。需要"完全不落缓存"的纯净重跑时用 `run.py --fresh`
> （或 `PAPER_LAB_FRESH=1`）：忽略一切缓存与续跑记录、不读不写缓存
> （保护归档缓存不被覆盖），`python code/main.py --paper-run` 前置该变量即全新流程。

> 注：代码中**没有** `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` 这类专用环境变量；
> 它们只在 `config.yaml` 里被写成 `${...}` 占位时才生效。密钥一律不写入仓库。

---

## 5. 其他外部依赖

除第 4 节的统一 LLM 外，运行还要访问的服务：

| 名称 | 用途 | 配置位置 | 不提供时能否跑完 |
|------|------|----------|------------------|
| 统一 LLM（mimo-v2.6-flash，见第 4 节） | 实验段摘要+答题（7,290 次）与论文写作段逐章生成/修订（17 次）的真实调用 | `~/.jiuwenswarm/config/config.yaml` | 不能（③ 需要；①②④⑤ 可离线） |
| ModelScope | 获取 LongMemEval-S cleaned 数据集（264.5 MiB） | 无需密钥，`code/scripts/fetch_data.py`（见 3.2） | 不能（③ 需要；本包已随附数据，可直接用） |
| ModelScope | 获取 bge-small / bge-base / bge-reranker 三个本地模型 | 见 3.2 / `data/README.md` §2.2 | 能（仅 Table 9、Table 12 消融需要；主表不需要） |

**无其他外部服务**：论文流程不访问文献检索、网页抓取或远程代码执行服务；
零 LLM 路径（① ②）为纯本地合成实验。密钥不得写入仓库，只需设置上述 `config.yaml` 字段。

---

## 6. 复现论文结果

在仓库根目录（`IsMyGo/`）执行。

### 运行方式与论文产出对照

| # | 运行方式 | 命令 | 出论文？ | 产出的论文形态 | openJiuwen (agent-core) 关联 |
|---|---|---|---|---|---|
| 1 | 零 LLM 确定性路径 | `python code/main.py` | ✅ | `paper_system/paper_memory_engine.md`——完整九段式中文短论文，确定性渲染、零幻觉 | **强**：② 主系统编排层复用 `core.workflow` 组件图（`system/orchestrator.py`），基建复用 `hash_text`/`task_manager`/`build_key`（`system/backends.py` 双后端：agentcore 优先、stdlib 回退） |
| 2 | 真实 LLM 论文路径 | `python code/main.py --paper-run` | ✅ | `output/paper.pdf` + `paper.tex`——**15 页 ICLR LaTeX 正式稿 PDF（最终交付物）** | **弱**：LLM 凭据读 `~/.jiuwenswarm/config/config.yaml`（与 JiuwenSwarm 框架共用一份密钥），不复用 agent-core 类 |
| 3 | 实验细粒度子命令 | `cd code/experiments/longmemeval && python run.py <mode>` | ⚠️ 间接 | 只产 `results.jsonl` + `tables/*.tex`（论文数字与表源，**论文数字的唯一来源**）；成稿需再走 ④⑤ 或 #2 | **弱**：同 #2（配置共用） |
| 4 | 技能驱动引擎多智能体 | JiuwenSwarm 团队模式 + `skills/*`（见 §6.3） | ✅ | `paper-writer` 写作 + `paper-proofread` 校对产出定稿（Markdown + LaTeX + PDF） | **强**：JiuwenSwarm 引擎内多智能体执行，`skills/*` + `swarmflow/research_pipeline.py` 挂载到引擎工作区 |
| 5 | 引擎 SwarmFlow 部署版 | `deploy/research_pipeline_v5.py`（见 `run_guide.md` §4） | ✅ | `paper/draft_v5.md` → `paper/final_v5.md`（七阶段流水线写作/校对产出） | **强**：`openjiuwen.agent_teams.workflow.engine.run_workflow`、harness manifest、paper_guard Rails（框架补丁 `framework-contribution/paper_guard.patch`） |
| 6 | 离线测试套件 | `python -m pytest code/tests -q` | ❌ | 仅验证正确性，无论文产物 | **部分**：`test_backend_equivalence.py` 验证 agent-core 复用（`hash_text` 逐位一致、Workflow 图端到端）与 stdlib 回退等价 |

> **agent-core 复用清单**：见 `docs/module_call.md` §0（`hash_text` 内容哈希、`task_manager` 任务树、
> `checkpointer.build_key` 键构造、`core.workflow` 组件图、`BranchRouter` 门控路由的逐一映射）；
> 双后端开关 `PAPER_LAB_BACKEND=auto|agentcore|stdlib` 见 §2「双后端」段。
> 口径：「强」= 直接复用 agent-core 类/引擎执行；「弱」= 仅共用 JiuwenSwarm 配置（密钥/模型名）；「部分」= 测试层验证复用等价性。

> **论文数字纪律**：#1/#2/#4/#5 四种成稿方式的**数字都必须溯源到 #3 的落盘结果**
> （`results.json` / `results.jsonl`）——这是零幻觉设计的核心约束（`paper_builder` 确定性渲染、
> `paper-writer` 技能 Forbidden 条款均禁止编造实验外数字）。
> 即：**#3 提供论文的数字，#1/#2/#4/#5 是四种"把数字写成论文"的成稿方式**。

### 6.1 论文运行（两段式：实验段产数字 → 写作段产论文与提交的 `logs/`）

提交的写作段运行（run_id `paper-gen-15p-20261016`，样例口径「产生提交论文那一次运行」）
的原始 `logs/run.json`+`calls.jsonl` 已于 2026-10-17 被 full500 复跑覆盖（披露见 `logs/README.md`
与 §8，账目以 `resource_report.md` §1.1 为准）；`output/results.jsonl`+`tables/` 来自**实验段**
（run_id `agent-sci-2026-comp-001`）。两段依次执行：

```bash
# ① 实验段：复现论文数字（120 题 × 6 策略 × 4 预算 + full-context = 21 格）
#    论文主网格 = deepseek-v4.1-flash 全量 500 题（run.py --full500，主读者，10,500 条）；
#    mimo-v2.6-flash 为副读者（120 题复跑，实测约 3 小时 / 23,194,392 token / 7,290 次调用）
python code/main.py --paper-run            # = run.py --full --log-run → analyze.py → populate_output.py
#    主读者全量复现入口：cd code/experiments/longmemeval && python run.py --full500 --log-run
#    产 code/output/longmemeval/results.jsonl（2,520 条）+ tables/；同步到 output/
#    注：--log-run 写出的是实验段 run.json（run_id agent-sci-2026-comp-001）；
#        该存档目录未随包提交，实验段用量对账见 resource_report.md §1.2/§1.3，
#        非提交 logs/（logs/ 只放写作段记录）

# ② 写作段：逐章 LLM 生成 15 页定稿 + 写提交的 logs/（约 14 分钟、113,530 token、17 次调用）
cd code/experiments/longmemeval
RUN_ID=paper-gen-15p-20261016 RUN_LOG_DIR=../../logs python paper_gen_llm.py
#    产 output/final_15p/（归档为 output/final/ = paper/paper.pdf）+ logs/{run.json,calls.jsonl}

# 冒烟档（仅验证环境，另一次运行，run_id 需重新登记）
python code/main.py --paper-run --smoke    # 11 题，约 10 分钟
```

实验段（`code/main.py --paper-run` 的 `run_paper()`）依次执行三步：

| 步 | 命令 | 产出 |
|---|---|---|
| ③ | `experiments/longmemeval/run.py --full --log-run`（cwd=`code/experiments/longmemeval`） | `code/output/longmemeval/results.jsonl`（逐题记录）+ 实验段 `run.json`/`calls.jsonl`（run_id `agent-sci-2026-comp-001`，已存档） |
| ④ | `experiments/longmemeval/analyze.py` | `code/output/longmemeval/tables/*.tex`、`*.json`、`fig_*.pdf`（25 项） |
| ⑤ | `code/scripts/populate_output.py` | `output/results.jsonl`、`output/tables/`（含 `main.csv`）、`output/draft/`、`output/run_manifest.json`（成稿子步当前守卫退出，论文定稿由写作段 `paper_gen_llm.py` 产出，见 `output/final/`） |

**预期产物**：

- 实验结果文件：`code/output/longmemeval/`（results.jsonl + tables/），运行包说明见 `output/README.md`
- 提交日志：`logs/run.json`、`logs/calls.jsonl`（**写作段** `paper-gen-15p-20261016`），说明见 `logs/README.md`

两段均须正常退出（exit code 0）：实验段在 `code/output/longmemeval/` 写出完整 `results.jsonl` 与表格；写作段在 `output/final/` 写出 15 页定稿并编译 `paper/paper.pdf`，`logs/` 中可读取 token 总量（113,530）与起止时间。`verify_logs('logs')` 对写作段 8 项断言全通过。

两点说明：

1. **断点续跑**：`run.py` 以 `policy|budget|question_id` 为键读已有 `results.jsonl`，已完成的格子会打印
   `[skip] … 已完成` 并跳过；带缓存的格子重复运行**不会重新发起 HTTP 调用**，也不写 `calls.jsonl`。
2. **重跑与提交版的关系**：论文的 36 题 full-context 完成子集来自当年一次供应商限流风暴（84/120 客户端层失败），
   该环境不可复现；重跑会得到 120/120 完成的 full-context 行，其余 19 个格子与论文表在 1–2 题以内一致，
   三条主结论（压缩单独使用劣于 BM25；分层三档单调上升；分层在 4096 预算最优）均不变。
   逐格对照见 `output/README.md`。

### 6.2 零 LLM 路径（约 10 秒，用于先验证环境）

```bash
python code/main.py              # ① 实验真值 + ② 主系统（确定性，无需密钥）
python code/main.py --quick      # 同上，实验真值用快速档预算
```

产出：`code/output/results.json`、`code/paper_system/paper_memory_engine.md`、`code/charts_system/`、`code/logs_system/`。
这条链证明环境可用，但**不产出 `logs/` 与 `output/`**（那需要真实 LLM 的 6.1 节）。

重构说明：② 主系统经 `system/orchestrator.run_pipeline` 走真实四模块链
（构思→规划→实验→写作），agent-core 可用时执行 `core.workflow` 组件图
（含门控状态路由），否则回退 stdlib 顺序执行，两路产物逐字节等价。
`logs_system/run_log.json` 的 `orchestration` 字段记录实际生效的编排后端与
四阶段溯源（`backend`/`engine`/`steps`），可用于确认 Workflow 图是否真实执行。

### 6.3 技能驱动的引擎多智能体路径（可选，非论文数字必要条件）

`code/skills/` 下是 5 个**引擎侧 Agent 技能包**（各含 `SKILL.md` 提示词规范，
面向 LLM 多智能体，不被 Python 代码 import）：

| 技能 | 职责 |
|---|---|
| `literature-review` | 文献调研与近邻系统定位 |
| `hypothesis-filter` | 假设双维门控（创新性/可行性） |
| `experiment-runner` | 实验执行与真值注入 |
| `paper-writer` | 依据真实实验数据写论文（零幻觉纪律） |
| `paper-proofread` | 论文校对与格式合规 |

**用法**（需 `jiuwenswarm` 0.2.3 + 引擎运行，完整步骤见 `run_guide.md` §4）：

```bash
# 1) 挂载技能与 Rail 扩展到引擎工作区（一次性）
#    Windows 目标目录：C:\Users\<用户名>\.jiuwenswarm\agent\workspace\skills\
code/skills/*        → ~/.jiuwenswarm/agent/workspace/skills/
code/extensions/*    → ~/.jiuwenswarm/agent/workspace/extensions/
code/swarmflow/research_pipeline.py → ~/.jiuwenswarm/agent/workspace/swarmflow/
```

```
# 2) 引擎内以团队模式调度（JiuwenSwarm TUI/Web 会话）
/swarmflow on --budget 500000
Leader: swarmflow(script_path=".../swarmflow/research_pipeline.py",
                   args={"topic": "你的题目"})
/swarmflows 查看运行树；Rail 每次钩子留痕 rail_runtime.log
```

**与命令行复现的关系**：本路径演示「模块化多智能体协同 + Rail 护栏」语义
（技能提示词约束各阶段 Agent 行为），**不是复现论文数字的必要条件**——
论文数字与成稿来自 §6.1 的 `python code/main.py --paper-run`（③④⑤ 链，
不依赖技能包）。两条路径共享同一实验真值（`results.json`/`results.jsonl`）。
注意：技能包需先完成第 1 步挂载才会被引擎 Agent 消费；未挂载时引擎路径不可用。

> **2026-10-16 实跑记录**：本路径已完成一次端到端全量复现（IsMyGo 项目）。
> 五阶段任务链全部完成：t1-lit / t2-hyp / t3-exp（213 缺失格断点续跑补齐，
> `results.jsonl` 2,520 条、21 格全满 n=120、零空预测，答题器 `mimo-v2.6-flash`）→
> t4 论文撰写 → t5 校对定稿。定稿三件套归档于 `../output/final/`
> （`paper.tex` + `paper.pdf` + `final_paper.md`，单读者版本、无跨读者表），
> 主表数值与 `results.jsonl` 逐格一致。

---

## 7. 更换题目

只改输入，不改源码。本包有三条链，题面所在位置逐一给出：

| 链 | 题面位置（路径 + 字段名） | 改法 |
|---|---|---|
| ① 主系统（零 LLM） | `code/experiments/run_all.py:46` 的 `payload["meta"]["topic"]`（当前值 `Agent记忆引擎：长程流式任务中的记忆策略权衡`） | 改这一个字符串 |
| ② 引擎 agentic 路径 | 调用处 `args={"topic": ...}`，写在 `code/deploy/research_pipeline_v5.py` 的入参 | 见下 |
| ③ LongMemEval（论文数字） | 题面即数据集：`code/experiments/longmemeval/common.py:16-19` 的 `DATASET_PATH`，或直接替换 `data/longmemeval-cleaned/longmemeval_s_cleaned.json` | 换数据集文件，不改算法 |

引擎 agentic 路径的两种换法（需要 `jiuwenswarm` 0.2.3，见第 2 节）：

```python
result = await run_workflow(
    "code/deploy/research_pipeline_v5.py",
    args={"topic": "你的新题目", "pacing": False},   # ← 只改这里
)
```

```
/swarmflow on --budget 500000
Leader: swarmflow(script_path=".../swarmflow/research_pipeline.py",
                   args={"topic": "你的新题目"})
```

> **命令口径提示**：本包 `code/main.py` 只有 `--paper-run` / `--smoke` / `--quick` / `--skip-exp` 四个开关，
> **没有** `--topic` 或 `--output`；题目不在命令行上传入，而在上表的文件字段里。因此样例说明中
> `python code/main.py --topic "…" --output ./output` 的写法在本包不适用，请以本节表格为准。
> 输出目录同样固定：`logs/`、`output/`、`code/output/longmemeval/`。

---

## 8. 与资源报告核对

按样例口径逐项核对 `logs/` 所记录的那一次运行（run_id `agent-sci-2026-full500-015`，
即产生论文主网格数字的 full500 复跑终扫批；`verify_logs` 8 项断言全过）：

1. `logs/run.json` 的 `run_id` 与 `resource_report.md` 主表一致：均为 `agent-sci-2026-full500-015`。
2. 资源报告主表的 token 总量等于 `run.json` 的 `token_total`，也等于 `calls.jsonl` 里各次
   `total_tokens` 之和：**2,632**（2,175 + 457）。
3. 总耗时等于 `run.json` 的 `ended_at - started_at`（= `wall_seconds`）：**108 秒**。
4. `run.json` 的 `output_paper` = `paper/paper.pdf`，即提交包 `paper/` 下的成稿；其数字依据为
   `output/results.jsonl`（deepseek 全量 500 题主网格记录），可重编译 LaTeX 源为
   `output/final/paper.tex`（+ `paper.bib`/`.bbl` + `iclr2025_conference.{sty,bst}` +
   `output/final/tables/`）。

一条命令核对 `logs/` 的同一次运行（8 项断言，实测 `passed: true`）：

```bash
python -c "import sys;sys.path.insert(0,'code/scripts');from run_logger import verify_logs;print(verify_logs('logs'))"
```

### 补充：论文写作段的历史账目（原始日志已被覆盖，不与 logs/ 对账）

> ⚠ 披露：写作段 `paper-gen-15p-20261016` 的原始 `run.json`/`calls.jsonl` 已于 2026-10-17
> 被 full500 复跑的 `--log-run` 覆盖且无备份，逐次调用记录不可恢复；下表为覆盖前记录的
> 历史真值，账目见 `resource_report.md` §1.1。full500 分批各轮的累计对账见 §1.2。

写作段那一次运行（`paper_gen_llm.py`，真实 LLM 逐章生成 15 页定稿）的账目如下：

| 项 | 值 |
|---|---|
| `run_id` | `paper-gen-15p-20261016` |
| `model` | mimo-v2.6-flash |
| `llm_calls` | 17（论文生成Agent 12 + 论文修订Agent 5） |
| `token_input` / `token_output` / `token_total` | 72,395 / 41,135 / **113,530** |
| `wall_seconds` | 847.0（2026-10-16 01:19:10 → 01:33:17 +08:00） |
| `command` | `python paper_gen_llm.py`（cwd=`code/experiments/longmemeval`，`RUN_LOG_DIR=logs`） |

补充口径说明：

1. **`logs/` 现为实验段终扫批**：按样例「产生论文**结果**的那次运行」，`logs/` 放 full500
   复跑终扫批（deepseek 主读者全量 500 题主网格的最后一批）的真实程序日志；上表写作段
   （17 次调用：12 次 `论文生成Agent(章节)` + 5 次 `论文修订Agent(章节)`）为被覆盖前的历史账目。
2. **各代际实验消耗另行披露**：mimo 120 题初网格实测 **23,194,392 token / 7,290 次调用**
   （2026-10-15，墙钟 10,728 s）；deepseek full500 全轮 **125,460,134 token / 29,695 次调用**。
   两者逐题用量均内嵌于 `output/results.jsonl` 的 `prompt_tokens`/`completion_tokens` 字段
   （可直接复算）；逐项对账见 `resource_report.md` §1.2/§1.3。
3. **与累计口径的关系**：`resource_report.md` 补充口径 §1 的「累计 ≈2.05 亿 token」为全项目
   开发总消耗（GLM/mimo/deepseek 各代际、消融、跨读者、修订轮与写作段），不与 `logs/` 的
   单次 run_id 对账；单次对账等号（`run.json` × `calls.jsonl`）已由 `verify_logs()` 逐项验证。

---

## 9. 离线校验（可选）

```bash
python -m pytest code/tests -q          # 离线测试套件（不访问网络、不需要密钥）
```

本机实测（2026-10-24 复测，CPython 3.14.0 / Windows 11）：**70 tests collected；69 passed / 1 skipped in ~10s**
（数字与 2026-10-15 实测一致；2026-10-24 判据演进：reviewer 参考文献识别扩展至 author-year
行内引用 + References 节，特异性护栏改按 z 显著性断言并注明证据桶并入 500 题网格后的
重标定依据——详见 `tests/test_system.py` 两处用例 docstring）
（64 个既有用例 + 6 个双后端等价性用例；skip 为 `test_build_gate_router_shape` 在
pytest 会话被其它 rail 测试的 openjiuwen 桩遮蔽时跳过，单独运行即通过）。
> 次要说明：`test_paper_builder_no_hallucination` 在**受限沙箱**下会退化为
> `63 passed / 1 failed` —— 该用例经 `tempfile.mkdtemp()` 取系统临时目录写入，
> 该目录在受限沙箱下不可写，报 `PermissionError: [Errno 13] ... at system\paper_builder.py:190`；
> 把临时目录指向可写路径后重跑即全过，故不是代码缺陷。
> （早期版本 `test_reviewer_language_agnostic_iclr_tex` 的溯源断言口径问题已由溯源判据
修正解决，现 ICLR 稿 `cov_d` 98.48% ≥ 90% 门槛。详见 `run_guide.md` §3。）

双后端等价性用例（`tests/test_backend_equivalence.py`）额外验证：
- `hash_text`（agent-core 复用）与内置 `sha256[:16]` 逐位一致；
- 双后端产物 accuracy 语义等价（计时噪声字段除外）；
- agent-core Workflow 组件图端到端执行（单独跑时 6/6 全过）。

套件不依赖 LLM 密钥；引擎内 agentic 路径与 Rail 生效证明见 `run_guide.md` §4，
框架补丁见 `code/framework-contribution/paper_guard.patch` 与 `framework_contribution.md`。

---

## 附：`code/` 目录速查

| 路径 | 作用 |
|---|---|
| `main.py` | 统一入口：零 LLM 路径（默认）/ 论文运行（`--paper-run`） |
| `requirements.txt` | 第三方依赖（③ 与测试；①②④ 不需要） |
| `config/config.yaml.example` | JiuwenSwarm `config.yaml` 模板（含第 4 节字段） |
| `experiments/run_all.py` | ① 实验真值（合成数据，确定性） |
| `experiments/longmemeval/` | ③ 论文数字：`run.py` 主网格、`common.py` 抽样与预算、`llm.py` 调用/缓存/日志、`policies.py` 六策略、`score.py` 评分、`analyze.py` 表格与图 |
| `system/` | ② 主系统四阶段（ideation / planning / experiment / writing）+ 双后端基建 |
| `system/backends.py` | 双后端适配层：agent-core 基础类复用（hash_text / task_manager / build_key）+ stdlib 回退 |
| `system/orchestrator.py` | 四模块编排层：agent-core `core.workflow` 组件图（Start→四模块→门控路由→End）+ stdlib 顺序回退 |
| `skills/` | 5 个引擎侧 Agent 技能包（literature-review / hypothesis-filter / experiment-runner / paper-writer / paper-proofread，SKILL.md 提示词，需挂载到引擎工作区，见 §6.3） |
| `swarmflow/` | SwarmFlow 多智能体流水线脚本（`research_pipeline.py`，引擎团队模式调度用，见 §6.3） |
| `scripts/` | `fetch_data.py` 数据获取校验、`fetch_models.py` 模型获取校验、`make_submission.py` 按样例结构打包 zip、`run_logger.py` 日志、`populate_output.py` 成稿、`sandbox_runner.py` 沙箱执行 |
| `deploy/` | 引擎 agentic 路径（SwarmFlow 流水线、E2E 检查、Rail 判定） |
| `extensions/` | 三个 Rail 扩展（academic_format / hallucination_check / claim_alignment） |
| `framework-contribution/` | 上游补丁 `paper_guard.patch` 与逐文件副本 |
| `output/longmemeval/` | results.jsonl、tables/、cache/（断点续跑缓存 ~100 MiB） |
| `output/locomeval/` | LoCoMo 跨数据集探针产物（泛化性补充，非主网格；见 `experiments/longmemeval/README.md`） |
| `tests/` | 离线测试套件（含 `test_backend_equivalence.py` 双后端等价性） |

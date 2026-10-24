# data/ —— 复现论文结果所需的数据

> 论文：**When Does Memory Compression Pay Off? A Budget-Controlled Study of Memory
> Policies for LLM Agents on LongMemEval**（`paper/paper.pdf`）
>
> 本目录给出「跑出论文全部数字」需要的数据：哪些随包提交、哪些必须自行获取、
> 获取后如何校验、以及输入题目在哪里改。

---

## 一、包内数据（随包提交）

### 1.1 `longmemeval-cleaned/longmemeval_s_cleaned.json`

| 项 | 值 |
|---|---|
| 路径 | `data/longmemeval-cleaned/longmemeval_s_cleaned.json` |
| 大小 | 277,383,467 字节（264.5 MiB） |
| SHA256 | `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442` |
| MD5 | `9b009af4084c6207e9d41aa0dcb6506c` |
| 格式 | JSON 数组，500 题；每题含 `question_id / question_type / question / question_date / answer / answer_session_ids / haystack_session_ids / haystack_dates / haystack_sessions` |
| 题型分布 | multi-session 133、temporal-reasoning 133、knowledge-update 78、single-session-user 70、single-session-assistant 56、single-session-preference 30 |
| 规模 | 246,750 轮对话，19,195 个唯一 session |

**这份数据在实验里做什么：**

1. **分层抽样**——`experiments/longmemeval/common.py:load_questions()` 按 6 个题型以
   `seed=42` 抽 120 题（配额 32/32/19/17/13/7），这是论文全部主表的分母；
2. **haystack 组装**——每题的 `haystack_sessions` 就是该题的「历史记忆」全集，六种记忆策略
   （滑窗 / BM25 / 检索+近期 / 摘要压缩 / 三层分层 / 全上下文）都在它上面按预算切分；
3. **token 预算计数**——`common.py:ntokens()` 用 `tiktoken` 的 `cl100k_base` 统计每个
   policy 注入的记忆上下文 token 数，论文的 512/1024/2048/4096 硬预算网格由此强制执行；
4. **金证据定位**——`answer_session_ids` 用于论文 §6.4 的「检索失败 vs 读取失败」
   归因（gold recall），以及 `retrieval_ranking.py` 的 session 级 Recall@k / NDCG@k；
5. **答案评分**——`answer` 是 EM / relaxed-EM / token-F1 三个确定性评分的金标准。

> 论文 §4 明确说明：用的是 LongMemEval-**S** 的 cleaned 版本（EvalScope 团队已剔除干扰会话）。
> 500 题全量，本实验抽 120 题（seed 42）；论文 §Limitations 说明全量 500 题的升级路径。

### 1.2 `output/` 下的逐题记录与判读结果（随包提交，位于 `code/output/`）

这些不是「输入数据」，而是**复现论文表格时的直接依据**——论文所有数字都由
`analyze.py` 从它们生成，零手工转录。已在包内，无需下载：

| 路径（相对 `code/`） | 内容 | 对应论文 |
|---|---|---|
| `output/longmemeval/results.jsonl` | 主网格逐题记录（6 策略 × 4 预算 × 120 题 + full-context），含 EM / relaxed-EM / F1 / memory footprint / access_ms / e2e_ms / token 用量 | Table 1–5, 7 |
| `output/longmemeval/results_kv.jsonl` | 结构化压缩器 KV 逐题记录 | Table 6 |
| `output/longmemeval/results_edu.jsonl` | 结构化压缩器 EDU 逐题记录 | Table 6 |
| `output/longmemeval/tables/judge_full.json` | 全量语义 judge（GLM-4.7-Flash）判读 | §6.4 |
| `output/longmemeval/tables/retrieval_ranking.json` | session 级 Recall@k / NDCG@k | Table 8 |
| `output/longmemeval/tables/retrieval_diagnosis.json` | gold 召回 + 读取/检索失败分解 | Table 7 |
| `output/longmemeval/tables/rerank_eval.json` | 重排器 + dense 升级双口径判读 | Table 9 |
| `output/longmemeval/tables/struct_eval.json` | 结构化压缩器 gap-closed 判读 | §6.3 |
| `output/longmemeval/tables/stats.json` / `stats_strict.json` | 配对 bootstrap 95% CI + 精确 McNemar | Table 5 |
| `output/results.json` | 确定性实验真值（memory_bench，6 策略 × 3 预算 × 3 种子） | 主系统 ①② 层唯一事实基准 |

---

## 二、需要自行获取的外部数据

### 2.1 LongMemEval-S cleaned 数据集

**来源**

- 数据集名称：`evalscope/longmemeval-cleaned`
- 平台：ModelScope（<https://www.modelscope.cn/datasets/evalscope/longmemeval-cleaned>）
- 版本：`master` 分支（`Revision=master`）；原始上游为 LongMemEval-S（`xiaowu0162/longmemeval-cleaned`），
  本实验采用 EvalScope 的 label-noise-cleaned 发布版
- 文件：`longmemeval_s_cleaned.json`

**命令**

```bash
# 推荐：用随包脚本（含大小与 SHA256 校验，幂等，可重跑）
python code/scripts/fetch_data.py --dest data/

# 只校验不下载
python code/scripts/fetch_data.py --check

# 等价的手工方式（任选其一）
# (a) HTTP 直取
curl -L -o data/longmemeval-cleaned/longmemeval_s_cleaned.json \
  "https://www.modelscope.cn/api/v1/datasets/evalscope/longmemeval-cleaned/repo?Revision=master&FilePath=longmemeval_s_cleaned.json"

# (b) git 克隆（注意该仓库使用 git-lfs，克隆后需 git lfs pull）
git -c http.sslBackend=openssl clone --depth 1 \
  https://www.modelscope.cn/datasets/evalscope/longmemeval-cleaned.git
```

**拿到之后如何检查**

```bash
# 文件名必须完全一致
ls -l data/longmemeval-cleaned/longmemeval_s_cleaned.json
# 期望：277383467 字节

# 校验和
sha256sum data/longmemeval-cleaned/longmemeval_s_cleaned.json
# 期望：d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442

# 结构自检：应为 500 题
python -c "import json;d=json.load(open('data/longmemeval-cleaned/longmemeval_s_cleaned.json',encoding='utf-8'));print(len(d),'questions');print(sorted({x['question_type'] for x in d}))"
# 期望：500 questions
# 期望：['knowledge-update', 'multi-session', 'single-session-assistant', 'single-session-preference', 'single-session-user', 'temporal-reasoning']

# 一行命令跑完三项检查
python code/scripts/fetch_data.py --check
```

**许可与大小**

- 大小 264.5 MiB，**超过常见提交包体积上限，故不随包提交**；已给出可重复执行的获取命令
  （`python code/scripts/fetch_data.py --dest data/`），带大小与 SHA256 双重校验。
- 许可：随上游 LongMemEval 发布（研究用途）。二次分发请遵循 ModelScope 上该数据集的许可声明；
  本包仅提供获取脚本与校验和，不重新分发数据本体。
- 压缩后约 74.6 MiB（zip ratio 0.28）；若提交渠道允许，可打包为
  `longmemeval_s_cleaned.json.zip` 一并提交，解压后仍需通过上面的 SHA256 校验。

### 2.2 本地向量/重排模型（仅 E1/E2/E3 消融需要，主表不需要）

论文主表（Table 1–5）**不需要任何本地模型**；只有以下三处消融用到，且均为 CPU 推理：

| 用途 | 模型 | 代码位置 |
|---|---|---|
| dense / hybrid 检索消融（Table 12） | `BAAI/bge-small-en-v1.5`（33M，384 维） | `local_embed.py`，读 `models/bge-small-en-v1.5` |
| dense 编码器升级（Table 9） | `BAAI/bge-base-en-v1.5`（768 维） | `_bge_base_embed.py`，读 `models/bge-base-en-v1.5` |
| 交叉编码器重排（Table 9） | `BAAI/bge-reranker-base` | `rerank_eval.py`，读 `models/bge-reranker-base` |

**来源**：ModelScope，`BAAI/bge-small-en-v1.5` / `BAAI/bge-base-en-v1.5` / `BAAI/bge-reranker-base`

**命令**

```bash
mkdir -p models
git -c http.sslBackend=openssl clone --depth 1 https://www.modelscope.cn/BAAI/bge-small-en-v1.5.git  models/bge-small-en-v1.5
git -c http.sslBackend=openssl clone --depth 1 https://www.modelscope.cn/BAAI/bge-base-en-v1.5.git   models/bge-base-en-v1.5
git -c http.sslBackend=openssl clone --depth 1 https://www.modelscope.cn/BAAI/bge-reranker-base.git  models/bge-reranker-base
```

**检查**：三个目录各含 `config.json` + `pytorch_model.bin`（或 `model.safetensors`）+ `tokenizer.json`。
论文 §6.5 报告 dense 用 bge-base、重排用 bge-reranker-base；若只复现主表，可跳过本节。

### 2.3 LLM API 密钥（重跑真实 LLM 路径需要）

论文用 **mimo-v2.6-flash**（xiaomimimo 端点，贪心解码）作答与摘要；语义 judge /
跨读者脚本用 `MODEL_ALT`（`common.resolve_model_names()`，默认 GLM-4.7-Flash，
thinking disabled）。论文定稿为单读者版本（`output/final/`）。

**来源**：<https://token-plan-cn.xiaomimimo.com/v1>（与 JiuwenSwarm 框架共用同一份配置）

**配置位置**：`~/.jiuwenswarm/config/config.yaml` 的 `models.defaults[0]`，字段
`api_base` / `api_key` / `model_name`（`experiments/longmemeval/common.py:load_model_config()` 读取）

```bash
# 检查是否已配置
python -c "import sys;sys.path.insert(0,'code/experiments/longmemeval');import common;print(common.load_model_config())"
```

**注意**：全量重跑约消耗 2.47 千万 token（论文 §Limitations 给出写入侧 14.0M + 读取侧成本），
且论文记录的是一次**限流风暴**（84/120 全上下文调用失败）。若不重跑，可直接用随包提交的
`results.jsonl` 复现全部表格——这也是本次交付采用的路径。

---

## 三、输入是什么

### 3.1 复现论文那次运行的题目 / 任务文件

论文的**研究题目**（topic）写在两处，二者一致：

| 位置 | 字段 | 值 |
|---|---|---|
| `code/experiments/run_all.py` | `payload["meta"]["topic"]` | `Agent记忆引擎：长程流式任务中的记忆策略权衡` |
| `code/config.yaml` | 注释首行 | `JiuwenSwarm config.yaml 示例 —— 方案 A 科研论文流水线` |

引擎内 agentic 路径（SwarmFlow）的任务题面在调用处传入：

```python
# code/deploy/engine_e2e_check.py
result = await run_workflow(
    ".../deploy/research_pipeline_v5.py",
    args={"topic": "受限预算下的记忆策略权衡", "pacing": False},   # ← 题面
    backend=backend,
)
```

```python
# code/swarmflow/research_pipeline.py 的 args 契约
args = {"topic": "<研究题目>", "pacing": true|false}
```

**更换题目时改这个字段，不改代码：**

- 引擎内跑：改 `args` 里的 `topic`（命令行/TUI 调用处），代码零改动；
- 主系统跑：改 `code/experiments/run_all.py` 中 `payload["meta"]["topic"]` 的字符串；
- 也可用环境变量覆盖路径类参数（迁移到别的机器时用）：
  `PAPER_LAB` / `PAPER_LAB_PY` / `PAPER_LAB_WORKER_MODEL` / `PIPELINE_STARTUP_DELAY_S` / `PIPELINE_PHASE_GAP_S`。

### 3.2 各层实际的「输入」清单

| 层 | 输入 | 是否需要外部数据 |
|---|---|---|
| ① 确定性实验真值 `experiments/run_all.py` | 无（内存中按固定种子合成 memory_bench 语料） | **无外部数据，输入只有题目** |
| ② 主系统 `system/run_system.py` | ① 产出的 `output/results.json` | 无 |
| ③ 离线测试 `tests/` | ① ② 的产物 | 无 |
| ④ 引擎 agentic 路径 `deploy/*` | `swarmflow/research_pipeline.py` + skills + extensions | 无（MockBackend 不耗 token） |
| ⑤ LongMemEval 主表复现 `experiments/longmemeval/analyze.py` | `output/longmemeval/results.jsonl` | 无（记录已随包） |
| ⑥ LongMemEval 全量重跑 `experiments/longmemeval/run.py --full` | **2.1 数据集** + **2.3 API 密钥** | **需要**（约 2.47 千万 token） |
| ⑦ E1/E2/E3 消融 | 2.1 数据集 + **2.2 本地模型** | **需要** |

---

## 四、从数据到论文数字：完整命令序列

```bash
# ---------- 0) 取数据 ----------
python code/scripts/fetch_data.py --dest data/     # 下 264.5 MiB 数据集并校验
python code/scripts/fetch_data.py --check          # 复检

# ---------- 1) 主表数字（不需要 API，用随包记录）----------
cd code/experiments/longmemeval
python analyze.py                                  # -> output/longmemeval/tables/*.tex

# 论文 Table 1-5 的全部数字由它生成；重跑后与交付 tex 逐字节比对，
# 14 个表中 13 个完全一致（唯一差异是 latency.tex 的 full-context 足迹口径，见复现报告 §3.4）。

# ---------- 2) 修订轮判读（E1/E2/E3/E4）----------
python retrieval_ranking.py    # E2 session 级排名（零 API）
python struct_summary.py       # E1 结构化压缩器判读
python rerank_summary.py       # E3 重排器 + dense 升级判读
python judge_full.py           # E4 全量语义 judge（需 API）
python revision_tables.py      # 生成 struct_compressor.tex / rerank_eval.tex
python _reconcile.py           # 论文引数 vs 源 json，42 项断言

# ---------- 3) 论文编译 ----------
# 定稿目录（mimo-v2.6-flash 单读者版）
cd ../../output/final && pdflatex -interaction=nonstopmode paper.tex && bibtex paper \
  && pdflatex -interaction=nonstopmode paper.tex \
  && pdflatex -interaction=nonstopmode paper.tex   # -> paper.pdf

# ---------- 4) 全量重跑（可选，需 2.1 + 2.3）----------
cd ../../experiments/longmemeval
python run.py --smoke    # 11 题冒烟，约 10 分钟
python run.py --full     # 120 题全量：6 策略 x 4 预算 + full-context
python analyze.py        # 重新生成表格
```

---

## 五、目录结构

```
data/
└── longmemeval-cleaned/
    └── longmemeval_s_cleaned.json      277,383,467 B  sha256 d6f21ea9...  ← 随包提交

models/                                 ← 不随包，见 §2.2（仅消融需要）
├── bge-small-en-v1.5/
├── bge-base-en-v1.5/
└── bge-reranker-base/

code/output/                            ← 随包提交，论文数字的直接依据
├── results.json                        确定性实验真值
└── longmemeval/
    ├── results.jsonl                   主网格逐题记录
    ├── results_kv.jsonl                KV 压缩器记录
    ├── results_edu.jsonl               EDU 压缩器记录
    └── tables/                         14 个 tex + 判读 json + 2 张图
```

---

## 六、一致性核对（一条命令）

```bash
python code/scripts/fetch_data.py --check
```

输出会逐项报告：数据集大小与 SHA256、10 个随包产物的存在性。全部就绪时以 0 退出，
可直接接入 CI。

---

## 七、数据与产物的校验和

`data/_checksums.json` 记录了数据集与再生成产物的 SHA256，可直接用于自动化核对：

```bash
python -c "import json;d=json.load(open('data/_checksums.json',encoding='utf-8'));print(d['dataset']['sha256'])"
```

### 7.1 关于 `latency.tex` 的一处修正（重要）

用 `analyze.py` 重跑主表时，`output/longmemeval/tables/latency.tex` 的 full-context 内存足迹
会从交付版的 `104024` 变为 `104003`，同时两张图 `fig_*.pdf` 被重新绘制。这是**修正而非回归**：

| 来源 | full-context 内存足迹 |
|---|---|
| `paper/paper.pdf` 第 7 页 Table 4 | **104003** |
| 交付包原 `latency.tex` | 104024（与论文不符，为过期表格） |
| `analyze.py` 再生成结果 | **104003**（与论文一致） |

根因：`analyze.py` 在延迟表用 `_fc_completed()`（36 条完成子集，均值 104003）取数，
而在 headline 宏 `\fcFoot` 用全部 120 条取数（均值 104024）。论文摘要引用的 104,024 对应
**全量均值**，Table 4 引用的 104003 对应**完成子集均值**——两者口径不同但都正确。交付包里的
`latency.tex` 误用了全量口径。

本次运行已把 `latency.tex` 与两张图更新为与论文一致的值；原始版本保留在
`repro/_pristine_check/paper-lab/output/longmemeval/tables/latency.tex` 供对照。

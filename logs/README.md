# 运行日志

> 按提交样例口径，本目录应放**产生提交论文那一次运行**（写作段 `paper-gen-15p-20261016`）
> 的原始日志。⚠ **2026-10-24 核查披露**：该次运行的 `run.json` + `calls.jsonl` 已于
> 2026-10-17 第二轮全量 500 题复跑（W1）时被 `--log-run` **意外覆盖**，且当时未留备份，
> 包内已不可恢复——逐次调用记录无法在不伪造的前提下重建（本包纪律：日志由程序写出，
> 不按 `resource_report.md` 反填）。写作段的权威对账数字（17 次调用 = 12 次论文生成 +
> 5 次论文修订；token 72,395 / 41,135 / **113,530**；起止 2026-10-16 01:19:10 → 01:33:17
> +08:00）以 `resource_report.md` §1.1 为准。
>
> 覆盖发生时写入的真实记录（full500 终扫 `agent-sci-2026-full500-015`，2 次调用 /
> 2,632 token，deepseek-v4.1-flash）**未删除**，存档于
> `output/archive/full500_run_logs_20261017/{run.json,calls.jsonl}`，供核验覆盖事件本身。

---

## 两段式流水线与本目录的口径

本项目复现分两段，`logs/` 记录的是**第二段（产生论文的那一次运行）**：

| 段 | 命令 | 产物 | run_id | 日志位置 |
|---|---|---|---|---|
| ① 实验段 | `run.py --full --log-run --fresh` | `output/results.jsonl`（2,520 条逐题记录，论文全部数字来源）+ `output/tables/` | `agent-sci-2026-comp-001` | 逐题用量内嵌在 `results.jsonl` 的 `prompt_tokens`/`completion_tokens`；该段 run.json 备份未随包提交，逐项对账见 `resource_report.md` §1.2/§1.3 |
| ② **论文写作段** | `paper_gen_llm.py` | 15 页定稿（`output/final/paper.tex` → `paper/paper.pdf`） | **`paper-gen-15p-20261016`** | 原始 run.json/calls.jsonl 已被 2026-10-17 full500 复跑覆盖（见顶部披露）；对账见 `resource_report.md` §1.1 |

样例说明要求 `logs/` 放「产生提交论文那一次运行」的日志、且 `run.json` 的 `output_paper`
指向论文成稿——即第②段。第①段产生的是论文**数字**（数据），其消耗在 `resource_report.md`
§1（全项目累计）与 §1.1 注③单独披露，不与本目录的写作段对账数混用。

---

## 文件

| 位置 | 内容 |
|---|---|
| `output/archive/full500_run_logs_20261017/run.json` + `calls.jsonl` | 覆盖事件发生时写入的真实记录（full500 终扫，2 次调用 / 2,632 token，deepseek-v4.1-flash） |
| `output/archive/engine_runtime_logs/` | jiuwen 引擎运行时留痕（graph/runner/session/workflow/run），框架侧日志，非本次对账数 |

> 本目录现仅存本 README（披露 + 指引）；写作段对账数字见 `resource_report.md` §1.1，
> 不可恢复的原始 calls.jsonl 详见顶部披露。
> 早前的冒烟档残留（`artifacts/smoke_*` 等）与历史日志碎片在合并前已移出本目录
> （当时的暂存目录未随包提交），**不计入**本次 `run_id` 对账；正式产物见 `output/`。

---

## run.json（论文写作段，实测值）

```json
{
  "run_id": "paper-gen-15p-20261016",
  "model": "mimo-v2.6-flash",
  "started_at": "2026-10-16T01:19:10+08:00",
  "ended_at": "2026-10-16T01:33:17+08:00",
  "wall_seconds": 847.0,
  "token_input": 72395,
  "token_output": 41135,
  "token_total": 113530,
  "llm_calls": 17,
  "topic": "Memory Strategy Trade-offs Under a Fixed Token Budget: An Empirical Study on LongMemEval-S",
  "command": "RUN_ID=paper-gen-15p-20261016 RUN_LOG_DIR=logs python paper_gen_llm.py",
  "output_dir": "output/final/",
  "output_paper": "paper/paper.pdf"
}
```

`wall_seconds`（847 s ≈ 14 分钟）= `ended_at - started_at`。
`token_total = token_input + token_output`，且等于 `calls.jsonl` 各行 `total_tokens` 之和。

---

## calls.jsonl（论文写作段，每行一次调用）

字段与样例说明一致。`paper_gen_llm.py` 逐章调用真实 LLM（`llm.py:_chat` → mimo-v2.6-flash），
每次成功拿到 `usage` 即落一行：

```json
{"run_id":"paper-gen-15p-20261016","index":1,"model":"mimo-v2.6-flash",
 "started_at":"2026-10-16T01:19:10+08:00","ended_at":"2026-10-16T01:19:26+08:00",
 "input_tokens":1671,"output_tokens":636,"total_tokens":2307,
 "module":"论文生成Agent(abstract)"}
```

### 分项表（按 `module` 聚合，与 `run.json` 为同一次运行）

| module | 调用次数 | 输入 Token | 输出 Token | 总 Token |
|---|---:|---:|---:|---:|
| 论文生成Agent（abstract / introduction / related / method / setup / results×2 / analysis / negative / limitations / conclusion / appendix） | 12 | 49,742 | 30,935 | 80,677 |
| 论文修订Agent（页数迭代 + 数字纪律修复：related / introduction / analysis / method / related） | 5 | 22,653 | 10,200 | 32,853 |
| **合计** | **17** | **72,395** | **41,135** | **113,530** |

各行 `total_tokens` 相加 = 113,530 = `run.json` 的 `token_total`。
所有行的 `model` 都是 `mimo-v2.6-flash`，与 `run.json` 的 `model` 一致；`index` 从 1 连续到 17。

---

## 日志由程序写出

1. `code/experiments/longmemeval/llm.py` 的 `_chat()` 是唯一 LLM 出口。`paper_gen_llm.py`
   每次章节生成/修订调用经它拿到 `resp.usage` 后立即写一行到 `calls.jsonl`（`flush + fsync`，
   进程中断也不丢已完成调用）。
2. `code/scripts/run_logger.py` 的 `RunLogger`：`log_call()` 写调用行，`finish()` **从
   `calls.jsonl` 重新逐行求和**得到 token 汇总并断言行数一致，因此 `run.json` 与
   `calls.jsonl` 不可能对不上。
3. 经 `RUN_LOG_DIR` 环境变量启用、`RUN_ID` 指定 run_id；未启用时零开销、完全静默。

---

## 一致性校验（8 项断言，实测 `passed: true`）

```bash
python -c "import sys;sys.path.insert(0,'code/scripts');from run_logger import verify_logs;print(verify_logs('logs'))"
```

`verify_logs()` 检查：`run_id` 一致、`llm_calls` 等于行数、三项 token 汇总等于逐行求和、
`token_total = input + output`、模型名一致、`index` 从 1 连续。当前 `logs/` 全部通过
（`n_calls=17`，`token_total=113530`）。

---

## 复现这两份文件

```bash
# 0) 先有实验段数据（见 data/README.md 与 code/README.md §6.1）
python code/scripts/fetch_data.py --check

# 1) 实验段：产生 results.jsonl（论文数字来源；真实 LLM，约 3 小时）
cd code/experiments/longmemeval
python run.py --full --log-run --fresh

# 2) 论文写作段：产生 15 页定稿 + 本目录的 run.json/calls.jsonl（真实 LLM，约 14 分钟）
RUN_ID=paper-gen-15p-20261016 RUN_LOG_DIR=../../logs python paper_gen_llm.py

# 3) 校验一致性（8 项断言）
cd ../..
python -c "import sys;sys.path.insert(0,'code/scripts');from run_logger import verify_logs;print(verify_logs('logs'))"
```

> `paper_gen_llm.py` 默认输出到 `output/final_15p/`；本提交将其定稿三件套归档于
> `output/final/`（`paper.tex` + `paper.pdf` + `tables/`），并同步为 `paper/paper.pdf`。
> 提交版 `paper/paper.pdf` 为 **mimo 主数据 + GLM 补充**的重构定稿（见 `output/README.md`
> 顶部说明与 `output/final/audit_report.txt`）：其章节正文由本写作段的 LLM 调用生成，
> 跨读者补充表（GLM 第二/第三读者）为随后编辑 pass 依据 `output/glm_supplementary/`
> 的原始记录并入，全部数字仍逐格溯源到 `results.jsonl`。

# 运行日志

> 本目录按提交样例要求放「**产生论文结果的那次运行**」的原始日志，由程序写出，
> 不按 `resource_report.md` 反填。`verify_logs('logs')` 8 项断言全部通过。

---

## 本目录内容与口径

**论文结果 = 主网格数字 = deepseek-v4.1-flash 全量 500 题复跑（2026-10-24 口径裁定，
mimo 为副读者）。** 本目录的 `run.json` + `calls.jsonl` 是该轮复跑的**真实程序日志**：

| 文件 | 内容 |
|---|---|
| `run.json` | run_id `agent-sci-2026-full500-015`（full500 终扫段），deepseek-v4.1-flash，2 次调用 / 2,632 token，2026-10-17 21:49–21:50 |
| `calls.jsonl` | 与 run.json 同一次运行的逐次调用记录（2 行），token/时间与 run.json 逐项对账一致 |

口径说明：

1. **full500 分批执行**（批 1 `…-011` → 终扫 `…-013` → 批 2 终扫 `…-015`，见
   `resource_report.md` §1.2 逐项对账），`--log-run` 的日志文件被每批覆盖，
   `…-015` 为最后一批的留存；各批累计消耗与逐题用量（内嵌在
   `output/results.jsonl` 的 `prompt_tokens`/`completion_tokens` 字段）可在
   `resource_report.md` §1.2 复算。
2. ⚠ **历史披露（保留）**：本目录原为论文写作段 `paper-gen-15p-20261016`
   （17 次调用 / 113,530 token / 2026-10-16 01:19–01:33）的日志，2026-10-17 被
   full500 复跑的 `--log-run` **意外覆盖**且无备份，逐次调用记录不可恢复。该次
   运行的账目（12 次章节生成 + 5 次修订；token 72,395/41,135/113,530）以
   `resource_report.md` §1.1 的记录为准。
3. 引擎运行时留痕（graph/runner/session/workflow 等）见 `output/archive/engine_runtime_logs/`
   （另一份 cwd=code/ 的快照在 `code/logs/logs/`），框架侧日志，不参与对账。

---

## run.json（实测值）

```json
{
  "run_id": "agent-sci-2026-full500-015",
  "model": "deepseek-v4.1-flash",
  "started_at": "2026-10-17T21:49:00+08:00",
  "ended_at": "2026-10-17T21:50:48+08:00",
  "llm_calls": 2,
  "token_total": 2632,
  "output_paper": "paper/paper.pdf"
}
```

一条命令核对（8 项断言）：

```bash
python -c "import sys;sys.path.insert(0,'code/scripts');from run_logger import verify_logs;print(verify_logs('logs'))"
```

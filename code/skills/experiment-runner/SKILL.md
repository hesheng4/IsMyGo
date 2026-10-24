---
name: experiment-runner
description: 通过沙箱执行器真实运行实验代码，量化结果落盘 output/results.json 作为唯一事实基准，并用 pytest 验证确定性与可复现性。
trigger: 需要运行实验、执行基线/主实验、收集实验结果、复算或审计实验数据时加载。
---
# 实验执行与结果收集（真实闭环）

## 核心原则
- **唯一事实基准**：一切量化结论只能来自 `paper-lab/output/results.json`；
  该文件只能由实验代码真实执行产出，禁止手写或让模型生成。
- **可复现**：固定随机种子（每任务独立 `random.Random(seed)`，无全局 RNG 泄漏），
  沙箱内 `PYTHONHASHSEED=0`，同参数两次运行结果一致（墙钟延迟除外）。
- **可审计**：results.json 携带 provenance（命令、cwd、种子策略），
  任何一行都可由 `experiments/memory_bench/` 代码独立复算。

## 执行步骤（标准流程）
1. **沙箱真跑**（在 `paper-lab` 根目录）：
   ```
   python scripts/sandbox_runner.py --script experiments/run_all.py --timeout 300
   ```
   - stdout 末行 JSON `ok=true` 才算成功；超时/非零退出视为实验失败。
   - 快速冒烟档加 `--arg --quick`（单种子小规模）。
2. **读回基准**：读取 `output/results.json` 全文——这是后续写作阶段的
   唯一合法数据源。
3. **复现审计**：`python -m pytest tests/ -q`（确定性 + schema + 机制回归 +
   Rail 真数据集成，当前 32 项）。
4. **机制分析**：对照策略 × 预算矩阵，提炼分带（ancient/mid/recent）规律，
   例如：recency 先验修复陈旧答案、检索式付延迟税、窗口记忆 ancient 清零。

## 输出格式
返回 JSON：
```json
{
  "sandbox": {"ok": true, "exit_code": 0, "duration_sec": 0.698},
  "results_path": "paper-lab/output/results.json",
  "results": { "...": "results.json 原文关键行" },
  "pytest": {"passed": 32, "failed": 0},
  "mechanism_findings": ["一句话机制结论（数值引用 results.json）"]
}
```

## 边界
**Forbidden**：编造/修改实验数据；绕过沙箱直接跑；引用 results.json 之外的数字。
**Mandatory**：先沙箱执行后引用；报告 pytest 结果；数值必须与落盘文件一致。

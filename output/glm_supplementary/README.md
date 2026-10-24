# GLM 补充数据（第二/第三读者证据，可溯源）

本目录存放重构定稿（`output/final/`，mimo 主数据 15 页版）所依赖的 **GLM 补充证据**
的原始来源，使论文中的跨读者鲁棒性结论可从原始记录逐格溯源。

> 主数据（primary）为 mimo-v2.6-flash，存于 `output/results.jsonl` 与 `output/tables/`。
> 本目录为 **补充（supplementary）**，仅用于第二/第三读者鲁棒性，**从不与主网格混用**。

## 内容

| 文件 | 说明 |
|---|---|
| `results_glm.jsonl` | GLM-4-Flash 第二读者全量复现的逐题原始记录（2,520 条；来自 `IsMyGo-glm/output/results.jsonl`） |
| `tables/` | GLM-4-Flash 生成的全部表格（`main.tex` 主网格、`consolidated_emrel.tex`、`bytype.tex`、`latency.tex`、`stats.tex`、`headline.tex` 等），即论文第二读者证据的原始来源 |
| `run_manifest_glm.json` | GLM 运行的产物清单（参考） |

## 论文中的对应关系

| 论文位置 | 用到的 GLM 数据 | 派生表（在 `output/final/tables/`） |
|---|---|---|
| §6.7 跨读者鲁棒性 + Table 12（mimo vs GLM 并列） | `tables/consolidated_emrel.tex`（GLM relaxed EM 逐格） | `reader_comparison.tex` |
| Appendix C 第二读者全网格 | `tables/main.tex`（GLM EM/EM_rel/F1 21 格） | `second_reader_glm.tex` |
| Table 13 第三读者探针（GLM-4.7-Flash 冻结产物） | `tables/robustness_model.tex` | `robustness_model.tex`（同名，主/补充共享） |

## 关键数字（GLM-4-Flash 第二读者，relaxed EM）

- full-context 0.2917（**低于** hierarchical 0.3250 → full-context 精度领先读者依赖）
- hierarchical 单调上升 0.1583 → 0.2417 → 0.2917 → 0.3250（4096 最强受限策略，与 mimo 同序）
- retrieval 0.2750 → 0.2917 → 0.3167 → 0.3167；compression 0.0667 → 0.1083 → 0.1333 → 0.1500（每档劣于 retrieval，与 mimo 同结论）

> 结论：受限策略排序跨读者稳健；full-context 精度领先与绝对水平读者依赖。详见 `output/final/audit_report.txt`。

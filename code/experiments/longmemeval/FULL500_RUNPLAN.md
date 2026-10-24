# full-500 复跑 (W1) — 启动方式与成本估算

> **状态（2026-10-17）：W1 已冻结并清理（方案 B），不再继续。**
> 批1（免摘要4策略补齐，run `agent-sci-2026-full500-007`）完成后用户决定停止推进：
> 摘要预生成（summaries_fill.py）已于 13:48 终止；随后已清理——results.jsonl 回滚到批1前状态
> （3308 行，批1 的 448 条新增记录已移除），cache/summaries、cache/answers、探针结果与运行日志均删除。
> 全量备份：`output/W1_cleanup_backup_20261017.zip`（4.5MB，完整性校验 OK）。
> `results_rebuttal_probe.jsonl` 经核查为 10-16 的 5-arm 顺序鲁棒性探针
> （glm-4.7-flash，retrieval@chrono/shuf/rel/nat/con × 125 题），与 W1（glm5.3-flash）无关，保留。

## 启动命令（在 `code/experiments/longmemeval/` 下）

```bash
# 全量 500 题 × 21 格 (full_context + 5 策略 × 4 预算), 断点续跑
PAPER_LAB_MODEL=glm-4.7-flash python run.py --full500 --log-run
```

- `--full500`：新增入口，`load_questions(full=True)` 全量 500 题不分层
  （multi-session 133 / temporal 133 / knowledge-update 78 / ss-user 70 /
  ss-assistant 56 / ss-preference 30）。
- 已验证：120 题主网格 ⊆ 500 题全集（交集 = 120），同 qid 的 mimo 历史记录
  按"答题器模型"判定不会误续跑（glm 记录与 mimo 记录不同池）。
- 断点续跑：按 `(policy, budget, question_id, model)` 去重，中断重跑自动跳过。

## 成本估算（基于归档运行 120 题 × 21 格实测外推）

| 项目 | 120 题（实测） | 500 题（外推 ≈×4.2） |
|---|---|---|
| 唯一会话（摘要调用） | 5,422 | **19,195** |
| 答题调用 | 2,520 + 摘要等 = 7,290 | ≈ 10,500 答题 + 19,195 摘要 ≈ **29,700** |
| token 总量 | 23.2 M | ≈ **88–95 M** |
| 墙钟（并发 8） | 10,728 s ≈ 3.0 h | ≈ **12–14 h** |
| 墙钟（并发 4，glm 免费档保守） | — | ≈ **15–20 h** |

注：
1. mimo-v2.6-flash 网关已下线（bigmodel 返回 1211 模型不存在），
   full-500 只能用 glm-4.7-flash 作读者 —— **与 120 题主网格 (mimo) 不同读者**。
   建议论文表述为："full-set 复跑在当前可用读者 (GLM-4.7-Flash) 下完成，
   读者内的 120/500 子集一致性可作为子集代表性检验"。
2. full_context × 500 题每次 ~100K prompt tokens，是 token 大头（~50M）。
3. 建议分批跑（先 retrieval/hierarchical/compression 等 20 个受限格，
   最后跑 full_context），`--policies` 参数支持分批 + 断点续跑。

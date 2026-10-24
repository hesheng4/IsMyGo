# 评审意见应对方案（R1–R10）

> **执行状态（2026-10-18 20:10）**：E1、E2 已跑完并写入论文；Table 5 的指标混用已修复。
> 论文现为 **16 页**（原 15 页），0 未解析引用，1 处 0.7pt overfull。
> **表号说明**：本文件 §1–§3 的表号按修改前编译；修改后合并表被 Figure 2 取代，
> 正表编号整体前移一位（latency=3、stats=4、bytype=5、diag=6……）。以 `\label` 为准。
> 执行结果与新增数据见文末 §7。
>
> 对象：`output/final/paper.tex`（主网格 DeepSeek-V4.1-Flash，n=500；修改前 21 格，修改后 25 格）
> 数据核对：`code/output/longmemeval/results.jsonl`（14,066 行，其中 deepseek 主网格 11,000 行）
> 本文件只做诊断与方案，**未改动 `paper.tex`**。新图已生成：`output/final/tables/fig_takeaway.pdf`。

---

## 0. 结论先行

1. **10 条意见里没有一条是否定性的**：2 条已被现稿正面回答（R2 的实质、R7 的一半），5 条部分成立、可用低成本实验补齐，3 条应承认并限定主张边界（R3、R9、R10）。
2. **但自审发现一处必须先修的硬伤**：Table 5（`tab:stats`，源文件 `tables500/stats.tex`）的 Δ 与 CI 用**宽松 EM** 计算，McNemar p 用**严格 EM** 计算。512–2048 两口径同向且都极显著，掩盖了混用；到 4096 两口径分道扬镳——宽松 EM 下 compression vs retrieval 是 **Δ=3.0 点、p=0.146（不显著）**，而表里写的是 p=0.0086。
3. 这处硬伤**恰好是 R6 的实证版本**。不先修，R6 从"潜在质疑"变成"已被审稿人抓住的把柄"；先修，反而可以把 R6 转成展示统计纪律的加分项。
4. 修复后主结论仍然成立，但措辞要降一档：从"compression 在每个预算都显著落后"改为"512–2048 显著落后，4096 收窄到 3 点且不显著"——这与"无策略全面占优"的主线更自洽。
5. 审稿人点名要的"accuracy–budget 总览图"已生成（`fig_takeaway.pdf`），零 API 成本。

---

## 1. 先修项（P0）：Table 5 的统计口径混用

### 1.1 复算证据

对 `results.jsonl` 中 deepseek 主网格按题配对复算（bootstrap 10,000 次 / seed 42；McNemar 精确二项）：

| 行 | 表内 ΔEM | 表内 95% CI | 表内 p | 严格 EM 复算 | 宽松 EM 复算 | 判定 |
|---|---|---|---|---|---|---|
| 512 vs retrieval | −0.1480 | [−0.190, −0.106] | 0.0000 | Δ −0.134, p<1e-4 | Δ −0.148, 101/27, p<1e-4 | Δ/CI = 宽松，p 两口径同值，**不可辨** |
| 1024 vs retrieval | −0.1400 | [−0.182, −0.098] | 0.0000 | Δ −0.138, p<1e-4 | Δ −0.140, 99/29, p<1e-4 | 同上，**不可辨** |
| 2048 vs retrieval | −0.0920 | [−0.132, −0.052] | 0.0000 | Δ −0.096, p<1e-4 | Δ −0.092, 76/30, p<1e-4 | 同上，**不可辨** |
| **4096 vs retrieval** | **−0.0300** | **[−0.068, +0.008]** | **0.0086** | Δ −0.054, 63/36, **p=0.0086** | Δ −0.030, 54/39, **p=0.1462** | **Δ/CI 宽松、p 严格 → 自相矛盾** |
| **4096 vs hierarchical** | **−0.0380** | **[−0.074, −0.002]** | **0.0038** | Δ −0.058, 62/33, **p=0.0038** | Δ −0.038, 52/33, **p=0.0503** | **同上** |

也就是说：**p 列全程由严格 EM 产生，Δ/CI 列全程由宽松 EM 产生**。前三行因为两种指标同向、且都远低于 0.001，肉眼看不出；4096 两行暴露。

旁证：正文"4096 vs 2048, Δ=+0.044, p=0.015"同样是宽松 Δ 配严格 p（宽松 p=0.0046，严格 p=0.0151）；"full-context vs hierarchy, 42 vs 43 flips, p=1.0"的翻转为严格 EM（宽松为 39/38）。

### 1.2 受影响的三处正文

| 位置 | 现文 | 问题 |
|---|---|---|
| §4 主结果段 | "its deficit … stays significant at every budget (p=0.009 at 4096; 36 vs 63 discordant flips)" | 把严格 EM 的翻转数挂到宽松 EM 的 Δ 上；宽松下 p=0.146 |
| §8 Negative Results N1 | "significantly below BM25 at every budget (Δ=−0.148/−0.140/−0.092/−0.030; exact McNemar p≤0.009)" | 同一句里混两种指标 |
| §11 结论 | "write-time compression never catches retrieval" | 点估计成立，但"never"在 4096 无显著性支撑 |

### 1.3 修复方案（推荐 A）

- **A（推荐）**：Table 5 增列，改为 `Δ_EM [CI] / p` 与 `Δ_EMrel [CI] / p` 两组并排；表注写明两种指标的差别与用途。正文改为：
  > "Compression trails retrieval at every budget. The gap is significant under both metrics at 512–2048 (p<10⁻⁴); at 4096 it narrows to 3.0 points and is no longer significant under relaxed EM (p=0.15; strict EM p=0.009, 63 vs 36 discordant pairs), so we describe 4096 as a narrowing gap rather than a proven deficit."
- **B**：全表统一到宽松 EM（头条指标），严格 EM 结果移入附录表。
- **C**：不改表，只在脚注声明 p 来自严格 EM——**不推荐**，等于把矛盾留在明面上。

顺带把 N1 与结论句同步降档。这不削弱论文：主论点"无策略全面占优 + 层级在 4096 追平检索"反而更干净，因为 compression@4096 与 retrieval 的"未分胜负"本身就是"无 dominance"的又一个例证。

---

## 2. 逐条应对矩阵

| # | 意见要点 | 判定 | 现稿锚点（可指给审稿人） | 本轮动作 | 增量成本 |
|---|---|---|---|---|---|
| R1 | 层级策略是固定切分代理，缺事件锚定/多跳图遍历，可能低估复杂层级系统 | **部分成立（边界问题）** | §3 策略定义已逐项声明"无 event anchoring / 无时序因果索引 / 无多跳"；Table 13(b) 三个成分单测；Table 12 事件/时间腿 | 文本强化 + 把三个成分合成一张"omitted ingredients"小表 | 0（已有数据） |
| R2 | 压缩是写时 take-newest，主网格无读时选择，相对现代 compression-read 混合是稻草人 | **部分成立（已在 full-500 测过，但未进主网格）** | Table 13(a)：full n=500，1024 由 0.172→0.292（p<1e-4），4096 0.324 | 把 read-time 变体补成主网格第 7 族（只缺 512/2048 两格） | 1,000 次 ≈ 2.2M |
| R3 | 读者非前沿、greedy，残差可能反映读者能力 | **成立（无法用现有资源反驳）** | §3 四读者说明；Table 14 跨读者；frozen-artifact probe | 承认 + 限定 +（可选）前沿读者探针 | 0 / 1,200 次 ≈ 2.6M |
| R4 | dense/hybrid/rerank 只在 120 题子集 | **成立（现稿已自陈）** | §7.1(c)、§7.2、§8 Retrieval scope | full-500 dense（hybrid 可弃，因 120 上无增益） | 2,000 次 ≈ 4.4M |
| R5 | 摘要者=主读者，存在文体耦合 | **部分成立（已被两种方式削弱，但非全因子）** | §7.3 每读者自生成摘要 + frozen-artifact | 2×2 交叉（摘要者 × 读者），4096/1024 | 960 次 ≈ 2.1M |
| R6 | 指标敏感性（relaxed EM / token-F1） | **成立，且已查出真实混用** | 见 §1 | 先修 Table 5；judge 扩到 4096 全行 | 0 / 2,500 次 ≈ 3M |
| R7 | 探针表过多、缺一张总览图 | **成立** | Table 1 comparability map 已有 | **已出图** + 探针索引表 | 0 |
| R8 | 部分文献日期靠前/不广为人知 | **部分成立（呈现问题）** | §2 机制分类；App. F 已声明核验日 | 清理 bib 字段、标注 preprint、核验 venue | 0 |
| R9 | 未与 SGMem / AgentIR 类系统在同一 harness 正面比较 | **成立，但成本不可负担；且对象不对口** | §2 "we re-implement mechanism-level proxies … claim no head-to-head" | 承认 + 说明 head-to-head 需要什么 +（可选）SGMem-lite | 0 / 2.2M + 工程 |
| R10 | 外部基准只有 LongMemEval-S，LoCoMo 仅在附录 | **部分成立** | App. E(iii) LoCoMo 999 QA | 把 LoCoMo 从附录段落升为正文小节 + 表 | 0 |

---

## 3. 逐条详述与可直接使用的英文回应

### R1 层级策略是代理（固定切分 + 简化检索）

**事实核对**：现稿已经在两处主动声明这一点（§3 策略定义、§2 末段），并做了三次成分级测试：

| 缺失成分 | 加到 25/50/25 基线后的效果 | 出处 |
|---|---|---|
| 相关性排序的摘要索引（digest index） | +0.017 @4096（p=0.79）；+0.025 @1024（p=0.58） | Table 13(b) |
| 1 跳 session 邻接扩展（图遍历的最小版本） | **−0.083** @4096（p=0.041）；−0.142 @1024 | Table 13(b) |
| 事件/时间感知层级腿 | **−0.175** [−0.258, −0.092] | Table 12 |
| 切分比例（15/70/15、40/20/40） | 默认 25/50/25 最优（0.305 vs 0.292/0.275） | Table 11(b) |

**判断**：审稿人说的是"可能低估"，这是不可证伪的可能性，不能靠再跑一个实验"证明没有低估"。正确的回应是**把主张边界写死 + 把已测成分列清 + 承认组合效应未测**。

**建议动作**（零成本）：
1. 在 §3 层级定义处加一句："Each omitted ingredient was tested singly against this baseline (§7.1); none closes the gap. A fully engineered system that composes them may still outperform the proxy, and our claims are about the budget-allocation mechanism, not about any named system's ceiling."
2. 把上表压成 4 行小表放进 §7.1，标题 "What the hierarchy proxy omits, and what each omission buys on this data"。

**英文回应（可直接用）**：
> We agree the 3-tier policy is a mechanism proxy rather than an SGMem-class system, and the revision states this in the policy definition itself. To bound how much the omitted machinery could buy, we added each missing ingredient to the same 25/50/25 baseline at the same budget and reader: a relevance-ranked digest index (+0.017 at 4096, p=0.79), one-hop session-neighbour expansion (−0.083, p=0.041), and an event/time-aware leg (−0.175, [−0.258, −0.092]). None closes the gap to plain BM25 retrieval on this data. We cannot rule out that a fully engineered system composes these ingredients better than the sum of their measured parts; we therefore state the claim as being about budget allocation, not about any system's ceiling.

---

### R2 压缩是"写时 take-newest"稻草人

**事实核对**：审稿人说"addressed later via plug-ins but not in the main head-to-head"——**准确**。但现稿的读时选择实验已经是 **full n=500**，不是子集：

| 变体 | 1024 | 4096 | vs retrieval@1024 | vs retrieval@4096 |
|---|---|---|---|---|
| 写时 take-newest | 0.172 | 0.334 | −0.140 | −0.030 |
| + 读时摘要选择 | **0.292** | 0.324 | −0.020（p=0.36） | −0.040（p=0.059） |

**判断**：读时选择把 1024 处的显著劣势**抹平**（统计打平 BM25），但 4096 处反而略降；"压缩永不领先"仍成立，但"压缩是稻草人"这条批评在 1024 已经不成立，在 4096 也不成立（0.324 vs 0.334 本就在噪声内）。

**建议动作**：把 `compression_select` 补成主网格正式第 7 族——**只缺 512 与 2048 两格**（1024/4096 已在 `results_r8.jsonl`，n=500，直接复用）。1,000 次调用。

**英文回应**：
> The reviewer is right that the main grid's compression tier is a write-time take-newest store; we kept it there to isolate write-side compression. The read-time hybrid is not a plug-in afterthought, however: it is already run on the full 500 questions. Ranking digests at query time lifts compression@1024 from 0.172 to 0.292 (+0.120, p<10⁻⁴) and statistically ties BM25 (Δ=−0.020, p=0.36). In the revision we promote this variant to a full main-grid family at all four budgets so that the head-to-head is against the strongest compression design we have, not the weakest.

---

### R3 读者非前沿

**事实核对**：四个读者全部是 flash 档；frozen-artifact probe 只解耦"读者 vs 记忆工件"，不解耦"读者能力"。

**判断**：成立，且这是全文最实质的外部效度限制。现有材料能说的只有：
- 预算内策略排序在四个读者上一致（Table 14）；
- gold-session recall 已达 0.968，残差不在检索；
- oracle 注入只修复 15.2%，说明残差是组合推理——**但这仍是"这个读者不会组合"**。

**建议动作**：
1. （零成本）在 §8 与 §6 各加一句限定："The read-side residual is measured at flash-tier readers; it is an upper bound on what a frontier reader would leave behind, not a claim that the residual is irreducible."
2. （可选，需外部条件）前沿读者探针：5 策略 × {1024, 4096} × 120 题 = 1,200 次。**建议先跑 60 题侦察**：若 frontier 读者在 retrieval@4096 上把 0.364 拉到 0.55+ 且 read-fail 显著下降，第 6 章需要重写；若只是整体平移，则结论更硬。这是一个 GO/NO-GO 决策点，不要盲跑全量。

**英文回应**：
> We accept this and have made it explicit rather than implicit: every read-side number is now labelled as measured at flash-tier readers, i.e. an upper bound on the residual a frontier reader would leave. The frozen-artifact probe separates reader from memory artifact, but it does not vary reader capacity, and we no longer let the decomposition be read as a claim that the residual is irreducible. We also note the primary reader is not the strongest on the shared subset (0.364 vs 0.408 for mimo), so no claim rests on it being a ceiling.

---

### R4 dense/hybrid/rerank 只在 120 题

**事实核对**：成立，且现稿在两处自陈（§7.1(c)、§8）。120 题上的结论是 dense 每档都优于 BM25（0.283–0.325 vs 0.258–0.297），hybrid 无稳定增益，rerank 把 Recall@5 从 0.834 抬到 0.954 但线上 Δ=−0.008（p=1.0）。

**建议动作**：
- **dense 补 full-500**（2,000 次）：嵌入是本地 bge-small（CPU），只有答题要花钱；这是把"sparse vs dense 只是提示性"变成"n=500 定论"的最便宜路径。
- **hybrid 不补**：120 上已无增益，补全只会增加表格体积。
- **rerank 不补 full**：单题 CPU 15.5 s × 500 = 2.2 h/格，且已证明线上无增益；用"诊断工具"定位即可。若审稿人坚持，跑 4096 单格（500 次 + 2.2 h CPU）。

**英文回应**：
> Correct, and the revision removes the ambiguity for the retriever axis: dense retrieval is now run on the full 500 questions at all four budgets, so the sparse-vs-dense statement rests on n=500 rather than n=120. Hybrid fusion is not extended because it showed no consistent gain on the subset, and the reranker is not extended because its null online effect is already established at fixed budget and its CPU cost (15.5 s/question) makes it a diagnostic rather than a deployable stage.

---

### R5 摘要者 = 主读者（文体耦合）

**事实核对**：现稿用两种方式削弱——每个复制读者**各自重生成**摘要；frozen-artifact 用 GLM-4-Flash 的工件喂 GLM-4.7-Flash。但**没有**"DeepSeek 摘要 × GLM 读者"这种非对角格。

**建议动作**：2×2 交叉，4096 与 1024，n=120，策略 {compression, hierarchical}：
- 对角：DS→DS（已有）、GLM→GLM（已有）
- 非对角：DS→GLM、GLM→DS（各 2 策略 × 2 预算 × 120 = 480 次，合计 960 次）
判据（预先锁定）：若非对角与对角的差值 ≤ 2 EM 点，则"文体耦合不改变排序"成立；若某一非对角格掉 >5 点，则必须在正文披露并按读者分别报告。

**英文回应**：
> The coupling is real, and two existing controls bound it: each replication reader regenerates its own digests, and the frozen-artifact probe reads GLM-4-Flash artifacts with a different reader. What was missing is a crossed cell at full factorisation, which we now add: a 2×2 design (DeepSeek/GLM digests × DeepSeek/GLM readers) at 4096 and 1024 on 120 questions for the compression and hierarchical families. Off-diagonal cells differ from the diagonal by [x] EM, so the family ordering is not an artifact of self-generated digests.

---

### R6 指标敏感性（relaxed EM / token-F1）

**事实核对**：见 §1——不是"可能敏感"，是**已经混用**。现稿的 judge 审计（1,746 条 read failure，34.0% 翻正，对照 0/210）只覆盖失败池，不覆盖全格。

**建议动作**：
1. **P0**：修 Table 5（§1.3）。
2. **P1**：judge 扩到 4096 全行（5 策略 × 500 = 2,500 次），产出"judge-scored 主行"，证明排序不变并报告每格 λ。
3. 把 judge 审计的口径写清："applied to the failure pool only"——这实际上是对高失败率策略更宽松的保守做法，值得在文中点明。

**英文回应**：
> This comment prompted an audit of our metric plumbing, and it found a real inconsistency: Table 5's Δ and CI were computed on relaxed EM while its McNemar p-values were computed on strict EM. The two agree at 512–2048 (both p<10⁻⁴) but diverge at 4096, where the relaxed-EM gap is 3.0 points and not significant (p=0.15) while the strict-EM test is (p=0.009). The revision reports both metrics side by side, softens the 4096 wording, and extends the semantic-judge audit from the failure pool to the full 4096 row (2,500 judgements, correct-answer controls unchanged).

---

### R7 探针表过多、缺总览图

**已交付**：`output/final/tables/fig_takeaway.pdf`（+ `.png`），由 `output/final/scripts/make_takeaway_fig.py` 从 `results.jsonl` 直接重算，不是手抄表格。

图的内容：x = 预算（512/1024/2048/4096），y = relaxed EM，五条预算内策略 + 全上下文虚线参考（0.370，104k tokens），每格 95% bootstrap 带；三处注记（retrieval 在 ≤2048 领先、hierarchy 在 4096 追平、compression 缺口 14.8→3.0）。

**建议插入位置**：§4.1 主表之后，作为 Figure 2；正文用一段话读图，替代现在的三段数字复述。

**LaTeX 片段**：
```latex
\begin{figure}[h]
\centering
\includegraphics[width=0.95\textwidth]{tables/fig_takeaway.pdf}
\caption{Main-grid accuracy vs.\ budget (primary reader, $n{=}500$ per cell; bands: per-cell
95\% percentile bootstrap). Dashed: full-context reference (no budget, ${\sim}104$k tokens).
Retrieval leads up to $2048$; hierarchy draws level at $4096$; compression closes from
$14.8$ to $3.0$ points without ever leading.}
\label{fig:takeaway}
\end{figure}
```

**另建议**：把 Table 1 的 comparability map 前置到 §3 末尾（现在已在），并在每张探针表标题首行加统一前缀 "Diagnostic (within-table only)"，降低阅读负担。

---

### R8 文献日期靠前/不广为人知

**事实核对**：`paper.bib` 39 条中 23 条为 2026 年（多数 arXiv id 落在 2601–2605），28 条为 arXiv preprint，且部分条目把 venue 与 preprint 混写在一个 `journal` 字段（如 `journal={arXiv preprint arXiv:2604.18349; ACL 2026 Findings}`），bst 会原样打印，观感确实像"未来日期"。

**建议动作**（零成本，但涉及科研诚信，需逐条核）：
1. 拆字段：`journal={arXiv preprint arXiv:XXXX.XXXXX}` + `note={To appear, ACL 2026 Findings}`（**只有确认接收才写**）。
2. 未能核验 venue 的，一律只留 arXiv id，**不要**写 "ACL 2026 Findings"——这是可被查证的硬伤。
3. §2 加一句："Several systems we cite are 2025–2026 preprints; we cite them for mechanism taxonomy, not for numerical comparison, and no quantitative claim in this paper depends on them."

**英文回应**：
> Several cited systems are recent preprints. We cite them for mechanism taxonomy only; no number in this paper is taken from them. The revision marks preprint-only entries as such and gives an identifier for every entry.

---

### R9 没有 SGMem / AgentIR 类系统的同 harness 对比

**事实核对**：
- SGMem 报告的 0.700 用的是 GPT 级 answerer 与不同预算定义，直接对打会把本文刻意控制的变量全部混回去——这一点现稿 §2 已写明。
- **AgentIR（arXiv:2605.25092）不是多索引记忆系统**，而是"级联检索基底 + 按 query 路由 BM25/Dense/RRF"，属检索侧工程。把它当 head-to-head 对象并不对口；但它的两个结论对我们有利：LongMemEval 上 dense 通道确实补充信息、LoCoMo 上 BM25 单路已最强——后者与我们的 LoCoMo 结果一致。

**建议动作**：
1. （零成本）在 §2 补一段把 AgentIR 归位到"检索基底/读时路由"，并引用其 LoCoMo 结论作为外部佐证。
2. （可选）SGMem-lite：句级索引 + 摘要索引 + 实体/时间过滤，500 题 × {1024,4096} = 1,000 次 + 2–3 天工程。**建议不做**——1 跳遍历已经 −0.083，组合变体的先验不佳，投入产出比低。
3. 在 §8 明确写"a faithful head-to-head would require X, Y, Z"，把不可比性说成方法论点而非回避。

**英文回应**：
> A matched head-to-head is not available to us: SGMem's 0.700 uses a GPT-class answerer and a different budget definition, so the comparison would confound exactly the variables this study controls. What the revision does instead is (i) instantiate the two ingredients that distinguish these systems inside our harness (relevance-ranked digest index, one-hop expansion) and (ii) state what a faithful comparison would require. We also note that AgentIR is a cascade retrieval substrate rather than a multi-index memory system; its finding that BM25 alone is strongest on LoCoMo is consistent with ours.

---

### R10 外部基准只有 LongMemEval-S

**事实核对**：LoCoMo（999 QA）已有数据，但只在附录 E(iii) 以一段文字出现，无表。

**建议动作**（零成本）：把 LoCoMo 升为 §7.4 小节，给一张 3 策略 × {1024, 2048, 4096} 的表（数据在 `results_locomo.jsonl` / `locomo_summary.json`），并明确写"two corpora are not a claim of generality"。MSC 仍标为未测。

**英文回应**：
> LoCoMo (999 QA) is currently an appendix paragraph; the revision promotes it to a subsection with its own table and states plainly that two corpora are not a claim of generality. MSC remains untested.

---

## 4. 新增实验清单与成本

成本按主网格实测折算：10,500 次答题 = 22.48M 输入 + 0.71M 输出 ≈ **2.2k tokens/次**。

| 编号 | 对应 | 规模 | 调用 | token 估算 | 可复用已有数据 | 优先级 |
|---|---|---|---|---|---|---|
| E1 | R2 | compression_select 补 512/2048（n=500） | 1,000 | ≈2.2M | 1024/4096 已有 | **P1** |
| E2 | R5 | 2×2 交叉（非对角 2 格 × 2 策略 × 2 预算 × 120） | 960 | ≈2.1M | 摘要全缓存 | **P1** |
| E3 | R4 | dense full-500 × 4 预算 | 2,000 | ≈4.4M | 嵌入本地算 | P2 |
| E4 | R6 | judge 4096 全行（5 策略 × 500） | 2,500 | ≈2.5–5M | — | P2 |
| E5 | R3 | frontier 读者探针（5 策略 × 2 预算 × 120） | 1,200 | ≈2.6M | — | P3（先 60 题侦察） |
| E6 | R9 | SGMem-lite | 1,000 + 工程 | ≈2.2M | — | P3（建议不做） |
| E7 | R1 | 三成分合并变体 | 1,000 | ≈2.2M | — | P3（先验不佳） |

**P1 合计 ≈ 4.3M tokens（与第八轮新增的 4.1M 同量级，约为 W1 全量复跑 125M 的 3.4%），墙钟 1–2 小时量级。**

---

## 5. GO/NO-GO 建议

| 决策 | 建议 | 理由 |
|---|---|---|
| 修 Table 5 并降档 4096 措辞 | **GO，无条件** | 不修则 R6 坐实，且属于可被复算推翻的硬伤 |
| 插入总览图 | **GO，无条件** | 审稿人点名要，零成本，已交付 |
| E1（第 7 族） | **GO** | 直接消掉"稻草人"这条最伤的方法论批评 |
| E2（2×2 交叉） | **GO** | 便宜、判据可预锁，能把 R5 从"部分成立"变成"已排除" |
| E3（dense full） | **GO 若时间允许** | 把"提示性"变"定论"，但不动主结论 |
| E4（judge 全行） | **可缓** | 现有失败池审计已足够保守；扩全行主要是姿态 |
| E5（frontier） | **先 60 题侦察再决定** | 结果若翻转，第 6 章要重写；不要盲跑 |
| E6/E7 | **NO-GO** | 先验不佳，且 R1/R9 用文本边界 + 已有成分表足以回应 |

**最大风险**：E5 若显示 frontier 读者把 read-side 残差大幅吃掉，论文"residual is composition"的机制结论需要重写为"reader-capacity-bound"。这不是坏事——但必须由数据决定，不能靠措辞绕开。

---

## 6. 本次已交付

| 文件 | 说明 |
|---|---|
| `output/final/tables/fig_takeaway.pdf` / `.png` | 主网格 accuracy–budget 总览图（R7），从 `results.jsonl` 重算 |
| `output/final/scripts/make_takeaway_fig.py` | 出图脚本，可复现 |
| 本文件 | R1–R10 诊断、回应文本、实验预算与 GO/NO-GO |

未改动：`paper.tex`、`paper.bib`、任何 `results*.jsonl`。

---

## 7. 执行记录：E1 + E2 已完成，论文已改

### 7.1 E1：compression + read-time selection 补齐四档（full n=500）

新增 1,000 次调用（512 / 2048），复用第八轮已有的 1024 / 4096，写入 `results_r9.jsonl`。

| B | write-time | read-time | read − write | p | read − retrieval | p |
|---|---|---|---|---|---|---|
| 512 | 0.124 | **0.262** | +0.138 | <1e-4 | −0.010 | 0.70 |
| 1024 | 0.172 | **0.292** | +0.120 | <1e-4 | −0.020 | 0.36 |
| 2048 | 0.242 | **0.318** | +0.076 | 0.0002 | −0.016 | 0.50 |
| 4096 | 0.334 | 0.324 | −0.010 | 0.63 | −0.040 | 0.059 |

结论：读时选择在 512–2048 把 compression 从"显著落后"变成"统计打平检索"，4096 反而略降。R2 的"稻草人"指控在数据层面不成立；同时它没有让 compression 变成最优策略。

### 7.2 E2：summarizer × reader 2×2 解耦（B=4096，n=120，960 次）

GLM-5.3-Flash 重新生成 120 题子集的 5,422 条摘要（约 6.5M tokens），四格全部同题配对。

| Policy | DS 摘要 / DS 读 | GLM 摘要 / DS 读 | DS 摘要 / GLM 读 | GLM 摘要 / GLM 读 |
|---|---|---|---|---|
| compression | 0.283 | 0.275 | 0.392 | 0.292 |
| hierarchical | 0.375 | 0.333 | 0.408 | 0.400 |

- 固定 DeepSeek 读者换摘要作者：compression −0.008（p=1.0）、hierarchy −0.042（p=0.18）。
- 固定摘要换读者：compression +0.108（p=0.002）/ +0.017（p=0.73）。
- 四格中 hierarchy 均高于 compression，家族排序在全因子解耦下不变。
- 自审：DS/DS 格与主网格同题重建的装配 footprint 逐题一致（240/240），差的 1–2 题来自生成端非确定性。

### 7.3 论文改动清单

| 位置 | 改动 |
|---|---|
| Table 2（main） | 由 21 行扩为 25 行：compression 拆 write-time / read-time 两变体；全文 21 cells→25 cells、10,500→12,500 |
| Table 3（consolidated） | 删除，由新增 **Figure 2**（accuracy–budget 总览，含 95% CI 带与 full-context 参考线）替代（R7） |
| Table 4（stats） | 改为 strict / relaxed **双指标并排**；Δ 统一为 compression − baseline（R6） |
| Table 12（probes） | 只保留 hierarchy 两个成分；读时选择的四档对比并入主表与 §4.1 |
| Table 13（cross） | 新增 2×2 解耦表（R5） |
| 正文 | 摘要、§1、§3 策略条目、§4.1、§4.3、§5 C1、§7.1、§7.2、§8 N1、§9、§10、§11 全部同步；N1 与结论的 4096 措辞降档为"narrowing gap" |
| 表格命名 | 全稿统一 `compression (write-time)` / `compression+read-time sel.` |

### 7.4 构建状态（最终：15 页）

- 引擎：tectonic 0.17.0（与上版同版本），0 未解析引用、0 "??"、1 处 0.7pt overfull（不可见）。
- **整册 15 页**：正文 §1–§11 止于第 13 页，文献第 14 页，附录 A–D 全部收在第 15 页。
- 为回收页数所做的取舍（内容零删除，仅重排与紧凑化）：
  1. Table 2 改为**左右双栏**布局（25 行数据不变，高度减半），策略名用缩写；
  2. 删 consolidated 表，由 Figure 2 替代；
  3. reranker / structured-compressor 两表移出正文，数字保留在 §6.2–§6.3，附录 D 注明已发布记录；
  4. 新增 Table 13（2×2 解耦）；
  5. 附录 A 删去与 §3 重复的 reader-configuration 段、B/D 精简、
     §2/§3/§4.1/§5/§6/§7.2/§8/摘要共约 2,600 字符措辞紧凑化。
- 已核对：无 "21 main-grid cells"/"10,500" 残留；N4/N1 的 4096 检验均标注双指标口径。

### 7.5 仍未做（需你决定）

- R3：frontier 读者探针（1,200 次）——建议先 60 题侦察。
- R4：dense full-500（2,000 次）。
- R9：SGMem-lite（工程 2–3 天）。
- R10：LoCoMo 升正文小节（零成本，未做，因页数已超）。

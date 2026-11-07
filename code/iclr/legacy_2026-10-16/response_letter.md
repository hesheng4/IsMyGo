# 审稿意见逐点回复信（Response Letter）

论文：*When Does Memory Compression Pay Off? A Budget-Controlled Study of Memory Policies for LLM Agents on LongMemEval*
修改版：`iclr/iclr_paper.tex`（重新编译 15 页，无编译错误、无未解析引用）

**修改原则说明**：本轮修改全部为零新实验成本的写作修订 + 两项基于已发布逐题记录的确定性重算（匹配对分析与整合表 CI 计算，无任何新 API 调用，脚本 `experiments/longmemeval/_matched_pair.py`、`experiments/longmemeval/_consolidated_table.py` 可复现）。所有新增数字均逐字溯源 `output/longmemeval/results.jsonl`。

---

## 意见 9（清晰度）：论文数字密集，建议整合表（策略×预算×含 CI 的 EMrel）

**采纳。新增整合表 Table~\ref{tab:consol}（Results §5.1，紧跟主表）。**

- **形态**：5 个受限策略 × 4 档预算的矩阵，每格 "relaxed EM [95% CI]"，full-context 参考行（完成子集 n=36）以跨列单值呈现——审稿人建议的"一个表读全关键比较"。
- **生成纪律**：由 `experiments/longmemeval/_consolidated_table.py` 从 `results.jsonl` 确定性生成（与 `analyze.py` 同口径：分层 120 题过滤 + 完成子集判定），每格 percentile bootstrap 95% CI（10,000 重采样、seed 42，与 `score.py` 同随机数协议），零新调用。
- **导读改写**：§5.1 首段改为"主表报告 EM/token-F1；整合表给出含 CI 的头条比较；其余表按题型/延迟/配对统计拆解"，降低数字密度感知。
- **页数控制**：为守住评审窗口（前 15 页），参考文献条目间距收紧至 2pt、附录 Summarizer prompts 段压缩（完整 prompt 随代码发布），最终仍为 15 页，无内容损失。

## 意见 10（清晰度）：PDF 提取符号不一致（分词器名称等）与轻微错别字

**采纳，已系统性排查并修正。**

- **分词器名称（6 处）**：原稿混用数学下标形式 `cl100k$_\text{base}$`（PDF 提取为 "cl100kbase"）与裸写 "cl100k"，提取形态不一致。全篇统一为等宽字面形式 `\texttt{cl100k\_base}`，修正后 PDF 文本提取全篇形态一致。
- **拼写混用（1 处）**：Abstract "favourable"（英式）与 §6.3 "favorable"（美式）混用，统一为美式拼写。
- **系统性扫描**：对全文执行重复词 / 常见错拼 / 英美拼写混用 / 名称变体扫描；其余命中均为 LaTeX 数学符号与策略名切分误报（如 "retrieval+recency"、"Mem0/Mem0g"、`$\rightarrow$` 连排）；"LongMemEval"（无 -S 后缀）3 处均指代基准族（标题、Related Work、协议对比），属正确用法，保留。
- **修正后全文提取验证**：cl100k 形态全篇一致、favourable 计 0、无未解析引用标记。

---

## 意见 1（技术限制）：全上下文平价基于 n=36 小完成子集，存在选择偏差风险；更强证据需要匹配对分析

**采纳。已补匹配对分析，平价结论在匹配后成立，且偏差本身已被量化披露。**

我们完全同意该风险是真实的——完成子集由提供方故障（而非我们）决定。修订版做了两件事：

1. **量化选择偏差**（新增于 C2）：完成子集 n=36 偏向 multi-session（14/32 完成 vs 7/32 temporal-reasoning、4/19 knowledge-update），且在策略无关的难度代理下更容易（逐题 retrieval@4096 relaxed EM：完成 0.361 vs 失败 0.274）——我们主动指出完成子集均值"可能美化 full-context"。
2. **匹配对分析**（新增于 C2 + Abstract）：将全部策略限定到**相同的 36 题**上重算：retrieval 四档预算 0.306–0.361，retrieval+recency 0.278–0.361，hierarchical 0.222–0.333，对照 full-context 0.333。**平价在匹配后保持**，且此结论可由发布的逐题记录确定性复现。

同时诚实声明边界（Limitations (1) 新增）：该子集欠代表 temporal/knowledge-update 题型，平价在这两类上属于外推而非测量。GLM-4.7-Flash 独立 60 题子集上 full-context 0.250 的复现（原文已有）作为旁证保留。

> 新增正文（Abstract）："A matched-question analysis on the same completed subset preserves this parity ($0.333$ vs.\ $0.28$--$0.36$)."
> 新增正文（C2）："A **matched-question analysis** therefore restricts every policy to the same 36 questions: retrieval scores $0.306$--$0.361$ across the four budgets, … Parity survives matching…"

## 意见 2（技术限制）：压缩策略最新优先填充、不通过摘要检索，可能低于取用-摘要设计

**采纳，已显式声明设计边界。**

Method 压缩策略条目新增："Digests are *never* selected by question relevance: the compressed tier is a pure take-newest store. This isolates `compression-as-storage' but deliberately omits the take-then-summarize retrieval designs…; that read path is untested here."

Limitations (3) 同步收窄结论范围：本研究的负结果**只约束单遍、取最新的摘要压缩**，不约束按相关性选取摘要的取用-摘要式设计。分层策略的检索层也只索引逐字轮次、从不检索摘要（见 Method 分层条目新增说明）。

## 意见 3（技术限制）：更高级压缩器（ProMem、Mem0/Mem0g、HiGMem/MAGMA）未在匹配预算下评估

**采纳，已按"明确声明未评估 + 收窄结论边界"处理（本轮不新增实验）。**

- Related Work 定位段新增一段，点名三类机制并声明未在匹配预算下评估：迭代验证式抽取（ProMem）、图/知识结构化记忆（Mem0/Mem0g）、正交语义/时间/因果/实体多图索引（MAGMA）。
- Limitations (3) 将原"event-level or learned compressors remain to be tested"扩为具名清单，并明确 null 的适用范围："the null bounds single-pass take-newest summarization only, not take-then-summarize designs."
- 新增三条**已核验**的参考文献（arXiv 号逐一查证）：Chhikara et al. 2025 (arXiv:2504.19413)、Yang et al. 2026 (arXiv:2601.04463)、Jiang et al. 2026 (arXiv:2601.03236)。HiGMem 原文已引用。

## 意见 4（实验空白）：500 题中仅用 120 题

**部分采纳（写作层面），不做全量重跑。**

Method 的 Power 段（原文已有）已给出功效计算：头条负结果 exact McNemar p≤0.005，CI 半宽 0.07–0.13，最小可检测效应 ≈0.10 EM，并说明 500 题可将 CI 收窄 √(500/120)≈2×。Limitations (2) 新增：题型级子组（如 temporal n=32）为**描述性对比而非功效充分的比较**，500 题全量运行为直接升级路径且 harness 已发布支持。

## 意见 5（方法论）：EM/EMrel 偏好逐字重叠，头条数字属词汇性

**采纳，已将 judge 修正后的头条数字升格入选型准则。**

论文原有的 full-sweep semantic judge（§6.4：1,746 失败单元 + 210 正确对照、零假阴性、翻转率 34.0%）已证明排序不变。本轮在 Practical selection guideline 新增第 (vii) 条，把 judge 口径下的 4096 头条数字直接给出：retrieval ≈0.53、hierarchical ≈0.54、compression ≈0.33——"levels shift with the metric, the selection ordering does not"。这样读者无需换算即可与 LLM-as-judge 社区实践对表。主指标仍保持确定性 EM/EMrel（避免 judge 环形性），此设计立场不变。

## 意见 6（方法论）：摘要离线写入成本被摊销，频繁重写情景会改变成本-收益结论

**已有覆盖（上一轮修订），本轮维持并确认。**

Limitations (9) 原文已完整讨论：写入侧成本（5,728 会话、14.0M tokens、≈2.6 h）一次性冻结入缓存、按 ≥21 个复用单元元格摊销（≈0.67M tokens/cell），并明确"write-heavy regime 下压缩层成本画像恶化、eviction/纯检索设计相对更优"的定性结论。本轮未改动该条。

## 意见 7（清晰度）：被测代理与特定先前系统的映射需更清晰

**采纳，已新增显式映射。**

Related Work "Protocol differences" 段新增一句完整映射：sliding window ↔ eviction；retrieval ↔ MemGPT/RAG 式外部记忆；compression ↔ MemoryBank/SeCom 式触发摘要；hierarchical ↔ SGMem/MLMF 多索引架构。并声明："Each proxy reproduces the *mechanism* (what is kept and how the budget is split), not the full system (no learned retrieval policies, graph indices, or memory-update loops of the original systems)."

## 意见 8（清晰度）：分层策略作为多索引架构代理，需明确其局限（事件级锚定、多跳选择）

**采纳，已双处声明。**

- Method 分层策略条目新增："The proxy shares their budget split but not their retrieval logic: it has no event-level anchoring [HiGMem], no temporal/causal indices or multi-hop graph traversal [MAGMA], and its retrieval tier indexes verbatim turns only, never digests."
- Limitations (4) 新增：消融只变预算切分、不变检索逻辑，事件级锚定/时间因果索引/多跳选择"outside what a 25/50/25 tier split can express"。

---

## 修改位置速查

| 意见 | 修改章节 | 类型 |
|---|---|---|
| 1 选择偏差/匹配对 | Abstract；Analysis C2；Limitations (1) | 写作 + 确定性重算（无新调用） |
| 2 摘要不检索 | Method 压缩条目；Limitations (3) | 写作 |
| 3 高级压缩器 | Related Work；Limitations (3)；bib +3 条 | 写作 |
| 4 样本量/功效 | Limitations (2)（Power 段原有） | 写作 |
| 5 词汇性指标 | Guideline (vii)（§6.4 judge 诊断原有） | 写作 |
| 6 写入成本摊销 | Limitations (9)（原有，未改） | 已覆盖 |
| 7 代理映射 | Related Work | 写作 |
| 8 分层代理局限 | Method 分层条目；Limitations (4) | 写作 |
| 9 整合表 | Results §5.1 新增 tab:consol；_consolidated_table.py；\bibsep 收紧 + 附录压缩控页 | 写作 + 确定性重算（无新调用） |
| 10 符号/错别字 | 6 处分词器名统一为 \texttt{cl100k\_base}；abstract 拼写修正 | 写作 |

---

# 第二轮（修订版残余意见，8 条）

**本轮修改原则**：与首轮一致，零新 API 调用。新增一项确定性重算（写入/读取 break-even，脚本 `experiments/longmemeval/_breakeven.py`，输入仅 `results.jsonl`）；三条新引用（ReFind / Infini Memory / BudgetMem）均经外部核验。总页数维持 15 页（评审窗口内）。

## R2-1（技术限制）：压缩策略省略"先取后汇总"的读取时间选择

**已在首轮覆盖，本轮维持。** Method 压缩策略条目明确 "Digests are never selected by question relevance"，Limitations (3) 明确 null 只约束单遍 take-newest 摘要。审稿人将其列为残余弱点而非新缺陷；无需进一步修改，边界声明已到位。

## R2-2（技术限制）：中等规模回答者，阅读侧上限或随更强读者改变

**已在正文原有覆盖，本轮维持。** Limitations (1) 首句即为 answerer-scale 声明；§6.5 reranker 探针结论限定 "at this answerer scale"；跨读者复现（GLM-4.7-Flash）已提供两个规模的数据点。

## R2-3（实验空白）：120/500 题型层次结论力度不足，应进一步限定

**采纳，本轮加强限定语。** §6.3 temporal 段落新增明确措辞："this is a descriptive contrast, not a powered comparison (minimum detectable effect ~0.10 EM, Method), so it should be read as hypothesis-generating for future type-stratified runs rather than as evidence of a temporal advantage"。与 Limitations (2) 的功效声明形成正文-局限呼应。

## R2-4（实验空白）：n=36 完成子集残余选择偏差

**已在首轮最大化覆盖，残余属披露而非可修复项。** 匹配对分析（同 36 题重算，parity 保持）+ 选择偏差量化（难度代理 0.361 vs 0.274、题型构成偏斜）均已入正文 C2 与 Limitations (1)。消除残余偏差的唯一途径是补跑 84 个失败调用（~12.5M tokens），属新实验，不在本轮零成本范围；论文以"parity in temporal/update regimes is extrapolation, not measurement"诚实划界。

## R2-5（实验空白）：写入+读取端到端成本曲线未全面探讨

**采纳，本轮新增定量 break-even 分析（Limitations (9)）。**

从已发布逐题记录确定性重算（`_breakeven.py`，零新调用）：
- 完成态 full-context 读取 104,121 prompt tokens/题 vs 压缩@4096 4,197 tokens/题；
- **break-even ≈ 140 次查询**：一次性写入成本（14.0M tokens）需约 140 次"替代 full-context"的读取才能摊销；
- **对检索永不回本**：压缩读取（4,197）比 BM25（3,986）略贵，每次查询对写入投资零偿还；
- 写入频繁场景使边界进一步不利于压缩；完整 write+read 成本曲线仍留作未探索项。

这把原先的纯定性讨论升级为可复现数字，且第二点（对检索不摊销）是本轮发现的新的诚实负结果。

## R2-6（实验空白）：单发回收，多轮/读取时笔记基线缺失

**采纳定位与理由，不新增实验。** Limitations (3) 新增：多轮读取时基线（ReFind 式迭代代理搜索、Infini Memory 式工具调用文档读取）缺失的**原则性理由**——它们在多次调用中消耗答题侧 token，在固定硬预算下实例化需要重新定义预算记账口径（逐调用求和 vs 单次装配上下文），留作未来工作。

## R2-7（清晰度）：关键结论需交叉引用多个部分重建

**采纳，本轮补齐整合表指针。** Analysis C1（证据句尾）与 C3（结论句尾）新增 "consolidated in Table 5 (tab:consol)" 指针。读者现在可从单表获得全部策略×预算×CI 数值，C1/C3 的机制叙述直接锚定到该表，无需在 stats/bytype/latency 表间拼图。

## R2-8（缺失比较）：ReFind/Infini Memory/BudgetMem 未作为匹配基线实例化

**采纳引用与定位（三条均经核验），不实例化。**

- Related Work 定位段新增：ReFind（arXiv:2608.12888）代理控制迭代搜索、Infini Memory（arXiv:2606.10677）主题文档工具调用读取、BudgetMem（ICML 2026, arXiv:2602.06025）查询感知预算档位路由；
- **加分引用**：ReFind 的结论（可控搜索媲美结构化记忆）与我方 §6.5 读取侧天花板诊断同向，正文明确指出这一一致性；
- Limitations (4) 的 learned allocation 现在具名引用 BudgetMem；
- 不实例化为匹配基线的理由同 R2-6（预算记账口径）。

## 第二轮修改位置速查

| 意见 | 修改章节 | 类型 |
|---|---|---|
| R2-1 take-then-summarize | 已覆盖（Method + Lim(3)） | 维持 |
| R2-2 中等规模读者 | 已覆盖（Lim(1)） | 维持 |
| R2-3 temporal 限定 | §6.3 新增 descriptive-contrast 措辞 | 写作 |
| R2-4 n=36 残余偏差 | 已覆盖（C2 + Lim(1)），残余划界 | 维持 |
| R2-5 写入+读取成本 | Lim(9) 新增 break-even 定量；_breakeven.py | 确定性重算（无新调用） |
| R2-6 多轮/笔记基线 | Lim(3) 新增原则性理由 | 写作 |
| R2-7 交叉引用 | C1/C3 新增 tab:consol 指针 | 写作 |
| R2-8 ReFind/Infini/BudgetMem | Related Work 定位段；Lim(3)(4)；bib +3 条 | 写作 |

## 第二轮验证记录

- 编译：pdflatex ×3 + bibtex 全部 exit 0；输出 15 页（评审窗口内完整覆盖）；无 undefined citation/reference；无 "??" 标记。
- Break-even：`python experiments/longmemeval/_breakeven.py`，输入仅 `results.jsonl`，输出 104,121 / 4,197 / 3,986 / ~140 四个数，与正文逐字一致。
- 页数控制：本轮新增内容曾使论文达 16 页，通过零内容损失的排版手段（12 处表格 \small→\footnotesize、浮动体/标题间距收紧、图宽 0.485→0.47、附录 \small、caption 压缩）压回 15 页；唯一文字删减为附录模板段落的措辞紧凑化（完整模板仍逐字保留于系统 prompt 引文）。
- 新增引用三条均经外部核验：ReFind arXiv:2608.12888（USTC）、Infini Memory arXiv:2606.10677（清华/Infinigence）、BudgetMem arXiv:2602.06025（ICML 2026），无占位符。
- 数字回归检查：0.333/0.308/0.005/0.83/0.95/34%/0.148/0.117 全部在位，无既有结论被本轮修改影响。

---

# 第二轮补充修订（口径系统收紧 + 低成本统计补跑）

**修订原则**（对应作者指示）：对论文文本与结论口径做系统收紧；仅补跑已有代码支持的低成本实验（复用 `score.py` 统计工具与 `results.jsonl`，零新 API 调用）；**不声称完成 ReFind / Infini Memory / BudgetMem 的公平复现**——它们分别需要重新定义多轮读取的预算记账口径或训练/门控协议，本轮仅作设计语境定位。

## A. 低成本补跑：匹配对分析升级为完整配对统计（强化 R2-4）

`experiments/longmemeval/_matched_pair.py` 升级为 v2（复用 `score.py` 的 `paired_bootstrap` + `mcnemar_exact`，输入仅 `results.jsonl`）：

- **平价主张获得正式统计支撑**：在相同的 n=36 完成子集上，full-context vs 每档预算的最强受限策略，配对差 |Δ|≤0.028 relaxed EM、**全部 bootstrap 95% CI 含零、全部精确 McNemar p=1.0**（512: vs retrieval +0.028 [-0.056,+0.111]；1024: vs retrieval+recency −0.028 [-0.139,+0.083]；2048: vs retrieval 0.000 [-0.111,+0.111]；4096: vs retrieval −0.028 [-0.111,+0.056]）。
- **诚实边界同步写入**：n=36 的 CI 宽（±0.11），这是"统计上不可区分"的证据而非精确相等的证明（正文原句）。
- **负结果被 sharpen**：同一匹配子集上 full-context 显著胜过 compression @512–2048（p≤0.022）与 sliding window 全档（p≤0.039）——与主网格的 standalone-compression 负结论同向且更尖锐。
- 摘要同步补一句 "statistically indistinguishable at every budget"。

## B. 结论口径系统收紧（审计发现两处原断言不成立，已修正）

| 位置 | 原表述 | 问题 | 收紧后 |
|---|---|---|---|
| 摘要 (iii)、引言 (4) | "strongest of the **six primary policies** at 4096" | full-context 无 4096 档位（非受限）且完成子集 0.333 > 0.308，字面不成立 | "numerically the strongest of the **five budget-constrained** policies at 4096" |
| 引言 (4)、C3 标题与正文 | "the **only** primary policy whose accuracy rises monotonically" / "alone keeps rising" | **滑动窗口（0.042→0.092）与压缩（0.058→0.158）同样单调上升**，原断言为假 | C3 改题 "keep scaling where the single-mechanism leaders saturate"，正文明确 sliding/compression 也单调上升但全程低于检索 ≥0.14 relaxed EM，"among the top contenders, only hierarchical keeps rising" |
| 摘要 (ii) | "fails standalone **regardless of format**" | 仅测过 3 种格式，"regardless" 过度泛化 | "fails standalone **in every tested format**" |
| 摘要 (iii)、引言 (4)、指南 (iii) | "is the strongest" | hierarchical 0.308 vs retrieval 0.300 差异不显著 | 前缀 "**numerically**" |
| 指南 (ii)(iii)、结论 | "strongest **primary** policy" | "primary" 语义含混（是否含参照组） | "strongest **budget-constrained** policy" |
| Limitations (9) | "compression **never** amortizes" | 修辞过强 | "compression **cannot** amortize"（同一数学事实：读取 4,197 > BM25 3,986，写入投资零偿还） |

## C. ReFind / Infini Memory / BudgetMem：显式不声称复现

Related Work 定位段结尾新增声明（逐字）："These are cited to map the design space only: none is instantiated under our protocol, and no comparison with them is claimed (Limitations)." 三条引用保持定位性质；不实例化为基线的原则性理由（多轮读取需重定义预算记账口径、BudgetMem 需训练门控协议）已在 Limitations (3)(4)。**本文未复现、也未声称复现这三个系统。**

## D. 页数控制

本轮净增约 16 行正文后曾达 16 页，通过以下手段收复 15 页（评审窗口）：C2/C3/RW/引言新增文本的紧凑化改写、附录 Reader/Summarizer 段与 user-turn 模板段压缩（系统 prompt 引文逐字保留）、图宽 0.47→0.45、参考文献 \scriptsize。全部为措辞与排版层面，无结论或数据变更。

## E. 验证记录（补充轮）

- 编译 exit 0，15 页，无 undefined citation/reference，无 "??"。
- 新表述 8 项全部在 PDF 提取文本中确认；旧表述 6 项（six primary / the only primary policy / regardless of format / never amortizes / alone keeps rising / strongest primary）全部清零。
- 匹配对统计数字（|Δ|≤0.028、p=1.0、p≤0.022、p≤0.039）与正文逐字一致，由 `_matched_pair.py` v2 确定性复现。
- 15 个既有头条数字（0.333/0.308/0.005/0.83/0.95/34%/0.148/0.117/104,121/4,197/3,986/140/0.150/0.225/0.275）无回归。

---

# 终轮校准（全文论证审计驱动的 P2–P3 修正）

对成稿执行审稿人视角的全文论证审计（一句话论证检验、主张-证据地图、拒稿维度扫描）后，实施三处残余校准，全程保持 15 页：

1. **P2 摘要加粗句校准**："Constrained memory wins on robustness and cost" → "wins on **cost and observed robustness**"。鲁棒性主张的证据基数是单次观测到的限流风暴（正文原措辞 "during the observed rate-limit event" 正确，但加粗句读作一般性结论），加 "observed" 对齐证据强度。
2. **P3 引言贡献 (2) 去重**：与摘要近乎逐字重复的统计括号（0.3333 vs. 0.30–0.35）改为指向 Abstract 的紧凑表述（"merely matches the constrained range in relaxed EM (Abstract)"），省 2 行。
3. **P3 "primary grid" 首现定义**：§6.1 首次出现处补 "(the six-policy main comparison, distinct from the sensitivity variants)"，消除与 "primary baseline/metric"（另一义项，共 3 处、语境自明）的潜在歧义。

审计结论备档：一句话论证成立且全文服务之；六条核心主张（平价/格式负结果/混合扩展/读取侧天花板/C1 位移机制/摊销边界）全部 supported 且边界校准正确；上一轮修复的假断言无复发。摘要数字密度（~340 词 12+ 数）为 ICLR 可接受范围，未动。

终轮验证：15 页、3 项新措辞在位、2 项旧措辞清零、20 个头条数字无回归、附录完整收于第 15 页、无未解析引用。

---

## 验证记录（首轮）

- 编译：pdflatex ×3 + bibtex 全部 exit 0；输出 15 页（评审窗口取前 15 页，完整覆盖）；无 undefined citation/reference；PDF 提取验证无 "??" 未解析标记。
- 匹配对分析：`python experiments/longmemeval/_matched_pair.py`，输入仅 `results.jsonl`（分层 120 题过滤与 `analyze.py::_fc_completed` 同口径），输出全部新增数字。
- 整合表：`python experiments/longmemeval/_consolidated_table.py`，输入仅 `results.jsonl`，输出 `tables/consolidated_emrel.tex`；表内数值与正文各处引用交叉一致（hierarchical@4096 = 0.308 [0.23, 0.39]、full-context 完成子集 = 0.333 [0.19, 0.50]）；表位于编译后 PDF 第 6 页。
- 符号一致性：编译后 PDF 全文提取，cl100k 形态全篇一致；favourable 计 0、favorable 计 2。
- 新增引用三条均经外部核验（arXiv:2504.19413 / 2601.04463 / 2601.03236），无占位符。

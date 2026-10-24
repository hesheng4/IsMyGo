# openJiuwen框架贡献说明文档

> 满足赛题"必须修改 openJiuwen（JiuwenSwarm）源码"红线的改动清单。
> 基线：develop 分支（openJiuwen/jiuwenswarm），上游 commit `develop@3fea8d16`（2026-10-10）；
> 在该 commit 上实测 `git apply --check` 与 `git apply` 均通过。上游源码可自行克隆验证；
> 全部改动以补丁形式随本包交付于 `code/framework-contribution/paper_guard.patch`
> （10 文件 / +843 行 / −0，git-apply 兼容）；`patch/new-files/` 与 `patch/modified-files/` 为逐文件参考副本。

## 1. 代码优化点

1. **团队公共 Rail 装配优化**：扩展 `member_rails.py` / `registry.py` / `config_specs.py` 装配链路，新增 `PAPER_GUARD` Rail 挂载点（完全遵循框架既有 `MODEL_ANOMALY_DETECTION` 模式：配置解析 → Input model → provider → registry 再导出），两条科研护栏 Rail 可由配置一键挂载到团队全部成员。
2. **工具装配名单扩展**：`registry.py` / `config_specs.py` 新增 `DEEPSEARCH_TOOLS` / `MEMORY_EVAL_TOOLS` 再导出与 `_research_tool_params` 参数构建器，科研工具按 `research_tools.enabled` 自门控装配，缺依赖时静默跳过。
3. **工具调用容错增强**：DeepSearch 与评测 harness 均以子进程隔离运行（超时可配 900s / 7200s），崩溃/超时不污染框架主进程；未配置或执行失败时返回结构化降级建议（改用 web_search），不抛异常。
4. **配置模板拓展**：`resources/config.yaml` 新增 `paper_guard:` 与 `research_tools:` 两个顶层段，`enabled: false` 出厂默认关闭，零影响现有部署。

## 2. 功能拓展点

- 新增 `HallucinationCheckRail` 幻觉校验护栏：提取 Agent 输出中的量化断言（百分比/F1/Acc/loss 等）与基准 `results.json` 逐值比对，未溯源数值注入告警；写文件动作前二次拦截校验
- 新增 `AcademicFormatRail` 学术格式护栏：论文章节完整性检查（abstract/introduction/method/experiment/conclusion/references，中英兼容），缺章节注入补齐指令；`[N]` 引用与参考文献对齐检查
- 新增 `DeepSearchToolkit` 可溯源文献检索工具：子进程调用 openJiuwen-DeepSearch，报告落盘 `deepsearch_results/` 并返回摘录+路径，与幻觉校验 Rail 形成「检索可溯源 → 断言可比对」闭环
- 新增 `MemoryEvalToolkit` 记忆评测执行工具：LongMemEval harness 子进程执行（smoke/full、断点续跑），Token 消耗与运行时长进框架日志，资源报告可从框架侧追溯
- 新增 `research_tools.py` 双 tool provider（`@harness_element(kind=ElementKind.TOOL)`），配置门控装配

## 3. PR提交信息

- PR名称：feat(rails+tools): add paper_guard rails and research_tools for automated research paper generation
- PR链接：**已发起** —— <https://gitcode.com/openJiuwen/jiuwenswarm/merge_requests/5577>
  （jiuwenswarm 仓库 MR !5577，state=`open`、`merged_at` 为空；
  head `feat/paper-guard-rails@794bd1ee`，base `develop@8315c183`，创建 2026-08-28；
  配对 GitHub PR：`openJiuwen-ai/jiuwenswarm#4185`）
- 参赛交付包侧同一套改动：`openJiuwen/agent-store!563`
  （<https://gitcode.com/openJiuwen/agent-store/merge_requests/563>）
  —— 与 !5577 **分属两个仓库**（!5577 = jiuwenswarm 框架仓；!563 = agent-store 交付包仓），
  并非同一 MR 的两个编号
- 提交分支（fork 源）：`gcw_sZpSWqT4/jiuwenswarm` 的 `feat/paper-guard-rails`
- **AtomGit fork 仓库（提交源，2026-10-16 联网核对）**：
  - jiuwenswarm fork：<https://atomgit.com/gcw_sZpSWqT4/jiuwenswarm>
    （可达；`develop` 分支；**Pull Requests 计数 0/0/0/0（Open/Closed/Merged/All 均 No Data）**
    —— 即 MR 不在 atomgit fork 上发起，atomgit 侧仅为提交源 fork/镜像）
  - agent-store fork（参赛交付包仓）：<https://atomgit.com/gcw_sZpSWqT4/agent-store>
    （可达；`main` 分支；Apache-2.0；314 commits；简介 = 本项目「基于 openJiuwen（JiuwenSwarm）
    构建的科研论文自动生成智能体…15 页 ICLR 格式论文」）
  - 结论：用户提供的两个 atomgit 链接是 **fork 源仓库**（承载 `feat/paper-guard-rails` 分支与
    交付包代码），**正式 MR 在 gitcode 上游仓发起**（!5577 / !563，见上）；atomgit fork 侧 0 PR
    属预期（fork 不自动携带上游 MR）。
- PR状态（2026-10-12 复核，来源：gitcode API v5
   `/repos/openJiuwen/jiuwenswarm/pulls/5577`，HTTP 200）：`state=open`、`merged_at=""`、
   `mergeable=true`、`draft=false`；labels = `sig/jiuwenswarm`、`openJiuwen-cla/yes`、
   `AI-Reviewed`、`ci-failed`；assignee `douran`；`updated_at=2026-08-28T20:53:01+08:00`
   （注：2026-10-16 本轮仅联网核对了 atomgit fork 侧可达性与 PR 计数；gitcode MR 状态沿用
   2026-10-12 复核结果，未在本轮重新拉取 gitcode API）
- 合并状态：**已发起、未合并**（`state=open`；带 `ci-failed` 标签，合并待 CI 通过）
- 基线口径说明：MR 发起时 base 为 `develop@8315c183`（2026-08-28）；随包交付的
  `paper_guard.patch` 另在本地克隆 HEAD `develop@3fea8d16`（2026-10-10）上实测
  `git apply --check` 通过（见文首基线说明），两者为同一 develop 分支的不同时点

## 4. 兼容性说明

本次改动完全兼容 openJiuwen（JiuwenSwarm）现有版本：两条 Rail 与两个工具集均由独立配置段门控，`enabled: false` 出厂默认关闭，无破坏性变更；装配链路完全遵循框架既有 `MODEL_ANOMALY_DETECTION` / `cron_tools` 模式，无新概念，可直接用于科研、写作类 Agent 开发。

---

# 附录：补丁明细（评审证据）

## 补丁一：paper_guard 科研护栏 Rails

### 改动动机

科研论文自动生成场景的两个高频失败模式：

1. **数据幻觉**：写作 Agent 编造实验数字（如"准确率 92.3%"），论文被
   Stanford Agentic Reviewer 判定"结论无依据"直接低分。
2. **结构缺失**：论文缺章节（方法/实验/参考文献），学术规范不过关。

新增框架级 `paper_guard` 能力：两条配置驱动的 Rail，挂载到每个团队成员。

### 新增文件（3）

| 文件 | 内容 |
|------|------|
| `jiuwenswarm/agents/harness/common/rails/paper_guard/__init__.py` | 包导出 |
| `jiuwenswarm/agents/harness/common/rails/paper_guard/hallucination_check_rail.py` | `HallucinationCheckRail`（priority=80）：`after_model_call` 提取输出中的量化断言（百分比/F1/Acc/loss 等），与基准 `results.json` 比对，未溯源数值注入告警；`before_tool_call` 拦截写文件动作二次校验 |
| `jiuwenswarm/agents/harness/common/rails/paper_guard/academic_format_rail.py` | `AcademicFormatRail`（priority=70）：`after_model_call` 检查论文类输出的章节完整性（abstract/introduction/method/experiment/conclusion/references，中英兼容），缺章节注入补齐指令；引用 `[N]` 与参考文献对齐检查 |

### 修改文件（4）

| 文件 | 位置 | 改动 |
|------|------|------|
| `jiuwenswarm/agents/swarm/providers/member_rails.py` | 常量区 + `_build_plugin_rails` 后 | 新增 `PAPER_GUARD = "swarm.paper_guard"`、`PaperGuardInput`、`@harness_element(kind=ElementKind.RAIL)` provider `_build_paper_guard_rails`（读 `paper_guard.enabled` 门控，构建两条 Rail 返回列表），并加入 `__all__` |
| `jiuwenswarm/agents/swarm/registry.py` | 常量再导出区 + `__all__` | 新增 `PAPER_GUARD = _member_rails.PAPER_GUARD` 再导出 |
| `jiuwenswarm/agents/swarm/config_specs.py` | `_COMMON_RAIL_NAMES` + `_RAIL_PARAM_BUILDERS` | 团队公共 Rail 装配名单插入 `registry.PAPER_GUARD`（位于 MODEL_ANOMALY_DETECTION 之后）；新增 `_paper_guard_params` 参数构建器映射 |
| `jiuwenswarm/resources/config.yaml` | `execution_guard` 与 `channels` 之间 | 新增顶层 `paper_guard:` 段：`enabled: false`（默认关闭，零影响默认行为）、可选 `results_path` |

### 设计决策

- **配置门控默认关闭**：`enabled: false` 出厂，不影响任何现有部署。
- **挂载点选 team 公共名单**：科研流水线跑在 team 模式（SwarmFlow 由
  Leader 调 `SwarmflowTool` 执行），member 级 Rail 即可覆盖全部写作成员。
- **告警不阻断**：Rail 只注入 note + 日志，不抛异常——防止校验器本身
  的 bug 卡死论文流水线；阻断决策留给下游 Agent 读 note 后自行修正。
- **防御式 ctx 访问**：`AgentCallbackContext` 具体字段随 openjiuwen
  版本演进，全部 `getattr` 链 + try/except 包裹。
- **遵循现有模式**：完全仿照 `MODEL_ANOMALY_DETECTION`（配置解析 →
  Input model → provider → registry 再导出 → config 模板）的最小闭环，
  无新概念，评审成本低。

### 验证清单（合并前）

- [ ] `pytest tests/agents/swarm/test_swarm_assembly.py`（装配名单变更回归）
- [ ] 新增 `tests/agents/swarm/test_paper_guard_rails.py`：
      - enabled=false → provider 返回 None
      - enabled=true → 返回 2 条 Rail 实例
      - 幻觉校验：构造含 `92.3%` 的输出 + 不含该值的 results.json → note 注入
      - 学术格式：缺 method 章节的论文草稿 → note 注入
- [ ] `config.yaml` 模板 YAML 语法校验

## 补丁二：research_tools 科研工具集（2026-08-22）

> 对应三仓架构 (JiuwenSwarm + DeepSearch + Agent Studio) 中的框架级科研执行能力。
> 与补丁一 (paper_guard) 共同构成参赛框架改动的完整 PR 内容。

### 改动动机

FARS 式科研流水线 (Ideation → Planning → Experiment → Writing) 在 JiuwenSwarm
中落地时缺少两个框架级执行入口：

1. **文献检索不可溯源**：写作/构思成员只能用通用 web_search，返回内容无落盘、
   无段级出处，论文引用核查 (hallucination_check rail) 无从比对。
2. **实验执行游离于框架外**：记忆策略评测 (LongMemEval harness) 若由外部脚本
   裸跑，则 Token 消耗、运行时长不进框架日志，资源报告不可从框架侧追溯。

新增 `research_tools` 能力：两个配置门控的 tool provider。

### 新增文件（3）

| 文件 | 内容 |
|------|------|
| `jiuwenswarm/agents/harness/common/tools/deepsearch_tools.py` | `DeepSearchToolkit`：`deepsearch_literature(query, top_k)` 工具，子进程调用 openJiuwen-DeepSearch CLI (https://atomgit.com/openJiuwen/deepsearch)，报告落盘 `deepsearch_results/ds_<ts>.md` 并返回摘录 + 路径；未配置/失败返回结构化降级建议（改用 web_search），不抛异常 |
| `jiuwenswarm/agents/harness/common/tools/memory_eval_tools.py` | `MemoryEvalToolkit`：`run_memory_eval(mode, policies, n_questions, budgets)` 工具，子进程执行 LongMemEval 记忆策略评测 harness，返回 EM/F1 汇总、逐题结果路径与 token 用量聚合；支持 smoke/full 与断点续跑 |
| `jiuwenswarm/agents/swarm/providers/research_tools.py` | `DEEPSEARCH_TOOLS = "swarm.deepsearch_tools"`、`MEMORY_EVAL_TOOLS = "swarm.memory_eval_tools"` 两个 `@harness_element(kind=ElementKind.TOOL)` provider；`research_tools.enabled` 门控（默认 false），缺 repo_dir/harness_dir 时静默跳过返回空列表 |

### 修改文件（4）

| 文件 | 位置 | 改动 |
|------|------|------|
| `jiuwenswarm/agents/swarm/registry.py` | import 块 + 常量再导出区 + `__all__` | 新增 `research_tools as _research_tools` 导入、`DEEPSEARCH_TOOLS` / `MEMORY_EVAL_TOOLS` 再导出并加入 `__all__` |
| `jiuwenswarm/agents/swarm/config_specs.py` | `_COMMON_TOOL_NAMES` 尾部、`_CODE_TOOL_NAMES` 尾部 | 两个工具名插入装配名单（默认关闭，由 provider 自门控） |
| `jiuwenswarm/agents/swarm/config_specs.py` | `_TOOL_PARAM_BUILDERS` | 新增 `_research_tool_params`：读 `research_tools` 段烘焙 `enabled` / `deepsearch_config` / `memory_eval_config` |
| `jiuwenswarm/resources/config.yaml` | `paper_guard:` 与 `channels:` 之间 | 新增顶层 `research_tools:` 段：`enabled: false` 出厂，deepsearch.repo_dir / memory_eval.harness_dir 等注释示例 |

### 设计决策

- **沿用既有模式**：toolkit (`ToolCard` + `LocalFunction` + `get_tools()`) 放
  `harness/common/tools/`，provider (`@harness_element`) 放 `swarm/providers/`，
  与 `send_file_to_user` / `cron_tools` 完全同构，评审成本低。
- **子进程隔离**：DeepSearch 与评测 harness 均以子进程运行，崩溃/超时不污染
  框架主进程；超时可配 (默认 900s / 7200s)。
- **可追溯性**：memory_eval 工具返回 `results.jsonl` 路径与 token 聚合，
  deepsearch 工具返回报告落盘路径——配合 paper_guard 的幻觉校验 Rail 形成
  「检索可溯源 → 断言可比对」闭环。
- **默认关闭零影响**：`enabled: false` 出厂；装配名单新增项由 provider 自门控，
  不改变任何现有部署行为。

### 验证清单（合并前）

- [x] provider 导入链与门控逻辑（enabled=false → 空列表；enabled=true 缺配置 → 跳过；全配置 → 构建出 Tool 实例）
- [ ] `pytest tests/agents/swarm/`（装配名单变更回归）
- [ ] 新增 `tests/agents/swarm/test_research_tools.py`：
      - deepsearch_literature 未配置 repo_dir → ok=false + 降级建议
      - run_memory_eval smoke 模式端到端（mock subprocess）
- [ ] `config.yaml` 模板 YAML 语法校验

## 复现（PR 准备）

```bash
git clone https://gitcode.com/openJiuwen/jiuwenswarm.git   # MR 平台；atomgit.com/openJiuwen/jiuwenswarm.git 为同源镜像
# Windows 下须指定 openssl 后端：git -c http.sslBackend=openssl clone ...
cd jiuwenswarm && git checkout develop
git checkout -b feat/paper-guard-rails
git apply <包根>/code/framework-contribution/paper_guard.patch   # 10 文件完整补丁（develop@3fea8d16 apply-check 通过）
git add -A && git commit -m "feat(rails+tools): add paper_guard rails and research_tools for automated research paper generation"
git push -u <你的 fork 远程> feat/paper-guard-rails
# 在 gitcode 向 openJiuwen/jiuwenswarm 发起 MR（base=develop）；已发起的 MR 见第 3 节（!5577）
```

> **交付状态（2026-10-12 复核）**：框架侧 MR !5577 已发起（链接与状态见第 3 节），
> 与交付包侧 agent-store!563 分属两个仓库；本包 `paper_guard.patch` 为基于上游
> develop@3fea8d16 的 10 文件完整补丁（+843 / −0）；
> `patch/new-files/` 与 `patch/modified-files/` 为逐文件参考副本（源自本地已应用
> 目录 `../jiuwenswarm-develop/`，其 4 个修改文件含上游快照漂移，重建请以
> `paper_guard.patch` 为准）。如需从分支重新生成完整补丁：
> `git diff develop feat/paper-guard-rails > paper_guard.patch`。

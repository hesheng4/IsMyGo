# openJiuwen 模块调用说明

> 本文档从 architecture.md 的「openJiuwen 模块调用清单」小节独立拆出，
> 便于评审快速定位框架依赖；完整上下文见 architecture.md。

## 0. agent-core (openjiuwen) 基础类复用清单（system/ 基建+编排层双后端）

| agent-core 基础类/函数 | 复用位置 | 调用方式 |
|---|---|---|
| `openjiuwen.core.memory.lite.internal.hash_text`（SHA256[:16]） | `system/backends.get_hash_fn()` ← `context_cache._sha` | 内容哈希缓存键；与内置 `hashlib` 同款实现逐位一致，双后端可互换 |
| `openjiuwen.core.session.checkpointer.build_key / build_key_with_namespace` | `system/backends.build_key` | 缓存/会话键构造 |
| `openjiuwen.core.common.task_manager`（`get_task_manager` / `print_task_tree`） | `system/backends.TaskTracker` ← `scheduler.ResearchScheduler` | 任务生命周期记录与任务树可观测性（调度语义不变） |
| `openjiuwen.core.workflow`（`Workflow` / `WorkflowCard` / `Start` / `End` / `WorkflowComponent`） | `system/orchestrator._build_agentcore_workflow` | 四模块流水线组件图（构思→规划→实验→[门控]→写作） |
| `openjiuwen.core.workflow.components.condition.FuncCondition` + `flow.branch_router.BranchRouter/Branch` | `system/contracts.build_gate_router` | 门控决策（PASS/REVISE/REJECT）状态路由，替代手搓状态机分支 |
| `openjiuwen.core.session.workflow.create_workflow_session` | `system/orchestrator` | 工作流会话构造 |
| `Workflow.invoke`（max_retries/timeout、输入 JSON Schema 校验） | `system/orchestrator`（经 `backends.run_sync` 独立事件环） | 组件图执行；`WorkflowCard.input_params` 为 JSON Schema（type/properties），节点 `inputs_schema` 为 `${}` 取值模板 |

**双后端语义**（`system/backends.py`，`PAPER_LAB_BACKEND=auto|agentcore|stdlib`）：
- agentcore 可用（pip 包或 `OPENJIUWEEN_SRC` 源码树注入）→ 上表类全部走 openjiuwen 实现
- 不可用/导入失败/被测试桩污染 → **优雅回退 stdlib 同款实现并告警**，零 LLM 路径保持纯标准库可运行
- openjiuwen 的 async API（Workflow/Checkpointer/TaskManager）经 `run_sync` 在独立事件环同步桥接；异常静默回退，绝不影响产物
- 等价性保证：`code/tests/test_backend_equivalence.py`（hash 逐位一致、双后端产物 accuracy 语义等价、Workflow 组件图端到端）

## 1. 框架模块调用清单

| 框架模块 | 调用方式 | 位置 |
|----------|----------|------|
| `openjiuwen.agent_teams.harness.manifest`（harness_element / ElementKind） | provider 注册（`@harness_element(kind=ElementKind.RAIL/TOOL)`） | `code/experiments/../deploy` 框架补丁：`swarm/providers/research_tools.py`、`swarm/providers/member_rails.py`（patch/ 目录） |
| `openjiuwen.core.foundation.tool`（ToolCard / LocalFunction / Tool） | 工具实例构造 | 框架补丁 `harness/common/tools/{deepsearch,memory_eval}_tools.py` |
| SwarmBuildContext / config_specs 装配名单 | 团队装配挂接（`_COMMON_RAIL_NAMES` / `_COMMON_TOOL_NAMES` 插入） | 框架补丁 `swarm/config_specs.py` |
| LLM 端点（`models.defaults[0]`） | 答题与摘要（OpenAI SDK，base_url 读 `~/.jiuwenswarm/config/config.yaml`） | `code/experiments/longmemeval/llm.py` |

## 2. 调用关系图（文字版）

```
JiuwenSwarm 引擎（团队模式）
 ├─ SwarmFlow 流水线 (code/deploy/research_pipeline_v5.py)
 │   ├─ hypothesis-review / planning / writing / proofread 诸阶段
 │   └─ 每阶段成员输出过 member Rails:
 │       ├─ HallucinationCheckRail (priority=80, paper_guard)
 │       └─ AcademicFormatRail   (priority=70, paper_guard)
 ├─ research_tools provider (patch/new-files/swarm/providers/research_tools.py)
 │   ├─ DeepSearchToolkit  → 子进程调 openJiuwen-DeepSearch CLI，报告落盘可溯源
 │   └─ MemoryEvalToolkit  → 子进程跑 LongMemEval harness，token 用量进框架日志
 └─ LLM 端点（models.defaults[0]） ← code/experiments/longmemeval/*.py（主实验全部 LLM 调用）
```

## 3. 挂载与门控

- 两条 Rail 与两个 Toolkit 均由 `resources/config.yaml` 新增段门控
  （`paper_guard.enabled` / `research_tools.enabled`），默认 `false`，
  不改变任何现有部署行为（见 framework_contribution.md）。
- 引擎内端到端验证：`code/deploy/engine_e2e_check.py`（MockBackend，
  不耗 token）；Rail 裁决演示：`code/deploy/rail_verdict.py`。

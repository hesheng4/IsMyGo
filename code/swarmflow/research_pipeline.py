"""
方案 A · SwarmFlow 科研论文流水线骨架
========================================
基于 JiuwenSwarm SwarmFlow 的 6 阶段端到端科研论文自动生成。

脚本契约（JiuwenSwarm SwarmFlow 官方规范）：
  - 顶层必须定义  META = {...}
  - 必须定义      async def run(args)
  - 算子通过      `from swarmflow import ...` 引入（运行时映射到
                  openjiuwen/agent_teams/workflow/engine/facade.py）

运行方式（详见 run_guide.md §4）：
  1. 安装并启动 JiuwenSwarm：    jiuwenswarm-init && jiuwenswarm-start
  2. 团队模式开启 SwarmFlow：    /swarmflow on --budget 500000
  3. 让 Leader 执行本脚本：      swarmflow(script_path=".../research_pipeline.py", args={"topic": "..."})
  也可将本脚本放入团队工作空间 swarmflow/ 目录后由 Leader 直接调用。
"""

# ---------------------------------------------------------------------------
# META：脚本元数据（字段以 openjiuwen 引擎 schema 为准，官方文档确认
# name/description/phases 等基础字段；如需扩展字段请参考引擎定义）
# ---------------------------------------------------------------------------
META = {
    "name": "research-paper-pipeline",
    "description": (
        "End-to-end automated research paper generation pipeline: "
        "ideation -> planning -> experiment -> writing -> proofread."
    ),
    # 与 FARS 四模块对齐的 Phase：构思 / 规划 / 实验 / 写作
    "phases": ["ideation", "planning", "experiment", "writing"],
}

import os

from swarmflow import (  # noqa: E402  (META 需在 import 之前定义)
    agent,
    phase,
    log,
    compact,
    parallel,
    budget,
)

# 阶段常量（与 META["phases"] 对齐）
PHASE_IDEATION = "ideation"
PHASE_PLANNING = "planning"
PHASE_EXPERIMENT = "experiment"
PHASE_WRITING = "writing"

# 模型标识：默认与 config.yaml 主模型（glm-4.7-flash，即 logs/run.json 的 model）一致。
# 强弱分工时用 PAPER_LAB_STRONG_MODEL / PAPER_LAB_FAST_MODEL 覆盖，
# 覆盖后的模型名须在 config.yaml 的 models 段登记。
MODEL_STRONG = os.environ.get("PAPER_LAB_STRONG_MODEL", "glm-4.7-flash")
MODEL_FAST = os.environ.get("PAPER_LAB_FAST_MODEL", "glm-4.7-flash")


# ---------------------------------------------------------------------------
# 阶段 1 · Ideation（构思）：文献调研 + 研究假设生成
# ---------------------------------------------------------------------------
async def _ideation(topic: str) -> str:
    phase(PHASE_IDEATION)
    hypothesis = await agent(
        (
            "你是科研构思研究员。围绕研究主题「{topic}」检索最新文献，"
            "梳理现有研究的痛点，提出 1 个可验证、有创新点的研究假设，"
            "并给出支撑该假设的文献依据。\n"
            "请用 JSON 返回："
            "{{\"hypothesis\": \"研究假设\", \"rationale\": \"思路依据\", "
            "\"references\": [\"关键文献1\", \"关键文献2\"]}}"
        ).format(topic=topic),
        label="ideation",
        phase=PHASE_IDEATION,
        options={"model": MODEL_STRONG},
    )
    log(f"Ideation 完成，假设：{hypothesis}")
    return hypothesis


# ---------------------------------------------------------------------------
# 阶段 2 · 假设筛选（FARS 弱项之一：复杂假设筛选能力弱）
# ---------------------------------------------------------------------------
async def _hypothesis_review(hypothesis: str) -> str:
    phase(PHASE_PLANNING)
    review = await agent(
        (
            "你是科研评审员。评估以下研究假设的可行性，重点判断："
            "① 是否可在有限算力下验证；② 是否有明确基线可对比；"
            "③ 结论是否可被实验结果支撑。\n"
            "研究假设：{hypothesis}\n"
            "请返回 JSON："
            "{{\"passed\": true或false, \"reason\": \"评审理由\", \"risks\": [\"风险1\"]}}"
        ).format(hypothesis=hypothesis),
        label="hypothesis-review",
        phase=PHASE_PLANNING,
        options={"model": MODEL_FAST},
    )
    log(f"假设评审完成：{review}")
    return review


# ---------------------------------------------------------------------------
# 阶段 3 · Planning（规划）：实验方案与基线设计
# ---------------------------------------------------------------------------
async def _planning(hypothesis: str, review: str) -> str:
    phase(PHASE_PLANNING)
    plan = await agent(
        (
            "你是实验设计专家。基于研究假设设计可复现的实验方案，明确："
            "① 数据集与预处理；② 基线方法与主实验方法；③ 评估指标；"
            "④ 消融实验；⑤ 运行步骤与预期资源消耗。\n"
            "研究假设：{hypothesis}\n评审意见：{review}\n"
            "请用 JSON 返回实验方案。"
        ).format(hypothesis=hypothesis, review=review),
        label="planning",
        phase=PHASE_PLANNING,
        options={"model": MODEL_STRONG},
    )
    log(f"实验方案完成：{plan}")
    return plan


# ---------------------------------------------------------------------------
# 阶段 4 · Experiment（实验）：沙箱真跑 + 复现审计（禁止编造数字）
# 数据流：sandbox_runner → output/results.json（唯一事实基准）→ 后续阶段引用
# ---------------------------------------------------------------------------
RESULTS_REL = "output/results.json"  # 相对 paper-lab 根


async def _experiment(plan: str) -> list:
    phase(PHASE_EXPERIMENT)

    async def _run_real_experiment():
        return await agent(
            "你是实验执行员，执行 LongMemEval 记忆策略真实评测。"
            "禁止编造或推算任何数字，全部数据必须来自真实执行。按顺序尝试：\n"
            "路径一（框架工具，若已注册）: 调用 run_memory_eval 工具 "
            "(mode='full')，其由 JiuwenSwarm research_tools 提供，"
            "返回逐题流水路径与 token 聚合。\n"
            "路径二（回退，框架工具不可用时）: 在 experiments/longmemeval/ 运行 "
            "python run.py --full （断点续跑，缓存自动跳过）。\n"
            "完成后运行 python analyze.py 生成论文表格，读取 "
            "output/longmemeval/tables/ 下的 main.tex 与 stats.json 原样返回。\n"
            "实验方案：\n" + plan,
            label="experiment-run",
            phase=PHASE_EXPERIMENT,
            options={"model": MODEL_FAST, "timeout": 600},
        )

    async def _audit_reproducibility():
        return await agent(
            "你是实验审计员。在 paper-lab 根目录运行: "
            "python -m pytest tests/ -q\n"
            "报告通过/失败数与失败详情。这些测试覆盖确定性、results.json "
            "schema、机制回归与幻觉校验真数据集成。",
            label="experiment-audit",
            phase=PHASE_EXPERIMENT,
            options={"model": MODEL_FAST, "timeout": 600},
        )

    # fork-join：真跑与审计并发，失败项返回 None 不影响其余
    results = await parallel([_run_real_experiment(), _audit_reproducibility()])
    settled = compact(results)
    log(f"实验完成，收集到 {len(settled)} 组结果。")
    return settled


# ---------------------------------------------------------------------------
# 阶段 5 · Writing（写作）：按学术规范撰写论文
# ---------------------------------------------------------------------------
async def _writing(hypothesis: str, plan: str, results: list) -> str:
    phase(PHASE_WRITING)
    draft = await agent(
        (
            "你是学术论文写作专家。严格依据实验数据撰写科研论文，"
            "包含：摘要、引言、相关方法、实验设置、实验结果、分析讨论、"
            "结论、参考文献。\n"
            "【篇幅硬性要求】成稿编译为 PDF 后必须正好 15 页（pdflatex 实测）。"
            "写作时按 15 页体量规划各章深度；初稿完成后须编译核对页数，"
            "不足 15 页则加深结果分析与方法阐述（严禁编造数据凑页数），"
            "超过 15 页则压缩次要段落，迭代直至恰好 15 页。\n"
            "【数据纪律】论文中出现的每一个数值都必须逐字来自下方实验结果"
            "（即 paper-lab/" + RESULTS_REL + " 的真实落盘数据），"
            "禁止编造、修改精度或推算新数值；results 中没有的指标不得出现。\n"
            "研究假设：{hypothesis}\n实验方案：{plan}\n实验结果（唯一数据源）：{results}"
        ).format(hypothesis=hypothesis, plan=plan, results=results),
        label="writing",
        phase=PHASE_WRITING,
        options={"model": MODEL_STRONG},
    )
    log("论文初稿完成。")
    return draft


# ---------------------------------------------------------------------------
# 阶段 6 · Proofread（校验）：结构完整性与幻觉检查
# ---------------------------------------------------------------------------
async def _proofread(draft: str) -> str:
    phase(PHASE_WRITING)
    final = await agent(
        (
            "你是论文审稿校对员。检查论文：① 章节结构是否完整（摘要/引言/"
            "方法/实验/结论/参考文献）；② 页数硬性门禁：编译 PDF 核对页数"
            "必须正好 15 页，不达标则按数据纪律修正篇幅后重新编译，"
            "页数不对不得定稿；③ 逐个数值核对：论文中每个量化数字"
            "是否都能在 paper-lab/" + RESULTS_REL + "（真实实验落盘文件）中"
            "找到，找不到的必须删除或改正；④ 有无无依据的断言（幻觉）；"
            "⑤ 引用是否规范。如有问题请修正并输出最终版论文。\n"
            "论文草稿：{draft}"
        ).format(draft=draft),
        label="proofread",
        phase=PHASE_WRITING,
        options={"model": MODEL_STRONG},
    )
    log("论文定稿完成。")
    return final


# ---------------------------------------------------------------------------
# 主入口：必须定义的 async def run(args)
# ---------------------------------------------------------------------------
async def run(args):
    # 引擎可能以 JSON 字符串而非 dict 传入 args，此时先解析为 dict。
    # 而直接 .get() 的脚本毫秒级失败且无任何 log 事件）
    if isinstance(args, str):
        import json as _json

        try:
            args = _json.loads(args)
        except (ValueError, TypeError):
            args = None
    if not isinstance(args, dict):
        args = {}
    topic = args.get("topic", "一个聚焦的 AI 研究方向")
    log(f"科研流水线启动，主题：{topic}")

    # 1. 构思
    hypothesis = await _ideation(topic)

    # 2. 假设筛选
    review = await _hypothesis_review(hypothesis)

    # 3. 规划
    plan = await _planning(hypothesis, review)

    # 4. 实验（并行）
    results = await _experiment(plan)

    # 5. 写作
    draft = await _writing(hypothesis, plan, results)

    # 6. 校对定稿
    final = await _proofread(draft)

    spent = budget.spent()
    log(f"论文成稿完成。累计 Token：{spent}")

    return {
        "paper": final,
        "hypothesis": hypothesis,
        "plan": plan,
        "results": results,
        "token_spent": spent,
    }
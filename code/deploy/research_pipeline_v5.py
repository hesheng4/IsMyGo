"""
方案 A · SwarmFlow 科研论文流水线（部署版）
============================================

七阶段串行流水线：ideation → hypothesis-review → planning → experiment-run
→ experiment-audit → writing → proofread。每一步由引擎的 agent() 调用一个
worker，阶段产物以**文件路径**在阶段之间传递（不靠模型转述）。

设计要点
--------
1. 跨阶段用文件传递
   worker 的 cwd 在团队工作区，与 paper-lab 无相对关系，因此所有 prompt 都
   给出 paper-lab 的绝对路径，并显式禁止在工作区里找。
   writing 把全文写入 paper-lab/paper/draft_v5.md，proofread 读该文件后
   定稿写 paper-lab/paper/final_v5.md。

2. 引擎侧真值注入
   不信任 worker 的文字转述：
     - _experiment 结束后直接读 results.json，JSON 校验通过即以文件内容
       覆盖 run_outcome；
     - _writing 结束后直接读 draft_v5.md，存在则以文件全文传给 proofread，
       保证 writing→proofread 数据不断流。

3. W1 模块覆盖硬约束
   hypothesis-review 返回的 module_gaps 会被解析出来，作为硬约束注入
   planning 与 writing 的 prompt，确保未做实验的模块不进入论文主张。

4. 工具纪律
   experiment-run 被要求必须用终端/shell 执行实验；执行失败时降级为原样
   返回已落盘的 results.json，而不是纯文字描述失败。

5. 限流规避
   worker 统一走 GLM-4-Flash（其配额独立于 GLM-4.7-Flash）；启动延迟与
   阶段间隔用于压低请求密度。可用 args {"pacing": false} 关闭节流。

环境变量
--------
  PAPER_LAB               paper-lab 根目录（默认相对本脚本定位）
  PAPER_LAB_PY            子进程解释器（默认当前解释器）
  PAPER_LAB_WORKER_MODEL  worker 模型名（默认 GLM-4-Flash）
  PIPELINE_STARTUP_DELAY_S / PIPELINE_PHASE_GAP_S   节流参数（秒）
"""

META = {
    "name": "research-paper-pipeline",
    "description": (
        "End-to-end automated research paper generation pipeline: "
        "ideation -> planning -> experiment -> writing -> proofread."
    ),
    "phases": ["ideation", "planning", "experiment", "writing"],
}

from swarmflow import (  # noqa: E402  (META 需在 import 之前定义)
    agent,
    phase,
    log,
    compact,
    budget,
)

import sys  # noqa: E402  (v7: 默认解释器用 sys.executable)
import time  # noqa: E402  (真值注入的节奏控制用)
import os  # noqa: E402  (路径/模型/节奏可经环境变量覆盖)
import json as _json  # noqa: E402  (解析 hypothesis-review 返回的 JSON)
import re as _re  # noqa: E402  (抽取文本里内嵌的 JSON 对象)

# 子进程要用的解释器：默认取当前进程的解释器，可用 PAPER_LAB_PY 指定另一个。

PY = os.environ.get("PAPER_LAB_PY") or sys.executable

# paper-lab 根目录。worker 的 cwd 在团队工作区，与 paper-lab 无相对关系，
# 因此这里解析为绝对路径；可用 PAPER_LAB 环境变量覆盖。
# 默认值相对本脚本定位（parents[1] = deploy/ 的上一级），两种布局下都成立：
#   IsMyGo/code/deploy/               -> IsMyGo/code/   （交付包布局）
#   agent/workspace/paper-lab/deploy/ -> paper-lab/     （引擎工作区布局）
# 两种布局下该目录都含 output/results.json、experiments/、system/。



PAPER_LAB = os.environ.get(
    "PAPER_LAB",
    str(__import__("pathlib").Path(__file__).resolve().parents[1]),
)
RESULTS_ABS = PAPER_LAB + "/output/results.json"
DRAFT_PATH = PAPER_LAB + "/paper/draft_v5.md"
FINAL_PATH = PAPER_LAB + "/paper/final_v5.md"

# worker 默认与项目主模型一致（glm-4.7-flash）；如需隔离配额避开限流，
# 模型名可用 PAPER_LAB_WORKER_MODEL 覆盖（如 GLM-4-Flash）。

WORKER_MODEL = os.environ.get("PAPER_LAB_WORKER_MODEL", "glm-4.7-flash")
WOPT = {"model": WORKER_MODEL}
WOPT_SLOW = {"model": WORKER_MODEL, "timeout": 600}

# 限流规避节奏：启动延迟与阶段间隔，可经环境变量微调（单位秒）
STARTUP_DELAY_S = int(os.environ.get("PIPELINE_STARTUP_DELAY_S", "90"))
PHASE_GAP_S = int(os.environ.get("PIPELINE_PHASE_GAP_S", "30"))

PHASE_IDEATION = "ideation"
PHASE_PLANNING = "planning"
PHASE_EXPERIMENT = "experiment"
PHASE_WRITING = "writing"

FALLBACK_HYPOTHESIS = (
    "针对长程流式任务，分层记忆引擎（近期滑窗 + 检索增强 + 摘要压缩）"
    "在受限上下文预算下优于单一全文检索基线，且预算越小优势越显著。"
)


# W1 模块覆盖硬约束。
# hypothesis-review 返回的 module_gaps 解析后，作为规划/写作阶段的硬约束注入，
# 确保未实验模块不得进入论文主张；闭环不依赖模型自觉。
def _parse_review(review_text):
    """从 hypothesis-review 的 JSON 输出抽取 passed/module_gaps/baseline_fairness。

    解析失败或字段缺失时返回安全默认（默认放行、无缺口），不中断流水线。
    """
    if not review_text or not isinstance(review_text, str):
        return {"passed": True, "module_gaps": [], "baseline_fairness": ""}
    try:
        data = _json.loads(review_text)
    except Exception:
        # 模型可能用 ```json 包裹或前后夹带文本：抽取首个 {...} 对象
        m = _re.search(r"\{.*\}", review_text, _re.DOTALL)
        if not m:
            return {"passed": True, "module_gaps": [], "baseline_fairness": ""}
        try:
            data = _json.loads(m.group(0))
        except Exception:
            return {"passed": True, "module_gaps": [], "baseline_fairness": ""}
    if not isinstance(data, dict):
        return {"passed": True, "module_gaps": [], "baseline_fairness": ""}
    gaps = data.get("module_gaps") or []
    if isinstance(gaps, str):
        gaps = [gaps]
    return {
        "passed": bool(data.get("passed", True)),
        "module_gaps": [str(g) for g in gaps if g],
        "baseline_fairness": str(data.get("baseline_fairness", "")),
    }


def _w1_guard_text(module_gaps) -> str:
    """针对未实验模块生成规划/写作硬约束文本；无缺口时返回空串。"""
    if not module_gaps:
        return ""
    gaps = "、".join(str(g) for g in module_gaps)
    return (
        "\n【W1 模块覆盖硬约束】假设中以下方法模块经评审确认无对应实验支撑："
        + gaps
        + "。必须在「模块→实验策略映射表」中显式声明缺失，且禁止在标题/摘要/"
        "方法/结论的任何优越性主张中出现这些模块作为已验证贡献；相关表述须"
        "降级为「未来工作」。"
    )


async def _ideation(topic: str) -> str:
    phase(PHASE_IDEATION)
    hypothesis = await agent(
        (
            "你是科研构思研究员。围绕研究主题「{topic}」检索最新文献，"
            "梳理现有研究的痛点，提出 1 个可验证、有创新点的研究假设，"
            "并给出支撑该假设的文献依据。\n"
            "【主张可实证纪律】假设中提及的每一个方法模块（如滑窗/检索/"
            "压缩等）都必须可独立实验验证——不得提出实验矩阵无法覆盖的"
            "模块性主张；假设的优越性比较对象只能是同等预算约束下的策略，"
            "无预算上界的基线只能作为 oracle 上界参照，不得作为被超越对象。\n"
            "【相关工作定位】references 必须给出至少 5 个近邻系统"
            "（系统名 + 年份/出处 + 一句话差异），并指出本研究相对它们的缺口。\n"
            "请用 JSON 返回："
            "{{\"hypothesis\": \"研究假设\", \"rationale\": \"思路依据\", "
            "\"modules\": [\"模块1\", \"模块2\"], "
            "\"references\": [\"系统名(年份)——差异一句话\", ...]}}"
        ).format(topic=topic),
        label="ideation",
        phase=PHASE_IDEATION,
        options=WOPT,
    )
    if not hypothesis or hypothesis == "None":
        log("WARN: ideation 返回空，启用兜底研究假设")
        hypothesis = FALLBACK_HYPOTHESIS
    log(f"Ideation 完成，假设：{hypothesis}")
    return hypothesis


async def _hypothesis_review(hypothesis: str) -> str:
    phase(PHASE_PLANNING)
    review = await agent(
        (
            "你是科研评审员。评估以下研究假设的可行性，重点判断："
            "① 是否可在有限算力下验证；② 是否有明确基线可对比；"
            "③ 结论是否可实验结果支撑；"
            "④ 模块覆盖——假设中提及的每个方法模块是否都有对应的"
            "实验策略或消融实验（若某模块无法实验，主张必须降级或删除）；"
            "⑤ 基线公平性——优越性比较是否仅在同等预算约束的策略间进行，"
            "无界基线（如全量上下文）是否仅作 oracle 上界参照。\n"
            "研究假设：{hypothesis}\n"
            "请返回 JSON："
            "{{\"passed\": true或false, \"reason\": \"评审理由\", "
            "\"risks\": [\"风险1\"], "
            "\"module_gaps\": [\"无实验支撑的模块\"], "
            "\"baseline_fairness\": \"公平或指出问题\"}}"
        ).format(hypothesis=hypothesis),
        label="hypothesis-review",
        phase=PHASE_PLANNING,
        options=WOPT,
    )
    if not review or review == "None":
        log("WARN: hypothesis-review 返回空，按有条件通过处理")
        review = '{"passed": true, "reason": "评审agent异常，默认放行（有既有实验基线可对比）", "risks": ["评审缺失"]}'
    log(f"假设评审完成：{review}")
    return review


async def _planning(hypothesis: str, review: str, module_gaps=None) -> str:
    phase(PHASE_PLANNING)
    if not plan_input_ok(hypothesis, review):
        log("WARN: planning 输入含空值，已替换为兜底值")
    w1 = _w1_guard_text(module_gaps)
    prompt = (
        "你是实验设计专家。基于研究假设设计可复现的实验方案，明确："
        "① 数据集与预处理；② 基线方法与主实验方法；③ 评估指标；"
        "④ 消融实验；⑤ 运行步骤与预期资源消耗。\n"
        "【模块映射表·必须】给出「方法模块→实验策略/消融」映射表，"
        "假设中提及的每个模块都必须映射到一条具体实验；无法映射的模块"
        "必须在方案中显式声明并从主张中移除。\n"
        "【基线公平性·必须】无预算上界的基线（如全量上下文）必须单列并"
        "标注为 oracle 上界参照，不参与受限策略间的优越性比较；所有受限"
        "策略在相同预算档位下对比。\n"
        "【统计方案·必须】多种子（≥3）聚合，报告均值 + 标准差 + 95% "
        "置信区间；对关键对比给出区间是否重叠的判读。\n"
        "【指标口径·必须】每个指标给出测量口径定义（如延迟是进程内内存"
        "查询耗时还是端到端含模型推理耗时）。\n"
        "研究假设：{hypothesis}\n评审意见：{review}\n"
        "请用 JSON 返回实验方案。"
    ).format(
        hypothesis=hypothesis or FALLBACK_HYPOTHESIS,
        review=review or "默认放行",
    )
    if w1:
        prompt += w1
    plan = await agent(prompt, label="planning", phase=PHASE_PLANNING, options=WOPT)
    log(f"实验方案完成：{plan}")
    return plan


def plan_input_ok(hypothesis: str, review: str) -> bool:
    return bool(hypothesis) and bool(review)


async def _experiment(plan: str) -> list:
    phase(PHASE_EXPERIMENT)

    # 给出 paper-lab 绝对路径：worker cwd 在团队工作区，禁止在工作区里找
    # 工具纪律：必须用终端执行，禁止改用浏览器等其他工具路径
    run_outcome = await agent(
        "你是实验执行员，按 experiment-runner skill 执行真实实验。"
        "禁止编造或推算任何数字，全部数据必须来自真实执行。\n"
        "【工具纪律】必须使用终端/命令行（shell/execute_command）工具执行下述命令；"
        "禁止使用浏览器工具打开或执行任何脚本；禁止仅凭想象报告结果。\n"
        "【路径纪律】项目根目录在 " + PAPER_LAB + "（绝对路径）。"
        "你当前的工作目录是团队工作区，里面没有 paper-lab，"
        "禁止在当前目录查找，所有命令必须用绝对路径或先切换到上述根目录。\n"
        "1. 用终端执行（整条复制）: cd \"" + PAPER_LAB + "\" && \"" + PY
        + "\" scripts/sandbox_runner.py --script experiments/run_all.py "
        "--timeout 300 --arg=--out --arg=output/results.json\n"
        "2. 确认 stdout 末行 JSON 的 ok=true。\n"
        "3. 用文件读取工具读取 " + RESULTS_ABS + " 全文。\n"
        "4. 你的最终回复必须原样包含该 JSON 全文（不得改写、省略或总结数值）。\n"
        "【降级路径】若步骤 1 执行失败：不要编造失败结论，改为直接读取 "
        + RESULTS_ABS + "（此前已通过 pytest 验证的真实落盘数据），"
        "将其 JSON 全文原样返回，并在开头注明「沙箱重跑失败，以下为已落盘验证数据」。"
        "任何情况下最终回复都必须包含真实 JSON 数据，禁止只回复文字描述。\n"
        "实验方案：\n" + (plan or "按 memory_bench 既有矩阵执行：3 seeds × budgets"),
        label="experiment-run",
        phase=PHASE_EXPERIMENT,
        options=WOPT_SLOW,
    )

    # 引擎侧真值注入：直接读落盘文件校验，不以 worker 的转述为准
    import json as _json
    import os as _os

    try:
        with open(RESULTS_ABS, encoding="utf-8") as _f:
            _data = _f.read()
        _json.loads(_data)
        _mtime = time.strftime("%H:%M:%S", time.localtime(_os.path.getmtime(RESULTS_ABS)))
        run_outcome = _data
        log(f"真值注入：results.json 校验通过（{len(_data)}B, mtime={_mtime}），"
            "下游以文件内容为准")
    except Exception as _exc:
        log(f"WARN: 引擎侧读取 results.json 失败（{_exc}），保留 worker 返回值")

    audit_outcome = await agent(
        "你是实验审计员，负责运行测试套件验证实验资产。\n"
        "【路径纪律】项目根目录在 " + PAPER_LAB + "（绝对路径）。"
        "你当前的工作目录是团队工作区，里面没有 paper-lab，"
        "禁止在当前目录查找或要求用户创建；必须直接用绝对路径操作。\n"
        "运行: cd " + PAPER_LAB + " && " + PY + " -m pytest tests/ -q\n"
        "报告通过/失败数与失败详情。这些测试覆盖确定性、results.json "
        "schema、机制回归与幻觉校验真数据集成。",
        label="experiment-audit",
        phase=PHASE_EXPERIMENT,
        options=WOPT_SLOW,
    )

    results = compact([run_outcome, audit_outcome])
    log(f"实验完成，收集到 {len(results)} 组结果（experiment-run={'有' if run_outcome else '空'}，"
        f"experiment-audit={'有' if audit_outcome else '空'}）。")
    return results


async def _writing(hypothesis: str, plan: str, results: list, module_gaps=None) -> str:
    phase(PHASE_WRITING)
    w1 = _w1_guard_text(module_gaps)
    draft = await agent(
        (
            "你是学术论文写作专家。严格依据实验数据撰写科研论文，"
            "包含：摘要、引言、相关工作、方法、实验设置、实验结果、"
            "分析讨论、结论、参考文献。\n"
            "【篇幅硬性要求】成稿编译为 PDF 后必须正好 15 页（pdflatex 实测）。"
            "写作时按 15 页体量规划各章深度；不足则加深结果分析与方法阐述"
            "（严禁编造数据凑页数），超过则压缩次要段落，迭代直至恰好 15 页。\n"
            "【工具纪律】使用文件写入工具（write_file）落盘，禁止用浏览器。\n"
            "【数据纪律】论文中出现的每一个数值都必须逐字来自真实落盘的 "
            + RESULTS_ABS + "（唯一数据源）。若下方实验结果文本不含 JSON 数值"
            "（例如只有文字描述），必须先用文件读取工具读取该文件全文再写作。"
            "禁止编造、修改精度或推算新数值；results 中没有的指标不得出现；"
            "禁止使用由原始值换算的相对百分比，提升一律用原始值对比表述。\n"
            "【报告规范·必须逐条满足】\n"
            "a. 统计置信：所有准确率表格必须附 accuracy_std 与 accuracy_ci95"
            "（results.json 已含），关键对比须判读置信区间是否重叠；\n"
            "b. 指标口径：每个指标首次出现时声明测量口径——延迟必须写明是"
            "「进程内内存查询耗时」还是「端到端含模型推理耗时」；\n"
            "c. 复现性小节：实验设置必须写明运行环境（Python 版本/平台）、"
            "种子列表、预算档位、检索配置（检索器类型/k 值等）；\n"
            "d. 相关工作定位：与 ideation 给出的 ≥5 个近邻系统逐一定位对比，"
            "参考文献不少于 5 条。\n"
            "【主张对齐·必须】标题/摘要/结论的优越性主张只能指向实验矩阵中"
            "真实存在的策略对比；假设中提及但实验未覆盖的模块不得出现在"
            "主张里；无界基线（全量上下文）只能表述为 oracle 上界参照，"
            "禁止宣称「优于全量上下文」类断言。\n"
            "【交付纪律·必须逐条执行】\n"
            "1. 将论文 Markdown 全文写入文件 " + DRAFT_PATH + "（绝对路径，"
            "若目录不存在则创建）；\n"
            "2. 你的最终回复必须原样包含论文全文——禁止只回复概览、摘要或"
            "完成报告，下游校对员只能看到你的最终回复文本；\n"
            "3. 回复末尾单独一行标注：DRAFT_FILE=" + DRAFT_PATH + "\n"
            "若实验结果与文件均不可用，明确报告数据缺失并停止，不得凭空杜撰数值。\n"
            "研究假设：{hypothesis}\n实验方案：{plan}\n实验结果（唯一数据源）：{results}\n"
            + w1
        ).format(
            hypothesis=hypothesis or FALLBACK_HYPOTHESIS,
            plan=plan or "默认 memory_bench 矩阵",
            results=results,
        ),
        label="writing",
        phase=PHASE_WRITING,
        options=WOPT_SLOW,
    )

    # 引擎侧真值注入：draft 以落盘文件为准，保证 writing→proofread 数据不断流
    try:
        with open(DRAFT_PATH, encoding="utf-8") as _f:
            _draft_file = _f.read()
        if len(_draft_file) > 200:
            draft = _draft_file
            log(f"真值注入：draft_v4.md 已落盘（{len(_draft_file)}B），"
                "proofread 以文件全文为准")
        else:
            log(f"WARN: draft_v4.md 过短（{len(_draft_file)}B），保留 worker 返回值")
    except Exception as _exc:
        log(f"WARN: 引擎侧读取 draft_v4.md 失败（{_exc}），保留 worker 返回值")
    log(f"论文初稿完成（要求落盘 {DRAFT_PATH}）。")
    return draft


async def _proofread(draft: str) -> str:
    phase(PHASE_WRITING)
    final = await agent(
        (
            "你是论文审稿校对员。论文初稿文件在 " + DRAFT_PATH + "（绝对路径）。\n"
            "【工具纪律】使用文件读取/写入工具操作文档，禁止用浏览器。\n"
            "【执行步骤】\n"
            "1. 先读取 " + DRAFT_PATH + " 全文作为校对对象。"
            "下方附加的「初稿文本」可能只是写作员的概览而非全文，"
            "以文件内容为准；若文件不存在，则基于 " + RESULTS_ABS + " "
            "直接产出最小可信论文。\n"
            "2. 检查：① 章节结构是否完整（摘要/引言/相关工作/方法/实验/"
            "结论/参考文献）；"
            "② 页数硬性门禁：成稿编译 PDF 后必须正好 15 页（pdflatex 实测），"
            "不达标则按数据纪律修正篇幅后重新编译，页数不对不得定稿；"
            "③ 逐个数值核对：论文中每个量化数字是否都能在真实落盘的 "
            + RESULTS_ABS + " 中找到，找不到的必须删除或改正；"
            "④ 有无无依据的断言（幻觉）；⑤ 引用是否规范；"
            "⑥ 主张-证据对齐：标题/摘要/结论的每个优越性主张是否都有"
            "实验矩阵中的真实对比支撑——无界基线（全量上下文）只能作 "
            "oracle 上界参照，禁止「优于全量上下文」类断言；假设提及但"
            "实验未覆盖的模块必须从主张中删除；"
            "⑦ 报告规范：准确率表是否附 std/CI；延迟是否声明测量口径"
            "（进程内 or 端到端）；是否写明环境/种子/预算/检索配置；"
            "参考文献是否 ≥5 条且有定位对比。\n"
            "3. 修订后将最终版论文全文写入 " + FINAL_PATH + "（绝对路径）。\n"
            "【自修订纪律】若你的上下文或系统注记中出现 PAPER_LAB[hallucination]、"
            "PAPER_LAB[claim_alignment] 或 PAPER_LAB[academic] 告警，必须逐条修订："
            "未溯源数值删除或改为 results.json 中的原始值；不公平对照断言改为"
            "「受限策略间比较 + oracle 仅作上界」表述；缺统计置信补 std/CI；"
            "缺指标口径补测量口径声明；缺复现要素补环境/种子/预算/检索配置；"
            "相关工作不足补近邻系统定位；缺章节补齐；悬空引用修正。"
            "终稿只使用 results.json 原始值，禁止出现由原始值换算的相对百分比"
            "（如 XX%）等衍生数值——如需表达提升，用原始值对比表述"
            "（如 0.1181 高于基线 0.1032）。\n"
            "4. 最终回复必须包含：修订点清单 + 论文全文 + 单独一行标注 "
            "FINAL_FILE=" + FINAL_PATH + "\n"
            "初稿文本（仅供参考，以文件为准）：{draft}"
        ).format(draft=draft or "（空——请直接读取上述初稿文件）"),
        label="proofread",
        phase=PHASE_WRITING,
        options=WOPT_SLOW,
    )
    log(f"论文定稿完成（要求落盘 {FINAL_PATH}）。")
    return final


async def run(args):
    # args 可能是 JSON 字符串，需先解析为 dict 才能 .get()
    if isinstance(args, str):
        import json as _json

        try:
            args = _json.loads(args)
        except (ValueError, TypeError):
            args = None
    if not isinstance(args, dict):
        args = {}
    topic = args.get("topic", "一个聚焦的 AI 研究方向")
    pacing = args.get("pacing", True)
    # 确保 draft/final 的落盘目录存在，否则真值注入会落空
    os.makedirs(PAPER_LAB + "/paper", exist_ok=True)
    log(f"科研流水线（v6 W1闭环版 worker模型={WORKER_MODEL}）启动，主题：{topic} pacing={pacing}")

    if pacing:
        import asyncio as _asyncio

        # 启动延迟：避开 leader 应答调用的并发窗口（GLM 免费档并发≈2）
        log(f"等待 {STARTUP_DELAY_S}s：让 leader 收尾调用结束、释放并发槽……")
        await _asyncio.sleep(STARTUP_DELAY_S)

    async def _pace():
        if pacing:
            import asyncio as _asyncio

            log(f"阶段间隔 {PHASE_GAP_S}s：压低请求密度，避免触发限流……")
            await _asyncio.sleep(PHASE_GAP_S)

    hypothesis = await _ideation(topic)
    await _pace()
    review = await _hypothesis_review(hypothesis)
    await _pace()
    # W1 闭环：解析评审返回的 module_gaps，作为硬约束注入下游
    review_info = _parse_review(review)
    module_gaps = review_info.get("module_gaps") or []
    if module_gaps:
        log(f"W1 模块覆盖缺口：{module_gaps}（将作为硬约束注入规划与写作）")
    plan = await _planning(hypothesis, review, module_gaps=module_gaps)
    await _pace()
    results = await _experiment(plan)
    await _pace()
    draft = await _writing(hypothesis, plan, results, module_gaps=module_gaps)
    await _pace()
    final = await _proofread(draft)

    spent = budget.spent()
    log(f"论文成稿完成。初稿={DRAFT_PATH} 定稿={FINAL_PATH} 累计 Token：{spent}")

    return {
        "paper": final,
        "draft_file": DRAFT_PATH,
        "final_file": FINAL_PATH,
        "hypothesis": hypothesis,
        "plan": plan,
        "results": results,
        "token_spent": spent,
    }

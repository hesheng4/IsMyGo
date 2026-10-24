"""生成 paper_guard.patch：以反向编辑重构上游基线文件，difflib 产出 git-apply 兼容补丁。
运行：python gen_patch.py

注意：本脚本仅覆盖补丁一（paper_guard rails，7 文件）。
完整 10 文件补丁（含补丁二 research_tools）请从功能分支用
`git diff develop feat/paper-guard-rails > paper_guard.patch` 生成，
勿用本脚本输出覆盖参赛包内的完整补丁（详见 framework_contribution.md 附录）。
"""
import difflib
import os
import pathlib
import sys

# 仓库根目录：相对本脚本定位（parents[2] = IsMyGo），可用 PAPER_LAB 覆盖。

ROOT = pathlib.Path(os.environ.get("PAPER_LAB")
                    or pathlib.Path(__file__).resolve().parents[2])
REPO = ROOT / "jiuwenswarm-develop"
OUT = ROOT / "code" / "framework-contribution" / "paper_guard.patch"

# ---- 反向编辑表：由已改文件还原出上游基线，供 difflib 生成补丁 ----
REVERSE = {
    "jiuwenswarm/agents/swarm/providers/member_rails.py": [
        ('MODEL_ANOMALY_DETECTION = "swarm.model_anomaly_detection"\n'
         '# Research-paper quality guard (hallucination check + academic format).\n'
         'PAPER_GUARD = "swarm.paper_guard"\n',
         'MODEL_ANOMALY_DETECTION = "swarm.model_anomaly_detection"\n'),
    ],
    "jiuwenswarm/agents/swarm/registry.py": [
        ('MODEL_ANOMALY_DETECTION = _member_rails.MODEL_ANOMALY_DETECTION\n'
         'PAPER_GUARD = _member_rails.PAPER_GUARD\n',
         'MODEL_ANOMALY_DETECTION = _member_rails.MODEL_ANOMALY_DETECTION\n'),
        ('    "MODEL_ANOMALY_DETECTION",\n    "PAPER_GUARD",\n',
         '    "MODEL_ANOMALY_DETECTION",\n'),
    ],
    "jiuwenswarm/agents/swarm/config_specs.py": [
        ('    registry.MODEL_ANOMALY_DETECTION,\n    registry.PAPER_GUARD,\n    registry.HEARTBEAT,\n',
         '    registry.MODEL_ANOMALY_DETECTION,\n    registry.HEARTBEAT,\n'),
        ('def _paper_guard_params(config: dict[str, Any]) -> dict[str, Any]:\n'
         '    """Attribute params for the research-paper guard rails."""\n'
         '    return {\n'
         '        "paper_guard_config": _config_section(config, "paper_guard"),\n'
         '    }\n\n\n',
         ''),
        ('    registry.MODEL_ANOMALY_DETECTION: _model_anomaly_detection_params,\n'
         '    registry.PAPER_GUARD: _paper_guard_params,\n',
         '    registry.MODEL_ANOMALY_DETECTION: _model_anomaly_detection_params,\n'),
    ],
    "jiuwenswarm/resources/config.yaml": [
        ('# 科研论文护栏：幻觉校验 + 学术结构规范（科研论文自动生成场景）\n'
         'paper_guard:\n'
         '  # 总开关。开启后为每个团队成员挂载 HallucinationCheckRail + AcademicFormatRail\n'
         '  enabled: false\n'
         '  # 真实实验结果基准文件（JSON）。模型输出中的量化断言必须可溯源到该文件，\n'
         '  # 否则注入告警。留空时使用默认路径 ~/.jiuwenswarm/agent/workspace/output/results.json\n'
         '  # results_path: /path/to/results.json\n\n',
         ''),
    ],
}

# member_rails.py 的 provider 块整体移除（多行，用锚点截取）
PROVIDER_BLOCK_START = "class PaperGuardInput(ConstructionInput):"
PROVIDER_BLOCK_END = "    return rails or None\n"


def reverse_member_rails(text: str) -> str:
    text = text.replace(REVERSE["jiuwenswarm/agents/swarm/providers/member_rails.py"][0][0],
                        REVERSE["jiuwenswarm/agents/swarm/providers/member_rails.py"][0][1])
    start = text.index(PROVIDER_BLOCK_START)
    end = text.index(PROVIDER_BLOCK_END, start) + len(PROVIDER_BLOCK_END)
    # 连同块后的两个空行一起移除
    tail = text[end:end + 2]
    assert tail == "\n\n", repr(tail)
    text = text[:start] + text[end + 2:]
    text = text.replace('    "PAPER_GUARD",\n', '')
    return text


def udiff(pristine: str, current: str, rel: str) -> list[str]:
    d = difflib.unified_diff(
        pristine.splitlines(keepends=True), current.splitlines(keepends=True),
        fromfile=f"a/{rel}", tofile=f"b/{rel}", n=3,
    )
    return list(d)


def new_file_diff(rel: str, content: str) -> list[str]:
    lines = content.splitlines(keepends=True)
    out = [f"diff --git a/{rel} b/{rel}\n", "new file mode 100644\n",
           "--- /dev/null\n", f"+++ b/{rel}\n", f"@@ -0,0 +1,{len(lines)} @@\n"]
    out += ["+" + l for l in lines]
    return out


patch: list[str] = []

# 修改文件
member_rel = "jiuwenswarm/agents/swarm/providers/member_rails.py"
cur = (REPO / member_rel).read_text(encoding="utf-8")
pris = reverse_member_rails(cur)
# 基线必须不含 PAPER_GUARD 残留
assert "PAPER_GUARD" not in pris and "PaperGuardInput" not in pris, "reverse incomplete"
patch += [f"diff --git a/{member_rel} b/{member_rel}\n"] + udiff(pris, cur, member_rel)

for rel, rules in REVERSE.items():
    if rel == member_rel:
        continue
    cur = (REPO / rel).read_text(encoding="utf-8")
    pris = cur
    for old, new in rules:
        assert old in pris, f"anchor missing in {rel}"
        pris = pris.replace(old, new)
    if rel.endswith(".py"):
        assert "PAPER_GUARD" not in pris, f"reverse incomplete: {rel}"
    patch += [f"diff --git a/{rel} b/{rel}\n"] + udiff(pris, cur, rel)

# 新增文件（paper_guard 包）
for f in sorted((REPO / "jiuwenswarm/agents/harness/common/rails/paper_guard").iterdir()):
    if f.suffix == ".py":
        patch += new_file_diff(
            f"jiuwenswarm/agents/harness/common/rails/paper_guard/{f.name}",
            f.read_text(encoding="utf-8"),
        )

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("".join(patch), encoding="utf-8", newline="\n")
n_files = "".join(patch).count("diff --git ")
print(f"OK {OUT}  files={n_files}  lines={len(patch)}")

# 自检：基线 YAML 仍可解析且无 paper_guard
import yaml
cfg = yaml.safe_load(REVERSE["jiuwenswarm/resources/config.yaml"] and
                     (REPO / "jiuwenswarm/resources/config.yaml").read_text(encoding="utf-8")
                     .replace(REVERSE["jiuwenswarm/resources/config.yaml"][0][0], ""))
assert "paper_guard" not in cfg, "baseline still has paper_guard"
print("baseline config.yaml reverse-check PASS (no paper_guard, parses OK)")
sys.exit(0)
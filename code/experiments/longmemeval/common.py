# -*- coding: utf-8 -*-
"""LongMemEval 评测公共层：数据集加载、分层抽样、tokenizer、模型配置。

数据: ModelScope evalscope/longmemeval-cleaned 的 longmemeval_s_cleaned 划分
      (500 题, 6 题型, 已由 EvalScope 团队剔除干扰会话)。
预算单位: cl100k_base token (tiktoken 0.14.0), 论文中显式声明。
"""
from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATASET_PATH = (
    Path(__file__).resolve().parents[3]
    / "data" / "longmemeval-cleaned" / "longmemeval_s_cleaned.json"
)


@lru_cache(maxsize=1)
def get_encoding():
    import tiktoken
    return tiktoken.get_encoding("cl100k_base")

# 按题型分层抽样 (合计 120, seed 固定, 顺序确定)
STRATA = {
    "multi-session": 32,
    "temporal-reasoning": 32,
    "knowledge-update": 19,
    "single-session-user": 17,
    "single-session-assistant": 13,
    "single-session-preference": 7,
}
SAMPLE_SEED = 42
BUDGETS = [512, 1024, 2048, 4096]
SMOKE_N = 10


def ntokens(text: str) -> int:
    # disallowed_special=(): 数据集文本可能包含 <|endoftext|> 等特殊 token 字面量,
    # 按普通文本计数而非让 tiktoken 抛错
    return len(get_encoding().encode(text, disallowed_special=()))


def truncate_to_budget(text: str, budget: int) -> str:
    ids = get_encoding().encode(text, disallowed_special=())
    if len(ids) <= budget:
        return text
    return get_encoding().decode(ids[:budget])


@dataclass
class Turn:
    session_idx: int
    turn_idx: int
    role: str
    content: str
    session_id: str
    text: str = ""          # "user: ..." 完整可检索文本
    ntok: int = 0

    def __post_init__(self) -> None:
        # disallowed_special=(): 数据集文本可能包含 <|endoftext|> 等特殊 token 字面量,
        # 按普通文本计数而非让 tiktoken 抛错
        self.text = f"{self.role}: {self.content}"
        self.ntok = ntokens(self.text)
        # 稳定键 (内置 hash 每进程加盐): 向量缓存/RRF 融合排序用
        import hashlib
        self.turn_key = hashlib.sha1(self.text.encode("utf-8")).hexdigest()[:16]


@dataclass
class Question:
    question_id: str
    question_type: str
    question: str
    question_date: str
    answer: str
    turns: list[Turn] = field(default_factory=list)
    session_ids: list[str] = field(default_factory=list)
    answer_session_ids: list[str] = field(default_factory=list)  # 金证据所在会话
    session_dates: dict[str, str] = field(default_factory=dict)  # 会话 -> 首次出现时间


def load_questions(n: int | None = None, seed: int = SAMPLE_SEED,
                   full: bool = False) -> list[Question]:
    """full=True: 全量 500 题 (不分层抽样, 审稿回应 W1 的 full-set 复跑);
    其余行为不变 (n=None -> 120 题分层, n=int -> 按比例冒烟)。"""
    raw = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    by_type: dict[str, list[dict]] = {}
    for item in raw:
        by_type.setdefault(item["question_type"], []).append(item)

    rng = random.Random(seed)
    picked: list[dict] = []
    if full:
        for qtype in sorted(by_type):
            picked.extend(sorted(by_type[qtype], key=lambda x: x["question_id"]))
    elif n is None:
        counts = STRATA
        for qtype, cnt in sorted(counts.items()):
            pool = sorted(by_type.get(qtype, []), key=lambda x: x["question_id"])
            picked.extend(rng.sample(pool, min(cnt, len(pool))))
    else:  # 冒烟测试: 按比例缩减
        total = sum(STRATA.values())
        counts = {k: max(1, round(v * n / total)) for k, v in STRATA.items()}
        for qtype, cnt in sorted(counts.items()):
            pool = sorted(by_type.get(qtype, []), key=lambda x: x["question_id"])
            picked.extend(rng.sample(pool, min(cnt, len(pool))))

    out: list[Question] = []
    for item in picked:
        q = Question(
            question_id=item["question_id"],
            question_type=item["question_type"],
            question=item["question"],
            question_date=item.get("question_date", ""),
            answer=item["answer"],
            session_ids=list(item.get("haystack_session_ids", [])),
            answer_session_ids=list(item.get("answer_session_ids", [])),
        )
        # 事件锚定检索用: 每个会话取其首轮的时间戳
        for si, sid in enumerate(q.session_ids):
            if si < len(item.get("haystack_dates", [])):
                q.session_dates[sid] = item["haystack_dates"][si]
        for si, sess in enumerate(item["haystack_sessions"]):
            sid = (
                item["haystack_session_ids"][si]
                if si < len(item.get("haystack_session_ids", []))
                else f"{item['question_id']}-s{si}"
            )
            for ti, turn in enumerate(sess):
                q.turns.append(
                    Turn(si, ti, turn["role"], turn["content"], sid)
                )
        out.append(q)
    out.sort(key=lambda q: q.question_id)
    return out


def unique_sessions(questions: list[Question]) -> dict[str, list[Turn]]:
    """跨题去重后的 session_id -> turns 映射, 摘要预计算只跑一遍。"""
    sessions: dict[str, list[Turn]] = {}
    for q in questions:
        for t in q.turns:
            sessions.setdefault(t.session_id, []).append(t)
    for sid in sessions:
        sessions[sid].sort(key=lambda t: (t.session_idx, t.turn_idx))
    return sessions


# 本地模型登记表: key -> (ModelScope 仓库名, 用途)。供 require_model 预检与
# code/scripts/fetch_models.py 下载器共用同一口径。
LOCAL_MODELS = {
    "bge-small": ("BAAI/bge-small-en-v1.5", "dense 检索基线 / hybrid 融合 (Table 12)"),
    "bge-base": ("BAAI/bge-base-en-v1.5", "dense 升级消融腿 (Table 9)"),
    "bge-reranker": ("BAAI/bge-reranker-base", "交叉编码器重排探针 (Table 9)"),
}


def require_model(model_dir, key: str) -> None:
    """加载本地模型前的存在性预检: 缺失时给出明确指引并退出, 而不是让
    sentence-transformers 把绝对路径当 HuggingFace 模型 ID 抛出晦涩网络错误。

    判定标准: 目录存在 + config.json + 权重 (model.safetensors 或
    pytorch_model.bin) + tokenizer.json。满足即放行, 交由加载器做完整校验。
    """
    model_dir = Path(model_dir)
    repo, usage = LOCAL_MODELS[key]
    missing = []
    if not model_dir.is_dir():
        missing.append(str(model_dir) + "/ (整个目录)")
    else:
        if not (model_dir / "config.json").is_file():
            missing.append("config.json")
        if not any((model_dir / w).is_file()
                   for w in ("model.safetensors", "pytorch_model.bin")):
            missing.append("model.safetensors / pytorch_model.bin (权重)")
        if not (model_dir / "tokenizer.json").is_file():
            missing.append("tokenizer.json")
    if missing:
        pkg_root = Path(__file__).resolve().parents[3]
        print(f"[模型缺失] {key} ({repo}) —— {usage}", file=sys.stderr)
        print(f"  路径: {model_dir}", file=sys.stderr)
        print("  缺失: " + ", ".join(missing), file=sys.stderr)
        print("  修复(任选其一):", file=sys.stderr)
        print(f"    1) python {pkg_root / 'code' / 'scripts' / 'fetch_models.py'} --only {key}", file=sys.stderr)
        print(f"    2) git -c http.sslBackend=openssl clone --depth 1 "
              f"https://www.modelscope.cn/{repo}.git  {model_dir}", file=sys.stderr)
        raise SystemExit(2)


def load_model_config() -> dict:
    """从 ~/.jiuwenswarm/config/config.yaml 读取主模型配置 (与框架共用一份密钥)。"""
    import os
    import re

    import yaml

    cfg_path = Path.home() / ".jiuwenswarm" / "config" / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    def resolve(v: str) -> str:
        return os.path.expandvars(re.sub(r"\$\{([^:-]+):-?([^}]*)\}", r"\2", v))

    # 主模型位于 models.defaults[0].model_client_config (is_default: true)
    defaults = cfg.get("models", {}).get("defaults", [])
    main = next(
        (d["model_client_config"] for d in defaults
         if d.get("is_default", True)),
        {},
    )
    api_key = str(main.get("api_key", ""))
    return {
        "api_base": resolve(str(main.get("api_base", ""))).rstrip("/"),
        "api_key": resolve(str(api_key)),
        "model": str(main.get("model_name") or DEFAULT_MODEL),
    }


# --------------------------------------------------------------------------- #
# 模型名解析入口（全项目统一，可灵活切换模型）
#   主模型（摘要/答题）  优先级：PAPER_LAB_MODEL 环境变量
#                        > config.yaml model_name > DEFAULT_MODEL
#   跨读者/裁判模型      优先级：PAPER_LAB_ALT_MODEL 环境变量 > DEFAULT_ALT_MODEL
# 读取失败（如目标机未安装配置）时静默回退默认值，保证跨环境可迁移。
# --------------------------------------------------------------------------- #
DEFAULT_MODEL = "glm-4.7-flash"
DEFAULT_ALT_MODEL = "GLM-4.7-Flash"


def resolve_model_names() -> dict:
    import os

    try:
        cfg_model = (load_model_config() or {}).get("model") or ""
    except Exception:
        cfg_model = ""
    return {
        "main": os.environ.get("PAPER_LAB_MODEL") or cfg_model or DEFAULT_MODEL,
        "alt": os.environ.get("PAPER_LAB_ALT_MODEL") or DEFAULT_ALT_MODEL,
    }


# --------------------------------------------------------------------------- #
# 记录的答题器模型归属（断点续跑 / 表格聚合的模型判定，答题器随配置变化的前提）
#   新记录带 model 字段（run.py 逐题写入）；历史记录按其生成时的读者回退：
#   主网格 = LEGACY_READER（归档运行为 GLM-4-Flash），跨读者按策略后缀 @mXX。
# --------------------------------------------------------------------------- #
LEGACY_READER = "GLM-4-Flash"
_CROSS_SUFFIX_MODEL = {
    "m47": "GLM-4.7-Flash",
    "m51": "zai-org/GLM-5.1",
    "m53": "glm5.3-flash",
}


def record_model(rec: dict) -> str:
    """该记录所属的答题器模型名。"""
    if rec.get("model"):
        return str(rec["model"])
    import re
    m = re.search(r"@(m\d+)$", str(rec.get("policy", "")))
    if m:
        return _CROSS_SUFFIX_MODEL.get(m.group(1), LEGACY_READER)
    return LEGACY_READER


def record_matches_model(rec: dict, model_tag: str) -> bool:
    """断点续跑判定：该记录是否由 model_tag 这个答题器生成（换模型须重新答题）。"""
    return record_model(rec) == model_tag


def model_cache_ns(model_tag: str) -> str:
    """LLM 产物缓存命名空间按生成模型隔离（摘要/答案）：
    GLM-4-Flash 保留历史命名空间（v2，兼容归档缓存），其余为 v2-{model}。
    换模型即换命名空间 → 摘要/答案全部由新模型重新生成（全新流程，不复用旧模型产物）。"""
    return "v2" if model_tag == LEGACY_READER else f"v2-{model_tag}"


def fresh_run() -> bool:
    """PAPER_LAB_FRESH=1 或 run.py --fresh：忽略一切 LLM 缓存与断点续跑记录，
    以当前模型完整重新执行（全新流程）。"""
    import os
    return os.environ.get("PAPER_LAB_FRESH", "").strip().lower() in ("1", "true", "yes")


def format_context(segments: list[str]) -> str:
    return "\n\n".join(segments)

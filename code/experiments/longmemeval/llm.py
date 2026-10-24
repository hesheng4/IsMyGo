# -*- coding: utf-8 -*-
"""LLM 调用层: 会话摘要 (compression 策略) 与答题。

- 客户端: openai SDK, base_url 指向 ~/.jiuwenswarm/config/config.yaml 的主模型
  (bigmodel v4 端点, 默认 glm-4.7-flash), 与 JiuwenSwarm 框架共用同一份密钥。
- 并发: asyncio.Semaphore(8) + 抖动退避, 规避资源报告中记录过的 429 重试风暴。
- 缓存: 摘要按 session_id 落盘, 断点续跑; 答题按 (policy,budget,qid) 落盘。
- 计量: 每次调用记录 usage/延迟, 供资源报告聚合 (llm.log 由框架侧记录,
  本层 results.jsonl 为实验侧可追溯流水)。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import time
from functools import lru_cache
from pathlib import Path

from openai import AsyncOpenAI

from common import load_model_config, model_cache_ns, fresh_run, resolve_model_names


@lru_cache(maxsize=1)
def _get_cfg():
    return load_model_config()


@lru_cache(maxsize=1)
def _get_client():
    cfg = _get_cfg()
    return AsyncOpenAI(api_key=cfg["api_key"], base_url=cfg["api_base"], timeout=120.0)


SEM = asyncio.Semaphore(int(os.environ.get("PAPER_LAB_CONCURRENCY", "24")))

# 单次 LLM 调用硬超时（秒）: SDK 自带 timeout 在个别慢连接上不生效, 这里以
# asyncio.wait_for 做权威兜底, 超时走统一退避重试; 可经 PAPER_LAB_LLM_TIMEOUT 覆盖。
LLM_CALL_TIMEOUT = float(os.environ.get("PAPER_LAB_LLM_TIMEOUT", "240"))

# --------------------------------------------------------------------------- #
# 模型配置入口（可灵活切换，全项目统一经 common.resolve_model_names() 解析）：
#   MODEL_MAIN 主模型（摘要/答题）  PAPER_LAB_MODEL > config.yaml model_name
#                                   > 默认 glm-4.7-flash
#   MODEL_ALT  跨读者/裁判模型      PAPER_LAB_ALT_MODEL > 默认 GLM-4.7-Flash
# --------------------------------------------------------------------------- #
_MODEL_NAMES = resolve_model_names()
MODEL_MAIN = _MODEL_NAMES["main"]
MODEL_ALT = _MODEL_NAMES["alt"]


def _needs_disable_thinking(model: str) -> bool:
    """GLM-4.7 / GLM-5.x 系列必须关闭思考模式, 否则思考 token 吃满输出预算导致空答案。
    PAPER_LAB_DISABLE_THINKING=1 强制关闭（陌生推理型模型兜底）。"""
    import os
    if os.environ.get("PAPER_LAB_DISABLE_THINKING", "").strip().lower() in ("1", "true", "yes"):
        return True
    m = (model or "").lower()
    return "4.7" in m or m.startswith("glm-5") or "glm-5" in m or "glm5" in m


def _answer_max_tokens(model: str) -> int:
    """答题输出预算：PAPER_LAB_ANSWER_MAX_TOKENS 显式覆盖（回应输出长度限制的普遍性质疑）；
    否则思考型模型 (GLM-5.x, 思考无法关闭) 240，其余 64（与历史网格同口径）。"""
    env = os.environ.get("PAPER_LAB_ANSWER_MAX_TOKENS")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    m = (model or "").lower()
    return 240 if ("glm5" in m or "glm-5" in m) else 64


def _answer_temperature() -> float:
    """答题解码温度：PAPER_LAB_ANSWER_TEMPERATURE 覆盖；默认 0.0（贪心，与历史网格同口径）。"""
    env = os.environ.get("PAPER_LAB_ANSWER_TEMPERATURE")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    return 0.0


# 网关伪成功检测: gitcode 网关限流/过载时把错误文本作为正常 content 返回
# (usage=None), 不抛异常; 若不识别会把错误串当成答案污染记录。
# 20261015: 补英文内容过滤拒绝文本 "The request was rejected because..." ——
# 网关把拒绝文本当正常 content 返回, 之前未识别即落盘为答案(EM=0 伪退化)。
_GATEWAY_ERR_RE = __import__("re").compile(
    r"^(三方请求失败|模型[「\[]?.{0,40}[」\]]?的请求负载过高|参数错误|系统检测到"
    r"|[Tt]he request was rejected)")

# --------------------------------------------------------------------------- #
# 运行日志：logs/calls.jsonl（每次 LLM 调用一行）+ logs/run.json（运行总账）
# 由 code/scripts/run_logger.py 提供；经环境变量 RUN_LOG_DIR + RUN_ID 启用。
# 未设置 RUN_LOG_DIR 时完全静默，不影响任何既有行为。
# --------------------------------------------------------------------------- #
RUN_LOGGER = None
_RUN_LOG_DIR = os.environ.get("RUN_LOG_DIR")
if _RUN_LOG_DIR:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from run_logger import RunLogger as _RunLogger  # type: ignore
    RUN_LOGGER = _RunLogger(
        run_id=os.environ.get("RUN_ID", "agent-sci-2026-comp-001"),
        out_dir=_RUN_LOG_DIR,
        model=MODEL_MAIN,
        topic=os.environ.get("RUN_TOPIC", "Agent记忆引擎：长程流式任务中的记忆策略权衡"),
        command=os.environ.get("RUN_COMMAND", ""),
        output_paper=os.environ.get("RUN_OUTPUT_PAPER", ""),
    )


def _log_call(model: str, t0: float, ms: float, usage, purpose: str) -> None:
    """把一次成功调用写入 logs/calls.jsonl（RUN_LOGGER 未启用时静默）。"""
    if RUN_LOGGER is None:
        return
    import datetime as _d
    end = _d.datetime.now().astimezone()
    start = end - _d.timedelta(milliseconds=ms)
    try:
        RUN_LOGGER.log_call(
            model=model,
            started_at=start.isoformat(timespec="seconds"),
            ended_at=end.isoformat(timespec="seconds"),
            input_tokens=(usage.prompt_tokens if usage else 0),
            output_tokens=(usage.completion_tokens if usage else 0),
            module=purpose or "llm",
        )
    except Exception:
        pass  # 日志失败不得影响实验主流程

# 模型名经 common.resolve_model_names() 统一解析（默认 glm-4.7-flash，入口可切换）;
# MODEL_ALT 用于跨读者稳健性复跑/裁判 (默认 GLM-4.7-Flash, 需关闭思考模式)

def summary_sys(max_words: int = 60) -> str:
    return (
        "You compress a conversation session between a user and an assistant into a "
        "fact-dense memory digest. Keep: names, dates, numbers, preferences, decisions, "
        "corrections and factual statements about the user. Drop greetings and filler. "
        f"Output at most {max_words} words, one paragraph, no preamble."
    )
ANSWER_SYS = (
    "You answer questions about a user based on stored memory from past conversations. "
    "Reply with ONLY the exact factual answer phrase copied as verbatim as possible from "
    "the memory: a few words, no explanation, no full sentence, no units beyond what the "
    "memory states. If the answer is a number, reply with just the number. Never pad the "
    "answer with extra words. If the memory does not contain the answer, reply with your "
    "best guess."
)


async def _chat(system: str, user: str, max_tokens: int, temperature: float = 0.0,
                model: str | None = None, disable_thinking: bool = False,
                purpose: str = "") -> dict:
    """带退避重试的单次调用, 返回 {text, prompt_tokens, completion_tokens, ms}。"""
    last_err: Exception | None = None
    model = model or MODEL_MAIN
    extra = ({"extra_body": {"thinking": {"type": "disabled"}}}
             if (disable_thinking or _needs_disable_thinking(model)) else {})
    for attempt in range(int(os.environ.get("PAPER_LAB_LLM_ATTEMPTS", "10"))):
        try:
            async with SEM:
                t0 = time.perf_counter()
                resp = await asyncio.wait_for(
                    _get_client().chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **extra,
                    ),
                    timeout=LLM_CALL_TIMEOUT,
                )
                ms = (time.perf_counter() - t0) * 1000.0
                u = resp.usage
                text = (resp.choices[0].message.content or "").strip()
                if _GATEWAY_ERR_RE.match(text):
                    # 网关伪成功: 错误文本伪装成正常响应 -> 当失败走退避重试
                    raise RuntimeError(f"gateway pseudo-success: {text[:120]}")
                # 运行日志（logs/calls.jsonl）：每次真实 LLM 调用落一行，
                # 由 RUN_LOGGER 写出；未启用时静默跳过（零开销）。
                _log_call(model, t0, ms, u, purpose)
                return {
                    "text": text,
                    "prompt_tokens": u.prompt_tokens if u else 0,
                    "completion_tokens": u.completion_tokens if u else 0,
                    "ms": ms,
                }
        except Exception as e:  # noqa: BLE001 - 网络/限流统一退避
            last_err = e
            msg = str(e)
            if ("429" in msg or "1302" in msg or "1305" in msg
                    or "gateway pseudo-success" in msg or "负载过高" in msg):
                # 速率限流: 更长退避, 等待配额窗口
                await asyncio.sleep(min(180.0, 15.0 * (attempt + 1) + random.random() * 10))
            else:
                await asyncio.sleep(min(60.0, (2**attempt) + random.random() * 2))
    raise RuntimeError(f"LLM call failed after retries: {last_err}")


def _cache_path(base: Path, key: str) -> Path:
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return base / f"{h}.json"


_SUMMARY_CAPS = {20: 60, 60: 140, 120: 260}


async def summarize_session(session_id: str, turns: list, cache_dir: Path,
                            max_words: int = 60) -> str:
    """会话级摘要 (compression/hierarchical 共用), 按词上限+生成模型分桶缓存。
    缓存命名空间含生成模型：换模型不复用旧模型摘要（全新流程）。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    ns = model_cache_ns(MODEL_MAIN)
    key = (f"summary:{ns}:{session_id}" if max_words == 60
           else f"summary:{ns}:w{max_words}:{session_id}")
    cp = _cache_path(cache_dir, key)
    if cp.exists() and not fresh_run():
        return json.loads(cp.read_text(encoding="utf-8"))["text"]
    text = "\n".join(t.text for t in turns)
    out = await _chat(summary_sys(max_words), text,
                      max_tokens=_SUMMARY_CAPS.get(max_words, 140),
                      purpose="摘要Agent(会话记忆压缩)")
    if not fresh_run():  # fresh 运行不落缓存，保护归档缓存不被覆盖
        cp.write_text(
            json.dumps({"session_id": session_id, "max_words": max_words,
                        "model": MODEL_MAIN, **out},
                       ensure_ascii=False),
            encoding="utf-8",
        )
    return out["text"]


async def summarize_fetched(question_id: str, question: str, evidence: str,
                            cache_dir: Path, max_words: int) -> str:
    """compression_fetch 阶段2: 把检索到的证据压缩为问题聚焦摘要 (先取后总结)。
    按 (词上限, question_id, 生成模型) 缓存——换模型不复用旧产物; 断点续跑; 失败向上抛由调用方决定降级。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = f"fetch:{model_cache_ns(MODEL_MAIN)}:w{max_words}:{question_id}"
    cp = _cache_path(cache_dir, key)
    if cp.exists() and not fresh_run():
        return json.loads(cp.read_text(encoding="utf-8"))["text"]
    sys_p = (
        "You compress retrieved evidence from past conversations into a fact-dense "
        "digest oriented toward a specific question. Keep: names, dates, numbers, "
        "preferences, decisions, corrections and any factual statements that help "
        "answer the question. Drop greetings and filler. "
        f"Output at most {max_words} words, one paragraph, no preamble."
    )
    user = (
        f"Question: {question}\n\n"
        f"Retrieved evidence from past conversations:\n\n{evidence}\n\n"
        "Write the digest."
    )
    out = await _chat(sys_p, user, max_tokens=max(int(max_words * 2.5), 64),
                      purpose="读取侧(fetch-then-summarize压缩)")
    if not fresh_run():  # fresh 运行不落缓存
        cp.write_text(
            json.dumps({"question_id": question_id, "max_words": max_words,
                        "model": MODEL_MAIN, **out},
                       ensure_ascii=False),
            encoding="utf-8",
        )
    return out["text"]


async def answer_with_memory(
    question: str,
    question_date: str,
    memory: str,
    cache_dir: Path,
    cache_key: str,
    model_tag: str = MODEL_MAIN,
) -> dict:
    """基于记忆上下文答题, 结果落盘缓存 (含 usage 与端到端延迟)。
    fresh 运行（PAPER_LAB_FRESH=1）不读不写缓存，强制以 model_tag 全新作答。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    # 答题缓存命名空间按生成模型隔离（model_cache_ns）：换模型不误用旧答案；
    # 历史主网格（GLM-4-Flash）保留旧命名空间 answer:v2，兼容归档缓存断点续跑。
    ns = "answer:" + model_cache_ns(model_tag)
    cp = _cache_path(cache_dir, f"{ns}:{cache_key}")
    if cp.exists() and not fresh_run():
        cached = json.loads(cp.read_text(encoding="utf-8"))
        ctext = (cached.get("text") or "").strip()
        # 退化缓存(空预测/拒绝文本)不复用——落到下方重新作答并覆盖,
        # 否则伪 0 行经缓存回放再次污染评分。
        if ctext and not _GATEWAY_ERR_RE.match(ctext):
            return cached
    date_line = f"(current date: {question_date})\n" if question_date else ""
    user = (
        f"Stored memory from past conversations:\n\n{memory}\n\n"
        f"{date_line}Based only on the memory above, answer:\n{question}"
    )
    budget = _answer_max_tokens(model_tag)
    out = await _chat(ANSWER_SYS, user, max_tokens=budget,
                      temperature=_answer_temperature(),
                      model=model_tag,
                      disable_thinking=_needs_disable_thinking(model_tag),
                      purpose="答题Agent(记忆策略评测)")
    # 截断空预测自适应放大: 空 text 且 completion_tokens 吃满 max_tokens => 思考挤占
    # 输出预算(mimo 等思考型模型 64 tokens 被思考吃满)。逐级放大输出预算重试,
    # 直到拿到非空答案或触及上限, 避免"截断空预测"被当成真实空答案落盘(EM=0 伪退化)。
    while not out["text"].strip() and out["completion_tokens"] >= budget and budget < 2048:
        budget = min(budget * 4, 2048)
        out = await _chat(ANSWER_SYS, user, max_tokens=budget,
                          temperature=_answer_temperature(),
                          model=model_tag,
                          disable_thinking=_needs_disable_thinking(model_tag),
                          purpose="答题Agent(记忆策略评测)")
    if not out["text"].strip():
        # 空预测不得落盘计 EM=0 污染评分（含放大预算后仍空）——抛错保持缺失,
        # run.py 侧不记录, 断点续跑自动重答。
        raise RuntimeError(f"empty prediction (budget={budget}, "
                           f"completion_tokens={out['completion_tokens']})")
    rec = {"cache_key": cache_key, "model": model_tag, **out}
    if not fresh_run():  # fresh 运行不落缓存
        cp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return rec

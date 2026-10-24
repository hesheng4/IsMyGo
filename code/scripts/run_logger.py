# -*- coding: utf-8 -*-
"""run_logger.py —— 运行日志记录器（程序写出，供 logs/run.json 与 logs/calls.jsonl）。

设计要点：
  * 每次 LLM 调用落一行到 calls.jsonl，字段与样例说明一致：
    run_id / index / model / started_at / ended_at / input_tokens / output_tokens
    / total_tokens / module
  * 运行结束时写 run.json：run_id / model / 起止时间 / wall_seconds / token 汇总
    / llm_calls / topic / command / output_dir / output_paper
  * token_total = sum(各行 total_tokens)，与 calls.jsonl 强一致（写入前断言）。
  * 追加写 + 崩溃安全：每行 flush，进程被中断也不丢已完成的调用。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import threading
import time
from pathlib import Path


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


class RunLogger:
    """一次运行的调用级与总账级日志。"""

    def __init__(self, run_id: str, out_dir: str | Path, *, model: str,
                 topic: str, command: str, output_paper: str) -> None:
        self.run_id = run_id
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.topic = topic
        self.command = command
        self.output_paper = output_paper
        self.calls_path = self.out_dir / "calls.jsonl"
        self.run_path = self.out_dir / "run.json"
        self._lock = threading.Lock()
        self._index = 0
        self._t_in = 0
        self._t_out = 0
        self._t0 = time.perf_counter()
        self.started_at = _now_iso()
        # 新运行清空上一次的调用流水（run.json 在结束时写）。
        # 用「写空文件」而非 unlink：这样即使本次运行一次 LLM 调用都没有，
        # calls.jsonl 仍是一个可读的合法文件（0 行）——
        # 若用 unlink，零调用运行时下游 read_text() 会 FileNotFoundError。
        self.calls_path.write_text("", encoding="utf-8")

    # ---------------- 调用级 ----------------
    def log_call(self, *, model: str, started_at: str, ended_at: str,
                 input_tokens: int, output_tokens: int, module: str,
                 extra: dict | None = None) -> dict:
        """记录一次 LLM 调用；返回写入的记录。"""
        with self._lock:
            self._index += 1
            rec = {
                "run_id": self.run_id,
                "index": self._index,
                "model": model,
                "started_at": started_at,
                "ended_at": ended_at,
                "input_tokens": int(input_tokens),
                "output_tokens": int(output_tokens),
                "total_tokens": int(input_tokens) + int(output_tokens),
                "module": module,
            }
            if extra:
                rec.update(extra)
            with open(self.calls_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self._t_in += int(input_tokens)
            self._t_out += int(output_tokens)
            return rec

    # ---------------- 总账级 ----------------
    def finish(self, *, output_dir: str, wall_seconds: float | None = None) -> dict:
        """写 run.json。token_total 与 calls.jsonl 逐行求和强一致。"""
        # 从 calls.jsonl 重新求和，杜绝内存计数与落盘不一致
        t_in = t_out = n = 0
        if self.calls_path.exists():
            for line in self.calls_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                t_in += int(r["input_tokens"])
                t_out += int(r["output_tokens"])
                n += 1
        assert n == self._index, "calls.jsonl 行数(%d) != 记录数(%d)" % (n, self._index)
        wall = wall_seconds if wall_seconds is not None else (time.perf_counter() - self._t0)
        payload = {
            "run_id": self.run_id,
            "model": self.model,
            "started_at": self.started_at,
            "ended_at": _now_iso(),
            "wall_seconds": round(wall, 1),
            "token_input": t_in,
            "token_output": t_out,
            "token_total": t_in + t_out,
            "llm_calls": n,
            "topic": self.topic,
            "command": self.command,
            "output_dir": output_dir,
            "output_paper": self.output_paper,
        }
        self.run_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        return payload


def verify_logs(out_dir: str | Path) -> dict:
    """校验 run.json 与 calls.jsonl 的一致性（供 CI / 复现自检）。"""
    d = Path(out_dir)
    run = json.loads((d / "run.json").read_text(encoding="utf-8"))
    calls = [json.loads(l) for l in (d / "calls.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    checks = {
        "run_id 一致": all(c["run_id"] == run["run_id"] for c in calls),
        "llm_calls 等于行数": run["llm_calls"] == len(calls),
        "token_input 等于求和": run["token_input"] == sum(c["input_tokens"] for c in calls),
        "token_output 等于求和": run["token_output"] == sum(c["output_tokens"] for c in calls),
        "token_total 等于求和": run["token_total"] == sum(c["total_tokens"] for c in calls),
        "token_total = input + output": run["token_total"] == run["token_input"] + run["token_output"],
        "模型名与 run.json 一致": all(c["model"] == run["model"] for c in calls),
        "index 连续从 1 开始": [c["index"] for c in calls] == list(range(1, len(calls) + 1)),
    }
    return {"passed": all(checks.values()), "checks": checks,
            "n_calls": len(calls), "token_total": run["token_total"]}

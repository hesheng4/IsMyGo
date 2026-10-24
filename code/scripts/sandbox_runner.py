"""通用子进程沙箱执行器：隔离运行实验脚本，捕获产物与退出状态。

用法：
    python scripts/sandbox_runner.py --script experiments/run_all.py --timeout 120
返回（stdout 末行 JSON）：{ok, exit_code, duration_sec, stdout_tail, stderr_tail}

安全边界（进程级隔离，非容器级）：
- 独立子进程 + 超时强杀；
- 固定 cwd（paper-lab 根）；
- 环境变量白名单（PATH/SYSTEM 等系统必需 + PAPER_GUARD_*），其余不透传。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
_ENV_ALLOW_PREFIX = ("PAPER_GUARD", "PAPER_LAB")
_ENV_INHERIT = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC",
                "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "PROGRAMFILES",
                "PYTHONIOENCODING", "PYTHONUTF8")


def build_env() -> dict[str, str]:
    env = {}
    for key, val in os.environ.items():
        upper = key.upper()
        if upper in _ENV_INHERIT or any(upper.startswith(p) for p in _ENV_ALLOW_PREFIX):
            env[key] = val
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONHASHSEED"] = "0"
    return env


def run(script: str, timeout: int, extra_args: list[str] | None = None) -> dict:
    script_path = (LAB_ROOT / script).resolve()
    cmd = [sys.executable, str(script_path), *(extra_args or [])]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, cwd=str(LAB_ROOT), env=build_env(),
            capture_output=True, text=True, timeout=timeout,
        )
        result = {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "duration_sec": round(time.perf_counter() - t0, 3),
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    except subprocess.TimeoutExpired as exc:
        result = {
            "ok": False,
            "exit_code": None,
            "duration_sec": round(time.perf_counter() - t0, 3),
            "stdout_tail": (exc.stdout or b"")[-2000:] if isinstance(exc.stdout, bytes)
                          else str(exc.stdout or "")[-2000:],
            "stderr_tail": f"TIMEOUT after {timeout}s",
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--arg", action="append", default=[],
                        help="透传给脚本的额外参数（可多次）")
    args = parser.parse_args()
    result = run(args.script, args.timeout, args.arg)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
"""Controlled Blender subprocess launcher with timeout, cancellation, and progress streaming.

Never imports `bpy` in the web backend process. Supports both:
1. Standalone `blender` executable (`BLENDER_EXECUTABLE` or `blender` on PATH)
2. Isolated Blender 4.2 LTS Python runtime (`BLENDER_PYTHON_EXECUTABLE`)
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import resource
import shutil
import signal
import subprocess
from collections.abc import Callable
from typing import Any

from backend.config import REPO_ROOT, Settings, get_settings

RUNNER_SCRIPT = REPO_ROOT / "backend" / "blender" / "runner.py"
PROGRESS_PREFIX = "STUDIO_PROGRESS:"
PROBE_MARKER = "STUDIO_CAPABILITIES_JSON:"


def resolve_blender_command(
    script_path: pathlib.Path,
    script_args: list[str],
    settings: Settings | None = None,
) -> tuple[list[str], dict[str, str], str]:
    """Return `(argv, env, mode_label)` for launching a script in Blender's runtime."""
    cfg = settings or get_settings()
    env = os.environ.copy()
    existing_py_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{REPO_ROOT}:{existing_py_path}" if existing_py_path else str(REPO_ROOT)

    headless_libs = pathlib.Path(cfg.blender_headless_libs)
    if headless_libs.exists():
        ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{headless_libs}:{ld}" if ld else str(headless_libs)

    # 1. Check explicit or PATH standalone Blender binary
    blender_bin = cfg.blender_executable.strip() or (shutil.which("blender") or "")
    if blender_bin and pathlib.Path(blender_bin).exists():
        cmd = [
            blender_bin,
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            str(script_path),
            "--",
            *script_args,
        ]
        return cmd, env, f"blender_cli:{blender_bin}"

    # 2. Isolated Blender Python runtime (`bpy` 4.2 LTS)
    py_bin = pathlib.Path(cfg.blender_python_executable)
    if py_bin.exists():
        cmd = [str(py_bin), str(script_path), *script_args]
        return cmd, env, f"blender_python_runtime:{py_bin}"

    raise RuntimeError(
        f"No Blender runtime found (checked BLENDER_EXECUTABLE={cfg.blender_executable!r} "
        f"and BLENDER_PYTHON_EXECUTABLE={cfg.blender_python_executable!r}). "
        "Run `python scripts/setup_blender_runtime.py` or install Blender 4.2 LTS."
    )


def _preexec_limits(cpu_seconds: int) -> Callable[[], None]:
    def _apply() -> None:
        os.setsid()
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 15))
        except Exception:
            pass

    return _apply


def run_blender_json_probe(settings: Settings | None = None) -> tuple[bool, Any, str | None]:
    """Run a fast synchronous capability probe inside Blender's Python runtime."""
    cfg = settings or get_settings()
    try:
        cmd, env, _ = resolve_blender_command(RUNNER_SCRIPT, ["--probe-capabilities"], cfg)
    except RuntimeError as exc:
        return False, None, str(exc)

    try:
        proc = subprocess.run(
            cmd,
            env=env,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        return False, None, str(exc)

    for line in proc.stdout.splitlines():
        if line.startswith(PROBE_MARKER):
            raw = line[len(PROBE_MARKER) :].strip()
            try:
                return True, json.loads(raw), None
            except json.JSONDecodeError as exc:
                return False, None, f"Invalid probe JSON: {exc}"

    err_tail = (proc.stderr or proc.stdout).strip()[-400:]
    return False, None, f"Blender probe exited with {proc.returncode}: {err_tail}"


async def run_blender_generation_job(
    job_config_path: pathlib.Path,
    output_dir: pathlib.Path,
    on_progress: Callable[[str, int, str], None] | None = None,
    cancel_event: asyncio.Event | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Execute a Blender asset generation job asynchronously in a bounded process group."""
    cfg = settings or get_settings()
    cmd, env, runtime_label = resolve_blender_command(
        RUNNER_SCRIPT,
        ["--config", str(job_config_path), "--output-dir", str(output_dir)],
        cfg,
    )

    cpu_limit = max(30, cfg.job_timeout_seconds)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(REPO_ROOT),
        env=env,
        preexec_fn=_preexec_limits(cpu_limit),
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    async def _read_stdout() -> None:
        assert proc.stdout is not None
        while True:
            raw_line = await proc.stdout.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            stdout_lines.append(line)
            if line.startswith(PROGRESS_PREFIX) and on_progress is not None:
                try:
                    data = json.loads(line[len(PROGRESS_PREFIX) :])
                    on_progress(
                        str(data.get("stage", "generating")),
                        int(data.get("pct", 50)),
                        str(data.get("message", "")),
                    )
                except Exception:
                    pass

    async def _read_stderr() -> None:
        assert proc.stderr is not None
        while True:
            raw_line = await proc.stderr.readline()
            if not raw_line:
                break
            stderr_lines.append(raw_line.decode("utf-8", errors="replace").rstrip())

    async def _watch_cancel() -> None:
        if cancel_event is None:
            return
        await cancel_event.wait()
        if proc.returncode is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass

    readers = asyncio.gather(_read_stdout(), _read_stderr())
    cancel_task = asyncio.create_task(_watch_cancel())

    try:
        await asyncio.wait_for(proc.wait(), timeout=cfg.job_timeout_seconds)
        await asyncio.wait_for(readers, timeout=5.0)
    except TimeoutError as exc:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        raise TimeoutError(
            f"Blender generation job timed out after {cfg.job_timeout_seconds} seconds."
        ) from exc
    finally:
        cancel_task.cancel()

    if cancel_event is not None and cancel_event.is_set():
        raise asyncio.CancelledError("Generation job was cancelled by user.")

    result_json_path = output_dir / "blender_result.json"
    if proc.returncode != 0 or not result_json_path.exists():
        combined_err = "\n".join(stderr_lines[-25:] + stdout_lines[-25:]).strip()
        # Check if runner wrote structured error details
        if result_json_path.exists():
            try:
                err_payload = json.loads(result_json_path.read_text(encoding="utf-8"))
                if err_payload.get("error"):
                    raise RuntimeError(err_payload["error"])
            except json.JSONDecodeError:
                pass
        raise RuntimeError(
            f"Blender process failed (exit={proc.returncode}, runtime={runtime_label}): {combined_err[-800:]}"
        )

    payload = json.loads(result_json_path.read_text(encoding="utf-8"))
    if not payload.get("success"):
        raise RuntimeError(payload.get("error", "Blender runner reported unsuccessful generation."))
    payload["runtime_label"] = runtime_label
    return payload

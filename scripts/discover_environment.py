#!/usr/bin/env python3
"""Discover basic editing capabilities without installing or changing anything."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

COMMANDS = {
    "ffmpeg": ["ffmpeg", "-version"],
    "ffprobe": ["ffprobe", "-version"],
    "git": ["git", "--version"],
    "python": [sys.executable, "--version"],
    "blender": ["blender", "--version"],
}


def run_version(command: list[str], timeout: float = 3.0) -> dict[str, Any]:
    """Run a low-impact version check; absence/failure is never treated as available."""
    executable = shutil.which(command[0])
    if not executable:
        return {"status": "unavailable", "executable": None, "version": None}
    try:
        result = subprocess.run(
            [executable, *command[1:]], capture_output=True, text=True,
            timeout=timeout, check=False
        )
        combined = (result.stdout or result.stderr).strip().splitlines()
        version = combined[0][:240] if combined else None
        return {
            "status": "available" if result.returncode == 0 else "detected_unverified",
            "executable": executable,
            "version": version,
            "exit_code": result.returncode,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "detected_unverified", "executable": executable,
            "version": None, "note": type(exc).__name__
        }



# Detect GUI editors by path only. Never launch a GUI application just to inspect it.
GUI_EDITORS = {
    "davinci_resolve": ["resolve", "Resolve"],
    "premiere_pro": ["premiere", "Adobe Premiere Pro"],
    "audacity": ["audacity", "Audacity"],
}


def detect_gui_editors() -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for name, candidates in GUI_EDITORS.items():
        executable = None
        for candidate in candidates:
            executable = shutil.which(candidate)
            if executable:
                break
        found[name] = {
            "status": "detected_unverified" if executable else "unavailable",
            "executable": executable,
            "note": "Detected by path only; not launched or tested.",
        }
    return found


def runtime_kind() -> str:
    markers = (
        "CODESPACES", "GITHUB_ACTIONS", "CI", "KUBERNETES_SERVICE_HOST",
        "AWS_LAMBDA_FUNCTION_NAME", "CLOUD_RUN_JOB", "REPL_ID",
    )
    if any(os.environ.get(marker) for marker in markers):
        return "likely_cloud_or_ci"
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT"):
        return "remote_ssh"
    return "local_or_unknown"


def disk_info(path: str | None = None) -> dict[str, Any]:
    target = Path(path or Path.cwd()).expanduser()
    try:
        usage = shutil.disk_usage(target)
        return {"path": str(target.resolve()), "total_bytes": usage.total, "free_bytes": usage.free}
    except OSError as exc:
        return {"path": str(target), "status": "unavailable", "note": type(exc).__name__}


def discover() -> dict[str, Any]:
    tools = {name: run_version(command) for name, command in COMMANDS.items()}
    try:
        import importlib.util
        modules = {
            name: importlib.util.find_spec(name) is not None
            for name in ("cv2", "PIL", "moviepy", "numpy", "torch", "av")
        }
    except (ImportError, ValueError):
        modules = {}
    return {
        "schema_version": "1.0",
        "runtime": {
            "os": platform.system(), "os_release": platform.release(),
            "architecture": platform.machine(), "python_version": platform.python_version(),
            "python_executable": sys.executable, "kind": runtime_kind(),
            "cwd": str(Path.cwd()),
        },
        "resources": {"disk": disk_info()},
        "tools": tools,
        "gui_editors": detect_gui_editors(),
        "python_modules": modules,
        "limits": {
            "network_access": "not_tested", "gpu": "not_tested",
            "ai_skills": "host_discovery_required", "editor_api_access": "not_tested",
            "credentials": "not_inspected",
        },
        "notes": [
            "This scan does not install software or change system settings.",
            "An executable being detected does not prove it can edit a particular project.",
            "AI skills, connected APIs, permissions, network access, and GPU availability must be checked using the host's supported mechanisms.",
            "Credential values are deliberately never inspected or displayed.",
        ],
    }


def main() -> int:
    if len(sys.argv) > 2 or (len(sys.argv) == 2 and sys.argv[1] != "--pretty"):
        print("Usage: python scripts/discover_environment.py [--pretty]", file=sys.stderr)
        return 2
    print(json.dumps(discover(), indent=2 if len(sys.argv) == 2 else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

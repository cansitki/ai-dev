#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/can-ops-refresh"
STATUS_PATH = STATE_DIR / "status.json"
HISTORY_PATH = STATE_DIR / "history.jsonl"
LOCK_PATH = STATE_DIR / "refresh.lock"
BRIEF_STATUS_PATH = HOME / ".local/state/can-ops-brief/status.json"
BRIEF_MD_PATH = HOME / ".local/state/can-ops-brief/brief.md"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def run(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    if not shutil.which(args[0]):
        return subprocess.CompletedProcess(args, 127, "", f"command not found: {args[0]}")
    try:
        return subprocess.run(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return subprocess.CompletedProcess(args, 124, stdout, stderr or f"timed out after {timeout}s")
    except Exception as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


def command_result(proc: subprocess.CompletedProcess[str], started_at: float, finished_at: float) -> dict[str, Any]:
    return {
        "command": " ".join(str(part) for part in proc.args),
        "returncode": proc.returncode,
        "duration_seconds": round(finished_at - started_at, 3),
        "stdout_tail": (proc.stdout or "")[-500:],
        "stderr_tail": (proc.stderr or "")[-500:],
    }


def build_payload(
    *,
    result: str,
    started_at: str,
    duration_seconds: float,
    command: dict[str, Any] | None,
    note: str,
) -> dict[str, Any]:
    brief = read_json(BRIEF_STATUS_PATH)
    return {
        "schema": "can-ops-refresh.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "started_at": started_at,
        "duration_seconds": round(duration_seconds, 3),
        "note": note,
        "command": command,
        "brief": {
            "status_path": str(BRIEF_STATUS_PATH),
            "brief_path": str(BRIEF_MD_PATH),
            "result": brief.get("result", "missing") if isinstance(brief, dict) else "missing",
            "top_priority_count": len(brief.get("top_priorities", [])) if isinstance(brief, dict) else 0,
            "summary": brief.get("summary", {}) if isinstance(brief, dict) else {},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run can-ops-brief refresh with lock and persistent status")
    parser.add_argument("--timeout", type=int, default=180, help="timeout in seconds for can-ops-brief --refresh --json")
    parser.add_argument("--json", action="store_true", help="print JSON status")
    parser.add_argument("--no-history", action="store_true", help="do not append to history.jsonl")
    args = parser.parse_args()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    started_monotonic = time.monotonic()
    started_at = iso_now()

    with LOCK_PATH.open("w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            payload = build_payload(
                result="skipped",
                started_at=started_at,
                duration_seconds=time.monotonic() - started_monotonic,
                command=None,
                note="another can-ops-refresh process is already running",
            )
            write_json_atomic(STATUS_PATH, payload)
            if not args.no_history:
                append_jsonl(HISTORY_PATH, payload)
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print("Can ops refresh")
                print("Result: skipped")
                print(f"Status: {STATUS_PATH}")
            return 75

        proc_started = time.monotonic()
        proc = run(["can-ops-brief", "--refresh", "--json"], timeout=args.timeout)
        proc_finished = time.monotonic()
        result = "success" if proc.returncode == 0 else "warn" if proc.returncode == 2 else "fail"
        command = command_result(proc, proc_started, proc_finished)
        note = "refresh completed" if result in {"success", "warn"} else "refresh command failed"
        payload = build_payload(
            result=result,
            started_at=started_at,
            duration_seconds=time.monotonic() - started_monotonic,
            command=command,
            note=note,
        )
        write_json_atomic(STATUS_PATH, payload)
        if not args.no_history:
            append_jsonl(HISTORY_PATH, payload)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Can ops refresh")
        print(f"Result: {payload['result']}")
        print(f"Brief: {payload['brief']['result']} ({payload['brief']['top_priority_count']} priorities)")
        print(f"Status: {STATUS_PATH}")

    return 1 if payload["result"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())

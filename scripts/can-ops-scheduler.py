#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
STATE_DIR = HOME / ".local/state/can-ops-scheduler"
STATUS_PATH = STATE_DIR / "status.json"
HISTORY_PATH = STATE_DIR / "history.jsonl"
REFRESH_STATUS_PATH = HOME / ".local/state/can-ops-refresh/status.json"
SESSION_NAME = "can-ops-refresh-loop"
DEFAULT_INTERVAL_SECONDS = 1800
SYSTEMD_DIR = HOME / ".config/systemd/user"
SERVICE_PATH = SYSTEMD_DIR / "can-ops-refresh.service"
TIMER_PATH = SYSTEMD_DIR / "can-ops-refresh.timer"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def run(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    if not shutil.which(args[0]):
        return subprocess.CompletedProcess(args, 127, "", f"command not found: {args[0]}")
    try:
        return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except Exception as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


def tmux_has(session: str = SESSION_NAME) -> bool:
    return run(["tmux", "has-session", "-t", session], timeout=5).returncode == 0


def systemd_user_available() -> bool:
    proc = run(["systemctl", "--user", "status"], timeout=5)
    return proc.returncode == 0


def systemd_timer_active() -> bool:
    proc = run(["systemctl", "--user", "is-active", "can-ops-refresh.timer"], timeout=5)
    return proc.returncode == 0 and proc.stdout.strip() == "active"


def brief_from_refresh() -> dict[str, Any]:
    refresh = read_json(REFRESH_STATUS_PATH)
    if not isinstance(refresh, dict):
        return {"result": "missing", "top_priority_count": 0}
    brief = refresh.get("brief") if isinstance(refresh.get("brief"), dict) else {}
    return {
        "result": brief.get("result", "missing"),
        "top_priority_count": brief.get("top_priority_count", 0),
        "refresh_result": refresh.get("result", "missing"),
        "refresh_updated_at": refresh.get("updated_at", ""),
    }


def write_status(result: str, mode: str, note: str, *, interval_seconds: int | None = None) -> dict[str, Any]:
    payload = {
        "schema": "can-ops-scheduler.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "mode": mode,
        "note": note,
        "interval_seconds": interval_seconds,
        "systemd_user_available": systemd_user_available(),
        "systemd_timer_active": systemd_timer_active(),
        "tmux_session": SESSION_NAME,
        "tmux_active": tmux_has(),
        "brief": brief_from_refresh(),
        "paths": {
            "status": str(STATUS_PATH),
            "history": str(HISTORY_PATH),
            "service": str(SERVICE_PATH),
            "timer": str(TIMER_PATH),
        },
    }
    write_json_atomic(STATUS_PATH, payload)
    append_jsonl(HISTORY_PATH, payload)
    return payload


def print_status(payload: dict[str, Any], json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print("Can ops scheduler")
    print(f"Result: {payload['result']}")
    print(f"Mode: {payload['mode']}")
    print(f"Note: {payload['note']}")
    print(f"Status: {STATUS_PATH}")


def install_systemd(interval_seconds: int) -> dict[str, Any]:
    SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
    service = f"""[Unit]
Description=Refresh Can daily operations brief

[Service]
Type=oneshot
ExecStart={HOME}/.local/bin/can-ops-refresh
"""
    timer = f"""[Unit]
Description=Run Can ops refresh periodically

[Timer]
OnBootSec=2min
OnUnitActiveSec={interval_seconds}s
AccuracySec=1min
Persistent=true

[Install]
WantedBy=timers.target
"""
    SERVICE_PATH.write_text(service, encoding="utf-8")
    TIMER_PATH.write_text(timer, encoding="utf-8")

    commands = [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "can-ops-refresh.timer"],
    ]
    results = []
    for command in commands:
        proc = run(command, timeout=20)
        results.append(
            {
                "command": " ".join(command),
                "returncode": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-500:],
            }
        )
        if proc.returncode != 0:
            payload = write_status("warn", "systemd", "systemd timer unit written but activation failed", interval_seconds=interval_seconds)
            payload["command_results"] = results
            write_json_atomic(STATUS_PATH, payload)
            append_jsonl(HISTORY_PATH, payload)
            return payload

    payload = write_status("success", "systemd", "systemd timer installed and active", interval_seconds=interval_seconds)
    payload["command_results"] = results
    write_json_atomic(STATUS_PATH, payload)
    append_jsonl(HISTORY_PATH, payload)
    return payload


def start_tmux(interval_seconds: int) -> dict[str, Any]:
    if tmux_has():
        return write_status("success", "tmux", "tmux refresh loop already running", interval_seconds=interval_seconds)
    if not shutil.which("tmux"):
        return write_status("fail", "tmux", "tmux not installed and systemd user unavailable", interval_seconds=interval_seconds)

    command = (
        f"exec {HOME}/.local/bin/can-ops-scheduler "
        f"loop --interval {interval_seconds}"
    )
    proc = run(["tmux", "new-session", "-d", "-s", SESSION_NAME, command], timeout=10)
    if proc.returncode != 0:
        payload = write_status("fail", "tmux", "failed to start tmux refresh loop", interval_seconds=interval_seconds)
        payload["start_error"] = (proc.stderr or proc.stdout or "")[-500:]
        write_json_atomic(STATUS_PATH, payload)
        append_jsonl(HISTORY_PATH, payload)
        return payload
    return write_status("success", "tmux", "tmux refresh loop started", interval_seconds=interval_seconds)


def stop_scheduler() -> dict[str, Any]:
    notes: list[str] = []
    if systemd_user_available():
        proc = run(["systemctl", "--user", "disable", "--now", "can-ops-refresh.timer"], timeout=20)
        notes.append(f"systemd disable returncode={proc.returncode}")
    if tmux_has():
        proc = run(["tmux", "kill-session", "-t", SESSION_NAME], timeout=10)
        notes.append(f"tmux kill returncode={proc.returncode}")
    if not notes:
        notes.append("nothing running")
    return write_status("success", "stopped", "; ".join(notes))


def scheduler_status() -> dict[str, Any]:
    if systemd_timer_active():
        return write_status("success", "systemd", "systemd timer active")
    if tmux_has():
        return write_status("success", "tmux", "tmux refresh loop active")
    return write_status("warn", "none", "no scheduler active")


def loop(interval_seconds: int) -> int:
    write_status("success", "tmux-loop", "loop process started", interval_seconds=interval_seconds)
    while True:
        started = time.monotonic()
        proc = run(["can-ops-refresh", "--json"], timeout=max(60, min(interval_seconds, 600)))
        result = "success" if proc.returncode == 0 else "warn" if proc.returncode in {2, 75} else "fail"
        payload = write_status(
            result,
            "tmux-loop",
            f"loop iteration completed with returncode={proc.returncode}",
            interval_seconds=interval_seconds,
        )
        payload["iteration"] = {
            "duration_seconds": round(time.monotonic() - started, 3),
            "returncode": proc.returncode,
            "stderr_tail": (proc.stderr or "")[-500:],
        }
        write_json_atomic(STATUS_PATH, payload)
        append_jsonl(HISTORY_PATH, payload)
        sleep_for = max(60, interval_seconds - int(time.monotonic() - started))
        time.sleep(sleep_for)


def main() -> int:
    parser = argparse.ArgumentParser(description="Schedule can-ops-refresh through systemd user timer or tmux fallback")
    sub = parser.add_subparsers(dest="command", required=False)

    for name in ("start", "install-systemd", "start-tmux", "loop"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS)
        cmd.add_argument("--json", action="store_true")
    sub.add_parser("status").add_argument("--json", action="store_true")
    sub.add_parser("stop").add_argument("--json", action="store_true")

    args = parser.parse_args()
    command = args.command or "status"
    json_mode = bool(getattr(args, "json", False))
    interval = int(getattr(args, "interval", DEFAULT_INTERVAL_SECONDS))

    if command == "start":
        payload = install_systemd(interval) if systemd_user_available() else start_tmux(interval)
    elif command == "install-systemd":
        payload = install_systemd(interval)
    elif command == "start-tmux":
        payload = start_tmux(interval)
    elif command == "status":
        payload = scheduler_status()
    elif command == "stop":
        payload = stop_scheduler()
    elif command == "loop":
        return loop(interval)
    else:
        payload = write_status("fail", "unknown", f"unknown command: {command}", interval_seconds=interval)

    print_status(payload, json_mode)
    return 1 if payload["result"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())

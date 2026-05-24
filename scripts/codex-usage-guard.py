#!/usr/bin/env python3
"""Codex usage guard for unattended agent runs.

Reads Codex session JSONL files and enforces a local budget against the
reported weekly rate-limit percentage. This is intentionally dependency-free
so it can live in the workspace template.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BUDGET_NAME = "sleep"
WEEKLY_WINDOW_MINUTES = 10080


@dataclass
class UsageSnapshot:
    timestamp: str
    timestamp_epoch: float
    source_file: str
    line: int
    weekly_used_percent: float | None
    weekly_resets_at: int | None
    primary_used_percent: float | None
    primary_resets_at: int | None
    plan_type: str | None
    last_total_tokens: int | None
    total_tokens: int | None


def parse_timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def iso_from_epoch(value: int | float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", name.strip())
    cleaned = cleaned.strip(".-")
    if not cleaned:
        raise SystemExit("budget name cannot be empty")
    return cleaned


def codex_home_from_args(args: argparse.Namespace) -> Path:
    raw = args.codex_home or os.environ.get("CODEX_HOME") or "~/.codex"
    return Path(raw).expanduser()


def budget_path(codex_home: Path, name: str) -> Path:
    return codex_home / "budgets" / f"{sanitize_name(name)}.json"


def iter_session_files(codex_home: Path) -> list[Path]:
    sessions = codex_home / "sessions"
    if not sessions.exists():
        return []
    return sorted(sessions.rglob("*.jsonl"))


def snapshot_from_record(record: dict[str, Any], source_file: Path, line_no: int) -> UsageSnapshot | None:
    if record.get("type") != "event_msg":
        return None
    payload = record.get("payload") or {}
    if payload.get("type") != "token_count":
        return None

    rate_limits = record.get("rate_limits") or payload.get("rate_limits") or {}
    primary = rate_limits.get("primary") or {}
    secondary = rate_limits.get("secondary") or {}
    if secondary.get("window_minutes") != WEEKLY_WINDOW_MINUTES:
        secondary = {}

    info = payload.get("info") or {}
    last_usage = info.get("last_token_usage") or {}
    total_usage = info.get("total_token_usage") or {}
    timestamp = record.get("timestamp") or ""

    return UsageSnapshot(
        timestamp=timestamp,
        timestamp_epoch=parse_timestamp(timestamp),
        source_file=str(source_file),
        line=line_no,
        weekly_used_percent=safe_float(secondary.get("used_percent")),
        weekly_resets_at=secondary.get("resets_at"),
        primary_used_percent=safe_float(primary.get("used_percent")),
        primary_resets_at=primary.get("resets_at"),
        plan_type=rate_limits.get("plan_type"),
        last_total_tokens=last_usage.get("total_tokens"),
        total_tokens=total_usage.get("total_tokens"),
    )


def latest_usage(codex_home: Path) -> UsageSnapshot | None:
    latest: UsageSnapshot | None = None
    latest_with_weekly: UsageSnapshot | None = None

    for path in iter_session_files(codex_home):
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_no, line in enumerate(handle, start=1):
                    if '"token_count"' not in line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    snapshot = snapshot_from_record(record, path, line_no)
                    if snapshot is None:
                        continue
                    if latest is None or snapshot.timestamp_epoch >= latest.timestamp_epoch:
                        latest = snapshot
                    if snapshot.weekly_used_percent is not None:
                        if latest_with_weekly is None or snapshot.timestamp_epoch >= latest_with_weekly.timestamp_epoch:
                            latest_with_weekly = snapshot
        except OSError:
            continue

    return latest_with_weekly or latest


def snapshot_dict(snapshot: UsageSnapshot | None) -> dict[str, Any]:
    if snapshot is None:
        return {
            "status": "unknown",
            "reason": "no Codex token_count events found",
        }
    return {
        "status": "ok" if snapshot.weekly_used_percent is not None else "unknown",
        "timestamp": snapshot.timestamp,
        "timestamp_epoch": snapshot.timestamp_epoch,
        "source_file": snapshot.source_file,
        "line": snapshot.line,
        "weekly_used_percent": snapshot.weekly_used_percent,
        "weekly_resets_at": snapshot.weekly_resets_at,
        "weekly_resets_at_utc": iso_from_epoch(snapshot.weekly_resets_at),
        "primary_used_percent": snapshot.primary_used_percent,
        "primary_resets_at": snapshot.primary_resets_at,
        "primary_resets_at_utc": iso_from_epoch(snapshot.primary_resets_at),
        "plan_type": snapshot.plan_type,
        "last_total_tokens": snapshot.last_total_tokens,
        "total_tokens": snapshot.total_tokens,
        "age_seconds": max(0, int(time.time() - snapshot.timestamp_epoch)) if snapshot.timestamp_epoch else None,
    }


def print_status(data: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(data, indent=2, sort_keys=True))
        return

    if data.get("status") == "unknown":
        print(f"UNKNOWN {data.get('reason', 'no weekly rate limit found')}")
        return

    weekly = data.get("weekly_used_percent")
    primary = data.get("primary_used_percent")
    weekly_reset = data.get("weekly_resets_at_utc") or "unknown"
    primary_reset = data.get("primary_resets_at_utc") or "unknown"
    print(
        f"Codex usage: weekly={weekly}% reset={weekly_reset} "
        f"primary={primary}% reset={primary_reset} plan={data.get('plan_type') or 'unknown'}"
    )


def command_status(args: argparse.Namespace) -> int:
    data = snapshot_dict(latest_usage(codex_home_from_args(args)))
    print_status(data, args.format)
    return 0


def command_start(args: argparse.Namespace) -> int:
    codex_home = codex_home_from_args(args)
    snapshot = latest_usage(codex_home)
    if snapshot is None or snapshot.weekly_used_percent is None:
        print("Cannot start budget: no Codex weekly usage snapshot found.", file=sys.stderr)
        return 3

    baseline = snapshot.weekly_used_percent
    target_cap = baseline + args.max_weekly_delta_percent
    if args.absolute_weekly_cap_percent is not None:
        target_cap = min(target_cap, args.absolute_weekly_cap_percent)
    if args.hard_weekly_cap_percent is not None:
        target_cap = min(target_cap, args.hard_weekly_cap_percent)

    stop_at = max(baseline, target_cap - args.reserve_percent_points)
    state = {
        "name": sanitize_name(args.name),
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "codex_home": str(codex_home),
        "baseline_weekly_used_percent": baseline,
        "max_weekly_delta_percent": args.max_weekly_delta_percent,
        "absolute_weekly_cap_percent": args.absolute_weekly_cap_percent,
        "hard_weekly_cap_percent": args.hard_weekly_cap_percent,
        "reserve_percent_points": args.reserve_percent_points,
        "target_weekly_cap_percent": round(target_cap, 4),
        "stop_at_weekly_used_percent": round(stop_at, 4),
        "baseline_snapshot": snapshot_dict(snapshot),
    }

    path = budget_path(codex_home, args.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.format == "json":
        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        print(
            f"Started Codex budget '{state['name']}': baseline={baseline}% "
            f"target={state['target_weekly_cap_percent']}% stop_at={state['stop_at_weekly_used_percent']}%"
        )
    return 0


def load_budget(codex_home: Path, name: str) -> dict[str, Any]:
    path = budget_path(codex_home, name)
    if not path.exists():
        raise SystemExit(f"budget '{sanitize_name(name)}' does not exist at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def command_check(args: argparse.Namespace) -> int:
    codex_home = codex_home_from_args(args)
    snapshot = latest_usage(codex_home)
    current = snapshot.weekly_used_percent if snapshot else None
    now_data = snapshot_dict(snapshot)

    if current is None:
        result = {
            "decision": "stop",
            "reason": "no current weekly usage snapshot",
            "current_snapshot": now_data,
        }
        if args.format == "json":
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("STOP no current Codex weekly usage snapshot")
        return 3

    if args.max_data_age_seconds:
        age = now_data.get("age_seconds")
        if age is None or age > args.max_data_age_seconds:
            result = {
                "decision": "stop",
                "reason": "usage snapshot is stale",
                "max_data_age_seconds": args.max_data_age_seconds,
                "current_snapshot": now_data,
            }
            if args.format == "json":
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"STOP Codex usage snapshot stale: age={age}s max={args.max_data_age_seconds}s")
            return 3

    budget = None
    stop_at = args.max_weekly_percent
    if args.name:
        budget = load_budget(codex_home, args.name)
        stop_at = safe_float(budget.get("stop_at_weekly_used_percent"))
    if stop_at is None:
        raise SystemExit("provide --name or --max-weekly-percent")

    remaining = stop_at - current
    decision = "ok" if current < stop_at else "stop"
    result = {
        "decision": decision,
        "current_weekly_used_percent": current,
        "stop_at_weekly_used_percent": stop_at,
        "remaining_percent_points": round(remaining, 4),
        "budget": budget,
        "current_snapshot": now_data,
    }

    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    elif decision == "ok":
        print(f"OK Codex weekly={current}% stop_at={stop_at}% remaining={round(remaining, 4)}pp")
    else:
        print(f"STOP Codex weekly={current}% stop_at={stop_at}% budget exhausted")

    return 0 if decision == "ok" else 2


def command_run(args: argparse.Namespace) -> int:
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("provide a command after --")

    check_args = argparse.Namespace(
        codex_home=args.codex_home,
        format=args.format,
        name=args.name,
        max_weekly_percent=args.max_weekly_percent,
        max_data_age_seconds=args.max_data_age_seconds,
    )
    check_result = command_check(check_args)
    if check_result != 0:
        return check_result

    sys.stdout.flush()
    completed = subprocess.run(command, check=False)
    return completed.returncode


def command_clear(args: argparse.Namespace) -> int:
    path = budget_path(codex_home_from_args(args), args.name)
    if path.exists():
        path.unlink()
        print(f"Cleared Codex budget '{sanitize_name(args.name)}'.")
    else:
        print(f"Codex budget '{sanitize_name(args.name)}' was not present.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guard unattended Codex runs against weekly usage limits.")
    parser.add_argument("--codex-home", help="Codex home directory. Defaults to CODEX_HOME or ~/.codex.")
    parser.add_argument("--format", choices=["text", "json"], default="text")

    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Show the latest Codex usage snapshot.")
    status.add_argument("--format", choices=["text", "json"], default=argparse.SUPPRESS)
    status.set_defaults(func=command_status)

    start = subparsers.add_parser("start", help="Start a named budget from the current weekly usage baseline.")
    start.add_argument("--format", choices=["text", "json"], default=argparse.SUPPRESS)
    start.add_argument("--name", default=DEFAULT_BUDGET_NAME)
    start.add_argument("--max-weekly-delta-percent", type=float, default=10.0)
    start.add_argument("--absolute-weekly-cap-percent", type=float)
    start.add_argument("--hard-weekly-cap-percent", type=float, default=95.0)
    start.add_argument("--reserve-percent-points", type=float, default=1.0)
    start.set_defaults(func=command_start)

    check = subparsers.add_parser("check", help="Return non-zero when a budget is exhausted.")
    check.add_argument("--format", choices=["text", "json"], default=argparse.SUPPRESS)
    check.add_argument("--name")
    check.add_argument("--max-weekly-percent", type=float)
    check.add_argument("--max-data-age-seconds", type=int)
    check.set_defaults(func=command_check)

    run = subparsers.add_parser("run", help="Run a command only when the budget check passes.")
    run.add_argument("--format", choices=["text", "json"], default=argparse.SUPPRESS)
    run.add_argument("--name")
    run.add_argument("--max-weekly-percent", type=float)
    run.add_argument("--max-data-age-seconds", type=int)
    run.add_argument("command", nargs=argparse.REMAINDER)
    run.set_defaults(func=command_run)

    clear = subparsers.add_parser("clear", help="Remove a named budget.")
    clear.add_argument("--format", choices=["text", "json"], default=argparse.SUPPRESS)
    clear.add_argument("--name", default=DEFAULT_BUDGET_NAME)
    clear.set_defaults(func=command_clear)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

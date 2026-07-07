#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/control-plane-runtime-dashboard"
STATUS_PATH = STATE_DIR / "status.json"
DASHBOARD_PATH = STATE_DIR / "dashboard.md"
TMUX_INVENTORY_PATH = Path(
    os.environ.get("CONTROL_PLANE_TMUX_INVENTORY")
    or HOME / ".local/state/can-doctor/tmux-inventory.json"
)
CAN_DOCTOR_STATUS_PATH = Path(
    os.environ.get("CONTROL_PLANE_CAN_DOCTOR_STATUS")
    or HOME / ".local/state/can-doctor/status.json"
)
BACKUP_READINESS_STATUS_PATH = Path(
    os.environ.get("CONTROL_PLANE_BACKUP_READINESS_STATUS")
    or HOME / ".local/state/control-plane-backup-readiness/status.json"
)
RESTIC_BACKUP_STATUS_PATH = Path(
    os.environ.get("CONTROL_PLANE_RESTIC_BACKUP_STATUS")
    or HOME / ".local/state/control-plane-restic-backup/status.json"
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def age_hours(value: Any) -> float | None:
    parsed = parse_time(value)
    if parsed is None:
        return None
    return max(0.0, (utc_now() - parsed).total_seconds() / 3600)


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


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def safe_text(value: Any) -> str:
    text = str(value or "")
    return text.replace("|", "\\|").replace("\n", " ").strip()


def tmux_group(name: str) -> str:
    lowered = name.lower()
    for prefix in ("clore-", "salad-", "provider-"):
        if lowered.startswith(prefix):
            return prefix.rstrip("-")
    if lowered.startswith("prlcompute"):
        return "prlcompute"
    return "other-provider"


def provider_groups(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for session in sessions:
        if session.get("category") != "provider_worker":
            continue
        grouped.setdefault(tmux_group(str(session.get("name") or "")), []).append(session)

    groups = []
    for group, items in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        attached = sum(1 for item in items if int(item.get("attached") or 0) > 0)
        oldest = max((float(item.get("age_days") or 0) for item in items), default=0.0)
        groups.append(
            {
                "group": group,
                "count": len(items),
                "attached": attached,
                "oldest_age_days": round(oldest, 1),
                "samples": [str(item.get("name") or "") for item in items[:8]],
            }
        )
    return groups


def check_summary(status: dict[str, Any] | None, *, category: str | None = None) -> dict[str, Any]:
    if not isinstance(status, dict):
        return {"result": "missing", "warnings": 0, "failures": 0, "checks": []}
    checks = status.get("checks") if isinstance(status.get("checks"), list) else []
    if category:
        checks = [check for check in checks if isinstance(check, dict) and check.get("category") == category]
    return {
        "result": status.get("result", "unknown"),
        "warnings": sum(1 for check in checks if isinstance(check, dict) and check.get("status") == "warn"),
        "failures": sum(1 for check in checks if isinstance(check, dict) and check.get("status") == "fail"),
        "checks": checks,
    }


def backup_gate_summary(readiness: Any, restic: Any) -> dict[str, Any]:
    readiness_blockers = readiness.get("blockers") if isinstance(readiness, dict) else []
    restic_blockers = restic.get("blockers") if isinstance(restic, dict) else []
    return {
        "readiness_result": readiness.get("result", "missing") if isinstance(readiness, dict) else "missing",
        "readiness_blockers": readiness_blockers if isinstance(readiness_blockers, list) else [],
        "restic_result": restic.get("result", "missing") if isinstance(restic, dict) else "missing",
        "restic_blockers": restic_blockers if isinstance(restic_blockers, list) else [],
    }


def build_payload() -> dict[str, Any]:
    warnings: list[str] = []
    blockers: list[str] = []
    inventory = read_json(TMUX_INVENTORY_PATH)
    can_doctor = read_json(CAN_DOCTOR_STATUS_PATH)
    readiness = read_json(BACKUP_READINESS_STATUS_PATH)
    restic = read_json(RESTIC_BACKUP_STATUS_PATH)

    if not isinstance(inventory, dict):
        blockers.append(f"tmux inventory missing or invalid: {TMUX_INVENTORY_PATH}")
        sessions: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
    else:
        sessions = [item for item in inventory.get("sessions", []) if isinstance(item, dict)]
        counts = inventory.get("counts") if isinstance(inventory.get("counts"), dict) else {}
        age = age_hours(inventory.get("updated_at"))
        if age is None:
            warnings.append("tmux inventory has no valid updated_at")
        elif age > 2:
            warnings.append(f"tmux inventory is stale: {age:.1f}h old")

    cleanup = inventory.get("cleanup_candidates") if isinstance(inventory, dict) else []
    cleanup = [item for item in cleanup if isinstance(item, dict)]
    missing_expected = inventory.get("missing_expected") if isinstance(inventory, dict) else []
    missing_expected = [str(item) for item in missing_expected or []]
    if missing_expected:
        warnings.append(f"missing expected tmux sessions: {', '.join(missing_expected)}")
    if cleanup:
        warnings.append(f"{len(cleanup)} tmux cleanup candidates need review")

    runtime = check_summary(can_doctor if isinstance(can_doctor, dict) else None, category="runtime")
    backup = check_summary(can_doctor if isinstance(can_doctor, dict) else None, category="backup")
    migration = check_summary(can_doctor if isinstance(can_doctor, dict) else None, category="migration")
    gates = backup_gate_summary(readiness, restic)
    if gates["readiness_blockers"]:
        warnings.append(f"backup readiness blockers: {len(gates['readiness_blockers'])}")
    if gates["restic_blockers"]:
        warnings.append(f"restic backup blockers: {len(gates['restic_blockers'])}")
    if migration["warnings"] or migration["failures"]:
        warnings.append("migration warnings present in can-doctor")

    critical_sessions = [item for item in sessions if item.get("category") == "critical"]
    provider_sessions = [item for item in sessions if item.get("category") == "provider_worker"]
    result = "blocked" if blockers else "warn" if warnings else "ok"

    return {
        "schema": "control-plane-runtime-dashboard.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "blockers": blockers,
        "warnings": warnings,
        "paths": {
            "status": str(STATUS_PATH),
            "dashboard": str(DASHBOARD_PATH),
            "tmux_inventory": str(TMUX_INVENTORY_PATH),
            "can_doctor_status": str(CAN_DOCTOR_STATUS_PATH),
        },
        "tmux": {
            "total": len(sessions),
            "counts": counts,
            "missing_expected": missing_expected,
            "cleanup_candidate_count": len(cleanup),
            "critical_count": len(critical_sessions),
            "provider_worker_count": len(provider_sessions),
            "provider_groups": provider_groups(sessions),
            "cleanup_candidates": cleanup[:25],
            "critical_sessions": critical_sessions,
        },
        "can_doctor": {
            "result": can_doctor.get("result", "missing") if isinstance(can_doctor, dict) else "missing",
            "runtime": {k: v for k, v in runtime.items() if k != "checks"},
            "backup": {k: v for k, v in backup.items() if k != "checks"},
            "migration": {k: v for k, v in migration.items() if k != "checks"},
        },
        "backup_gates": gates,
        "next_actions": build_next_actions(missing_expected, cleanup, gates, migration),
    }


def build_next_actions(
    missing_expected: list[str],
    cleanup: list[dict[str, Any]],
    gates: dict[str, Any],
    migration: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    if gates["restic_blockers"]:
        actions.append("Provide scoped R2/restic credentials and run control-plane-restic-backup --init --dry-run.")
    if gates["readiness_blockers"]:
        actions.append("Resolve control-plane-backup-readiness blockers before migration.")
    if cleanup:
        actions.append("Review tmux cleanup candidates before copying runtime state to Hetzner.")
    if migration["warnings"] or migration["failures"]:
        checks = migration.get("checks") if isinstance(migration.get("checks"), list) else []
        labels = {str(check.get("label", "")) for check in checks if isinstance(check, dict) and check.get("status") in {"warn", "fail"}}
        if "Hetzner hardening preflight" in labels:
            actions.append("Harden Hetzner: create a non-root sudo admin, activate firewall policy, and review exposed mail/service ports before cutover.")
        elif "Hetzner SSH" in labels or "Hetzner access preflight" in labels:
            actions.append("Fix Hetzner SSH/access warning before moving the daily control plane.")
        else:
            actions.append("Review can-doctor migration warnings before moving the daily control plane.")
    if not actions:
        actions.append("Run can-doctor and a restore drill before changing migration status.")
    return actions


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Control Plane Runtime Dashboard",
        "",
        "No secret values are read or printed. This dashboard is built from status JSON and tmux metadata only.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Blockers: {len(payload['blockers'])}",
        f"- Warnings: {len(payload['warnings'])}",
        "",
    ]

    if payload["blockers"]:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {item}" for item in payload["blockers"])
        lines.append("")

    if payload["warnings"]:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {item}" for item in payload["warnings"])
        lines.append("")

    tmux = payload["tmux"]
    lines.extend(
        [
            "## Tmux Summary",
            "",
            f"- Total sessions: {tmux['total']}",
            f"- Critical sessions: {tmux['critical_count']}",
            f"- Provider/worker sessions: {tmux['provider_worker_count']}",
            f"- Cleanup candidates: {tmux['cleanup_candidate_count']}",
            f"- Missing expected: {', '.join(tmux['missing_expected']) or 'none'}",
            "",
            "### Counts",
            "",
            "| Category | Count |",
            "|---|---:|",
        ]
    )
    for category, count in sorted(tmux["counts"].items()):
        lines.append(f"| `{safe_text(category)}` | {count} |")

    lines.extend(["", "### Provider Groups", "", "| Group | Count | Attached | Oldest Days | Samples |", "|---|---:|---:|---:|---|"])
    for group in tmux["provider_groups"]:
        samples = ", ".join(f"`{safe_text(name)}`" for name in group["samples"])
        lines.append(
            f"| `{safe_text(group['group'])}` | {group['count']} | {group['attached']} | {group['oldest_age_days']} | {samples} |"
        )

    lines.extend(["", "### Cleanup Candidates", "", "| Session | Age Days | Command | Path |", "|---|---:|---|---|"])
    for item in tmux["cleanup_candidates"]:
        lines.append(
            f"| `{safe_text(item.get('name'))}` | {item.get('age_days') or ''} | `{safe_text(item.get('command'))}` | `{safe_text(item.get('path'))}` |"
        )
    if not tmux["cleanup_candidates"]:
        lines.append("| none |  |  |  |")

    lines.extend(["", "## Backup And Migration Gates", ""])
    gates = payload["backup_gates"]
    lines.extend(
        [
            f"- Backup readiness: `{gates['readiness_result']}` ({len(gates['readiness_blockers'])} blocker(s))",
            f"- Restic backup: `{gates['restic_result']}` ({len(gates['restic_blockers'])} blocker(s))",
            f"- Can-doctor migration warnings: {payload['can_doctor']['migration']['warnings']}",
            "",
            "## Next Actions",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in payload["next_actions"])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a no-secret runtime dashboard for the control plane")
    parser.add_argument("--json", action="store_true", help="print JSON payload")
    args = parser.parse_args()

    payload = build_payload()
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(DASHBOARD_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Control-plane runtime dashboard")
        print(f"Result: {payload['result']}")
        print(f"Tmux sessions: {payload['tmux']['total']}")
        print(f"Provider/worker sessions: {payload['tmux']['provider_worker_count']}")
        print(f"Cleanup candidates: {payload['tmux']['cleanup_candidate_count']}")
        print(f"Status: {STATUS_PATH}")
        print(f"Dashboard: {DASHBOARD_PATH}")

    return 2 if payload["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-daily-ops-snapshot"
STATUS_PATH = STATE_DIR / "snapshot.json"
REPORT_PATH = STATE_DIR / "snapshot.md"

P0_BOARD = HOME / ".local/state/nomarh-p0-execution-board/board.json"
READINESS = HOME / ".local/state/nomarh-migration-readiness/readiness.json"
SERVICE_MAP = HOME / ".local/state/nomarh-service-migration-map/map.json"
CAN_OPS_BRIEF = HOME / ".local/state/can-ops-brief/status.json"
CAN_DOCTOR = HOME / ".local/state/can-doctor/status.json"
TMUX_CLEANUP = HOME / ".local/state/tmux-cleanup-review/status.json"
R2_RESTIC_INTAKE = HOME / ".local/state/control-plane-r2-restic-intake/status.json"
R2_RESTIC_BOOTSTRAP = HOME / ".local/state/control-plane-r2-restic-bootstrap/status.json"
RESTORE_DRILL = HOME / ".local/state/control-plane-restic-restore-drill/status.json"


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


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def first_action(p0: Any) -> dict[str, Any]:
    if not isinstance(p0, dict):
        return {
            "title": "Run P0 execution board",
            "status": "missing",
            "lane": "setup",
            "next_action": "Run `nomarh-p0-execution-board --json`.",
            "verify": "nomarh-p0-execution-board --json",
        }
    tasks = p0.get("next_tasks") if isinstance(p0.get("next_tasks"), list) else []
    if not tasks:
        return {
            "title": "No P0 task generated",
            "status": "ready",
            "lane": "none",
            "next_action": "Review readiness manually before cutover.",
            "verify": "nomarh-migration-readiness --refresh",
        }
    task = tasks[0] if isinstance(tasks[0], dict) else {}
    return {
        "title": str(task.get("title", "unknown")),
        "status": str(task.get("status", "unknown")),
        "lane": str(task.get("lane", "unknown")),
        "next_action": str(task.get("next_action", "")),
        "verify": str(task.get("verify", "")),
    }


def warning_checks(can_doctor: Any) -> list[dict[str, str]]:
    if not isinstance(can_doctor, dict):
        return []
    checks = can_doctor.get("checks") if isinstance(can_doctor.get("checks"), list) else []
    result = []
    for check in checks:
        if not isinstance(check, dict) or check.get("status") == "ok":
            continue
        result.append(
            {
                "category": str(check.get("category", "")),
                "label": str(check.get("label", "")),
                "status": str(check.get("status", "")),
                "detail": str(check.get("detail", "")),
            }
        )
    return result


def build_payload() -> dict[str, Any]:
    p0 = read_json(P0_BOARD)
    readiness = read_json(READINESS)
    service_map = read_json(SERVICE_MAP)
    brief = read_json(CAN_OPS_BRIEF)
    doctor = read_json(CAN_DOCTOR)
    tmux_cleanup = read_json(TMUX_CLEANUP)
    intake = read_json(R2_RESTIC_INTAKE)
    bootstrap = read_json(R2_RESTIC_BOOTSTRAP)
    restore = read_json(RESTORE_DRILL)

    p0_summary = p0.get("summary") if isinstance(p0, dict) and isinstance(p0.get("summary"), dict) else {}
    readiness_summary = readiness.get("summary") if isinstance(readiness, dict) and isinstance(readiness.get("summary"), dict) else {}
    service_summary = service_map.get("summary") if isinstance(service_map, dict) and isinstance(service_map.get("summary"), dict) else {}
    brief_summary = brief.get("summary") if isinstance(brief, dict) and isinstance(brief.get("summary"), dict) else {}

    result = "blocked"
    if isinstance(p0, dict):
        result = "blocked" if p0.get("result") == "blocked" else "warn" if p0.get("result") == "warn" else "ready"

    first = first_action(p0)
    do_not = []
    if result == "blocked":
        do_not.append("Do not cut over AWS/main runtime to Hetzner yet.")
        do_not.append("Do not decommission AWS/main yet.")
    if first["lane"] == "backup":
        do_not.append("Do not start service migration before backup/restore proof exists.")

    top_priorities = brief.get("top_priorities") if isinstance(brief, dict) and isinstance(brief.get("top_priorities"), list) else []
    payload = {
        "schema": "nomarh-daily-ops-snapshot.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "today": {
            "do_first": first,
            "do_not": do_not,
            "verify_after_change": [
                "can-ops-refresh --json",
                "control-plane-r2-restic-intake --json",
                "control-plane-r2-restic-bootstrap --json",
                "nomarh-p0-execution-board --json",
                "nomarh-migration-readiness --json",
            ],
        },
        "status": {
            "p0": {
                "result": p0.get("result", "missing") if isinstance(p0, dict) else "missing",
                "counts": p0_summary.get("counts", {}),
                "task_count": p0_summary.get("task_count", "?"),
            },
            "readiness": {
                "result": readiness.get("result", "missing") if isinstance(readiness, dict) else "missing",
                "ready": readiness_summary.get("ready", "?"),
                "warn": readiness_summary.get("warn", "?"),
                "blocked": readiness_summary.get("blocked", "?"),
            },
            "service_map": {
                "result": service_map.get("result", "missing") if isinstance(service_map, dict) else "missing",
                "priority": service_summary.get("by_priority", {}),
                "risk": service_summary.get("by_risk", {}),
            },
            "brief": {
                "result": brief.get("result", "missing") if isinstance(brief, dict) else "missing",
                "summary": brief_summary,
                "top_priorities": [str(item) for item in top_priorities[:6]],
            },
            "restore_drill": {
                "result": restore.get("result", "missing") if isinstance(restore, dict) else "missing",
                "blocker_count": len(restore.get("blockers", [])) if isinstance(restore, dict) and isinstance(restore.get("blockers"), list) else "?",
            },
            "r2_restic_intake": {
                "result": intake.get("result", "missing") if isinstance(intake, dict) else "missing",
                "blocker_count": len(intake.get("blockers", [])) if isinstance(intake, dict) and isinstance(intake.get("blockers"), list) else "?",
                "input_groups": (
                    f"{intake.get('summary', {}).get('present_required_input_groups', 0)}/{intake.get('summary', {}).get('required_input_groups', 0)}"
                    if isinstance(intake, dict) and isinstance(intake.get("summary"), dict)
                    else "?"
                ),
            },
            "r2_restic_bootstrap": {
                "result": bootstrap.get("result", "missing") if isinstance(bootstrap, dict) else "missing",
                "blocker_count": len(bootstrap.get("blockers", [])) if isinstance(bootstrap, dict) and isinstance(bootstrap.get("blockers"), list) else "?",
            },
            "doctor": {
                "result": doctor.get("result", "missing") if isinstance(doctor, dict) else "missing",
                "warnings": doctor.get("warnings", "?") if isinstance(doctor, dict) else "?",
                "warning_checks": warning_checks(doctor)[:10],
            },
            "tmux_cleanup": {
                "result": tmux_cleanup.get("result", "missing") if isinstance(tmux_cleanup, dict) else "missing",
                "candidate_count": (
                    tmux_cleanup.get("summary", {}).get("candidate_count", "?")
                    if isinstance(tmux_cleanup, dict) and isinstance(tmux_cleanup.get("summary"), dict)
                    else "?"
                ),
                "review_high": (
                    tmux_cleanup.get("summary", {}).get("review_high_count", "?")
                    if isinstance(tmux_cleanup, dict) and isinstance(tmux_cleanup.get("summary"), dict)
                    else "?"
                ),
                "review_medium": (
                    tmux_cleanup.get("summary", {}).get("review_medium_count", "?")
                    if isinstance(tmux_cleanup, dict) and isinstance(tmux_cleanup.get("summary"), dict)
                    else "?"
                ),
                "stop_candidates": (
                    tmux_cleanup.get("summary", {}).get("stop_candidate_count", "?")
                    if isinstance(tmux_cleanup, dict) and isinstance(tmux_cleanup.get("summary"), dict)
                    else "?"
                ),
            },
        },
        "paths": {"status": str(STATUS_PATH), "report": str(REPORT_PATH)},
        "sources": {
            "p0_board": str(P0_BOARD),
            "readiness": str(READINESS),
            "service_map": str(SERVICE_MAP),
            "can_ops_brief": str(CAN_OPS_BRIEF),
            "can_doctor": str(CAN_DOCTOR),
            "tmux_cleanup": str(TMUX_CLEANUP),
            "r2_restic_intake": str(R2_RESTIC_INTAKE),
            "r2_restic_bootstrap": str(R2_RESTIC_BOOTSTRAP),
            "restore_drill": str(RESTORE_DRILL),
        },
    }
    return payload


def safe_md(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(payload: dict[str, Any]) -> str:
    first = payload["today"]["do_first"]
    status = payload["status"]
    lines = [
        "# Nomarh Daily Ops Snapshot",
        "",
        "No secrets, env files, tmux pane output, private keys, or mailbox contents are read. This snapshot is generated from status JSON only.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        "",
        "## Do First",
        "",
        f"- Task: **{safe_md(first['title'])}**",
        f"- Lane: `{safe_md(first['lane'])}`",
        f"- Status: `{safe_md(first['status'])}`",
        f"- Next action: {safe_md(first['next_action'])}",
        f"- Verify: `{safe_md(first['verify'])}`",
        "",
    ]
    if payload["today"]["do_not"]:
        lines.extend(["## Do Not", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["today"]["do_not"])
        lines.append("")

    lines.extend(
        [
            "## Current State",
            "",
            f"- P0 board: `{safe_md(status['p0']['result'])}`, counts `{safe_md(status['p0']['counts'])}`",
            f"- Migration readiness: `{safe_md(status['readiness']['result'])}`, ready={safe_md(status['readiness']['ready'])}, warn={safe_md(status['readiness']['warn'])}, blocked={safe_md(status['readiness']['blocked'])}",
            f"- Service map: `{safe_md(status['service_map']['result'])}`, priority `{safe_md(status['service_map']['priority'])}`",
            f"- R2/restic intake: `{safe_md(status['r2_restic_intake']['result'])}`, blockers={safe_md(status['r2_restic_intake']['blocker_count'])}, input groups={safe_md(status['r2_restic_intake']['input_groups'])}",
            f"- R2/restic bootstrap: `{safe_md(status['r2_restic_bootstrap']['result'])}`, blockers={safe_md(status['r2_restic_bootstrap']['blocker_count'])}",
            f"- Restore drill: `{safe_md(status['restore_drill']['result'])}`, blockers={safe_md(status['restore_drill']['blocker_count'])}",
            f"- Can-doctor: `{safe_md(status['doctor']['result'])}`, warnings={safe_md(status['doctor']['warnings'])}",
            f"- Tmux cleanup: `{safe_md(status['tmux_cleanup']['result'])}`, candidates={safe_md(status['tmux_cleanup']['candidate_count'])}, high={safe_md(status['tmux_cleanup']['review_high'])}, medium={safe_md(status['tmux_cleanup']['review_medium'])}, stop={safe_md(status['tmux_cleanup']['stop_candidates'])}",
            "",
            "## Top Priorities",
            "",
        ]
    )
    priorities = status["brief"]["top_priorities"]
    if priorities:
        lines.extend(f"{idx}. {safe_md(item)}" for idx, item in enumerate(priorities, start=1))
    else:
        lines.append("- No priorities generated; run `can-ops-refresh --json`.")

    lines.extend(["", "## Verify After Change", ""])
    lines.extend(f"- `{safe_md(item)}`" for item in payload["today"]["verify_after_change"])
    lines.extend(["", "## Sources", ""])
    for key, path in payload["sources"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a compact no-secret daily ops snapshot")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_payload()
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        first = payload["today"]["do_first"]
        print("Nomarh daily ops snapshot")
        print(f"Result: {payload['result']}")
        print(f"Do first: {first['title']} [{first['status']}]")
        print(f"Report: {REPORT_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

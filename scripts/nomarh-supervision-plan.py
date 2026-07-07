#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-supervision-plan"
STATUS_PATH = STATE_DIR / "plan.json"
REPORT_PATH = STATE_DIR / "plan.md"

SERVICE_MAP_STATUS = HOME / ".local/state/nomarh-service-migration-map/map.json"
TMUX_INVENTORY = HOME / ".local/state/can-doctor/tmux-inventory.json"
SCHEDULER_STATUS = HOME / ".local/state/can-ops-scheduler/status.json"
RESTIC_BACKUP_STATUS = HOME / ".local/state/control-plane-restic-backup/status.json"
RESTORE_DRILL_STATUS = HOME / ".local/state/control-plane-restic-restore-drill/status.json"
HARDENING_STATUS = HOME / ".local/state/hetzner-hardening-preflight/status.json"


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


def result_of(payload: Any) -> str:
    return str(payload.get("result", "missing")) if isinstance(payload, dict) else "missing"


def tmux_names(inventory: Any) -> set[str]:
    sessions = inventory.get("sessions") if isinstance(inventory, dict) and isinstance(inventory.get("sessions"), list) else []
    return {str(item.get("name", "")) for item in sessions if isinstance(item, dict)}


def priority_rank(value: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "retire": 4}.get(value, 5)


def systemd_kind(target_model: str) -> str:
    lowered = target_model.lower()
    if "timer" in lowered:
        return "timer"
    if "retire" in lowered:
        return "retire"
    if "ephemeral" in lowered:
        return "ephemeral"
    if "service" in lowered:
        return "service"
    return "decision"


def unit_name(name: str, kind: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in name).strip("-").lower()
    suffix = "timer" if kind == "timer" else "service"
    return f"nomarh-{safe}.{suffix}"


def service_status(
    *,
    name: str,
    priority: str,
    target_model: str,
    risk: str,
    scheduler: Any,
    restic: Any,
    restore: Any,
    hardening: Any,
) -> tuple[str, list[str], list[str]]:
    blockers: list[str] = []
    decisions: list[str] = []
    kind = systemd_kind(target_model)
    restic_result = result_of(restic)
    restore_result = result_of(restore)
    hardening_result = result_of(hardening)

    if name == "vault-backup":
        if restic_result != "success":
            blockers.append("real restic backup is not successful yet")
        if restore_result != "success":
            blockers.append("restore drill is not successful yet")
    if name == "can-ops-refresh-loop":
        mode = str(scheduler.get("mode", "missing")) if isinstance(scheduler, dict) else "missing"
        scheduler_result = result_of(scheduler)
        if scheduler_result == "success" and mode in {"systemd", "systemd-user"}:
            return "ready", blockers, decisions
        decisions.append("install systemd user timer on Hetzner after non-root user is available")
    if kind == "service" and risk == "high":
        decisions.append("audit env/secrets and owner before installing service unit")
    if kind == "ephemeral":
        decisions.append("replace persistent tmux loop with one-shot secure intake workflow")
    if kind == "decision":
        decisions.append("decide whether to supervise, keep manual, or retire")
    if name in {"bot", "provider-gateway-tunnel"} and hardening_result != "ready":
        decisions.append("keep behind current controls until Hetzner hardening warnings are resolved or accepted")

    if blockers:
        return "blocked", blockers, decisions
    if decisions:
        return "pending-decision", blockers, decisions
    if kind in {"service", "timer"}:
        return "ready-to-spec", blockers, decisions
    if kind in {"retire", "ephemeral"}:
        return "pending", blockers, decisions
    return "pending", blockers, decisions


def suggested_commands(name: str, target_model: str) -> list[str]:
    kind = systemd_kind(target_model)
    if name == "can-ops-refresh-loop":
        return ["can-ops-scheduler install-systemd --interval 1800", "can-ops-scheduler status"]
    if name == "vault-backup":
        return [
            "control-plane-restic-backup --json",
            "control-plane-restic-restore-drill --json",
            "install scoped restic systemd service/timer after both are successful",
        ]
    if kind == "service":
        return [
            f"create {unit_name(name, kind)} with explicit WorkingDirectory, EnvironmentFile, Restart=on-failure",
            "systemctl daemon-reload",
            f"systemctl enable --now {unit_name(name, kind)}",
            f"systemctl status {unit_name(name, kind)}",
        ]
    if kind == "timer":
        return [
            f"create {unit_name(name, kind).replace('.timer', '.service')} as oneshot",
            f"create {unit_name(name, kind)} with bounded schedule",
            "systemctl daemon-reload",
            f"systemctl enable --now {unit_name(name, kind)}",
        ]
    if kind == "ephemeral":
        return ["document secure one-shot intake command", "remove persistent tmux session after handoff is verified"]
    if kind == "retire":
        return ["confirm not required", "archive state if needed", "stop old tmux/service"]
    return ["decide owner, uptime requirement, and target model"]


def build_payload() -> dict[str, Any]:
    service_map = read_json(SERVICE_MAP_STATUS)
    inventory = read_json(TMUX_INVENTORY)
    scheduler = read_json(SCHEDULER_STATUS)
    restic = read_json(RESTIC_BACKUP_STATUS)
    restore = read_json(RESTORE_DRILL_STATUS)
    hardening = read_json(HARDENING_STATUS)

    blockers: list[str] = []
    if not isinstance(service_map, dict):
        blockers.append(f"service migration map missing or invalid: {SERVICE_MAP_STATUS}")

    names = tmux_names(inventory)
    items = service_map.get("items") if isinstance(service_map, dict) and isinstance(service_map.get("items"), list) else []
    selected = [
        item
        for item in items
        if isinstance(item, dict) and str(item.get("priority", "")) in {"P0", "P1"}
    ]
    selected.sort(key=lambda item: (priority_rank(str(item.get("priority", ""))), str(item.get("name", ""))))

    plans: list[dict[str, Any]] = []
    for item in selected:
        name = str(item.get("name", ""))
        priority = str(item.get("priority", ""))
        target_model = str(item.get("target_model", ""))
        risk = str(item.get("risk", ""))
        status, item_blockers, decisions = service_status(
            name=name,
            priority=priority,
            target_model=target_model,
            risk=risk,
            scheduler=scheduler,
            restic=restic,
            restore=restore,
            hardening=hardening,
        )
        kind = systemd_kind(target_model)
        plans.append(
            {
                "name": name,
                "priority": priority,
                "risk": risk,
                "present_in_tmux": name in names,
                "target_model": target_model,
                "systemd_kind": kind,
                "unit_name": unit_name(name, kind) if kind in {"service", "timer"} else "",
                "status": status,
                "blockers": item_blockers,
                "decisions": decisions,
                "source_action": str(item.get("action", "")),
                "suggested_commands": suggested_commands(name, target_model),
            }
        )

    counts: dict[str, int] = {}
    for plan in plans:
        counts[plan["status"]] = counts.get(plan["status"], 0) + 1
    result = "blocked" if blockers or counts.get("blocked", 0) else "warn" if counts.get("pending-decision", 0) or counts.get("pending", 0) else "ready"

    return {
        "schema": "nomarh-supervision-plan.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "blockers": blockers,
        "summary": {
            "plan_count": len(plans),
            "status_counts": dict(sorted(counts.items())),
            "p0_count": sum(1 for plan in plans if plan["priority"] == "P0"),
            "p1_count": sum(1 for plan in plans if plan["priority"] == "P1"),
            "tmux_total": len(names),
            "service_map_result": result_of(service_map),
            "scheduler_result": result_of(scheduler),
            "restic_backup_result": result_of(restic),
            "restore_drill_result": result_of(restore),
            "hardening_result": result_of(hardening),
        },
        "plans": plans,
        "paths": {"status": str(STATUS_PATH), "report": str(REPORT_PATH)},
        "sources": {
            "service_map": str(SERVICE_MAP_STATUS),
            "tmux_inventory": str(TMUX_INVENTORY),
            "scheduler": str(SCHEDULER_STATUS),
            "restic_backup": str(RESTIC_BACKUP_STATUS),
            "restore_drill": str(RESTORE_DRILL_STATUS),
            "hardening": str(HARDENING_STATUS),
        },
    }


def safe_md(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Nomarh Supervision Plan",
        "",
        "No tmux pane output, env values, private keys, or secret files are read. This plan converts the service migration map into supervision decisions.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- P0/P1 plans: {summary['plan_count']} (P0={summary['p0_count']}, P1={summary['p1_count']})",
        f"- Status counts: `{safe_md(summary['status_counts'])}`",
        f"- Tmux sessions observed: `{summary['tmux_total']}`",
        f"- Backup gate: restic `{safe_md(summary['restic_backup_result'])}`, restore `{safe_md(summary['restore_drill_result'])}`",
        f"- Hardening: `{safe_md(summary['hardening_result'])}`",
        "",
    ]
    if payload["blockers"]:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["blockers"])
        lines.append("")

    lines.extend(["## P0/P1 Plans", "", "| Priority | Service | Status | Target | Unit | Blockers | Decisions |", "|---|---|---|---|---|---|---|"])
    for plan in payload["plans"]:
        lines.append(
            f"| `{safe_md(plan['priority'])}` | `{safe_md(plan['name'])}` | `{safe_md(plan['status'])}` | "
            f"{safe_md(plan['target_model'])} | `{safe_md(plan['unit_name'])}` | "
            f"{safe_md('; '.join(plan['blockers']) or 'none')} | {safe_md('; '.join(plan['decisions']) or 'none')} |"
        )

    lines.extend(["", "## Suggested Commands", ""])
    for plan in payload["plans"]:
        lines.extend([f"### {safe_md(plan['name'])}", "", f"- Status: `{safe_md(plan['status'])}`", ""])
        if plan["suggested_commands"]:
            lines.extend(["```bash"])
            lines.extend(str(command) for command in plan["suggested_commands"])
            lines.extend(["```", ""])

    lines.extend(["## Sources", ""])
    for key, path in payload["sources"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate no-secret P0/P1 supervision plan for Nomarh services")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_payload()
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Nomarh supervision plan")
        print(f"Result: {payload['result']}")
        print(f"Plans: {payload['summary']['plan_count']}")
        print(f"Status: {STATUS_PATH}")
        print(f"Report: {REPORT_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

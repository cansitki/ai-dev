#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-p0-execution-board"
STATUS_PATH = STATE_DIR / "board.json"
REPORT_PATH = STATE_DIR / "board.md"

READINESS_STATUS = HOME / ".local/state/nomarh-migration-readiness/readiness.json"
SERVICE_MAP_STATUS = HOME / ".local/state/nomarh-service-migration-map/map.json"
BACKUP_READINESS_STATUS = HOME / ".local/state/control-plane-backup-readiness/status.json"
R2_RESTIC_INTAKE_STATUS = HOME / ".local/state/control-plane-r2-restic-intake/status.json"
R2_RESTIC_BOOTSTRAP_STATUS = HOME / ".local/state/control-plane-r2-restic-bootstrap/status.json"
RESTIC_STATUS = HOME / ".local/state/control-plane-restic-backup/status.json"
RESTORE_DRILL_STATUS = HOME / ".local/state/control-plane-restic-restore-drill/status.json"
HARDENING_STATUS = HOME / ".local/state/hetzner-hardening-preflight/status.json"
SCHEDULER_STATUS = HOME / ".local/state/can-ops-scheduler/status.json"


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


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def has_text(items: list[Any], *needles: str) -> bool:
    text = "\n".join(str(item).lower() for item in items)
    return any(needle.lower() in text for needle in needles)


def task(
    task_id: str,
    title: str,
    lane: str,
    status: str,
    why: str,
    next_action: str,
    verify: str,
    source: str,
    order: int,
) -> dict[str, Any]:
    return {
        "id": task_id,
        "title": title,
        "lane": lane,
        "status": status,
        "why": why,
        "next_action": next_action,
        "verify": verify,
        "source": source,
        "order": order,
    }


def backup_tasks(readiness: Any, intake: Any, bootstrap: Any, restic: Any, restore_drill: Any) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    readiness_blockers = readiness.get("blockers") if isinstance(readiness, dict) and isinstance(readiness.get("blockers"), list) else []
    intake_blockers = intake.get("blockers") if isinstance(intake, dict) and isinstance(intake.get("blockers"), list) else []
    intake_result = str(intake.get("result", "missing")) if isinstance(intake, dict) else "missing"
    intake_summary = intake.get("summary") if isinstance(intake, dict) and isinstance(intake.get("summary"), dict) else {}
    bootstrap_blockers = bootstrap.get("blockers") if isinstance(bootstrap, dict) and isinstance(bootstrap.get("blockers"), list) else []
    bootstrap_result = str(bootstrap.get("result", "missing")) if isinstance(bootstrap, dict) else "missing"
    restic_blockers = restic.get("blockers") if isinstance(restic, dict) and isinstance(restic.get("blockers"), list) else []
    restic_result = str(restic.get("result", "missing")) if isinstance(restic, dict) else "missing"
    restore_result = str(restore_drill.get("result", "missing")) if isinstance(restore_drill, dict) else "missing"
    restore_blockers = restore_drill.get("blockers") if isinstance(restore_drill, dict) and isinstance(restore_drill.get("blockers"), list) else []

    intake_ready = isinstance(intake, dict) and not intake_blockers
    tasks.append(
        task(
            "r2-restic-intake",
            "Complete secure R2/restic intake",
            "backup",
            "ready" if intake_ready else "blocked",
            f"Intake status is `{intake_result}` with {len(intake_blockers)} blocker(s); input groups {intake_summary.get('present_required_input_groups', 0)}/{intake_summary.get('required_input_groups', 0)}.",
            "Fill the secure env file, create the restic password file, and configure active rclone remote `r2:`.",
            "control-plane-r2-restic-intake --json",
            str(R2_RESTIC_INTAKE_STATUS),
            5,
        )
    )

    r2_ready = not has_text(readiness_blockers + bootstrap_blockers, "active rclone remote r2", "r2 remote")
    tasks.append(
        task(
            "r2-remote",
            "Configure active R2 remote",
            "backup",
            "ready" if r2_ready else "blocked",
            "Backup readiness requires an active `r2:` remote.",
            "Configure scoped Cloudflare R2 remote or update backup policy if the remote name changes.",
            "control-plane-r2-restic-bootstrap --json",
            str(R2_RESTIC_BOOTSTRAP_STATUS),
            10,
        )
    )

    bootstrap_ready = isinstance(bootstrap, dict) and not bootstrap_blockers
    tasks.append(
        task(
            "restic-credentials",
            "Provide scoped restic/R2 credentials",
            "backup",
            "ready" if bootstrap_ready else "blocked",
            f"Bootstrap status is `{bootstrap_result}` with {len(bootstrap_blockers)} blocker(s). Restic status is `{restic_result}` with {len(restic_blockers)} blocker(s).",
            "Provide R2 endpoint, bucket, access key, secret key, and restic password through the secure env/vault path.",
            "control-plane-r2-restic-bootstrap --json",
            str(R2_RESTIC_BOOTSTRAP_STATUS),
            20,
        )
    )

    restic_ready = isinstance(restic, dict) and not restic_blockers
    dry_run_ok = restic_result in {"dry-run-ok", "success"}
    tasks.append(
        task(
            "restic-dry-run",
            "Run restic init/dry-run",
            "backup",
            "ready" if dry_run_ok else "blocked" if not restic_ready else "pending",
            "Dry-run proves repository configuration before a real backup.",
            "Run `control-plane-restic-backup --init --dry-run` after credentials are present.",
            "control-plane-restic-backup --init --dry-run",
            str(RESTIC_STATUS),
            30,
        )
    )

    real_backup_ok = restic_result == "success"
    tasks.append(
        task(
            "restic-real-backup",
            "Run real control-plane backup",
            "backup",
            "ready" if real_backup_ok else "blocked" if not dry_run_ok else "pending",
            "Migration needs a current successful backup, not only a manifest.",
            "Run the real `control-plane-restic-backup` and keep the status file fresh.",
            "control-plane-restic-backup --json",
            str(RESTIC_STATUS),
            40,
        )
    )

    tasks.append(
        task(
            "restore-drill",
            "Perform restore drill",
            "backup",
            "ready" if restore_result == "success" else "blocked" if not real_backup_ok else "pending",
            f"Restore drill status is `{restore_result}` with {len(restore_blockers)} blocker(s).",
            "Run `control-plane-restic-restore-drill --json` after a real backup exists.",
            "control-plane-restic-restore-drill --json",
            str(RESTORE_DRILL_STATUS),
            50,
        )
    )
    return tasks


def hardening_tasks(hardening: Any) -> list[dict[str, Any]]:
    warnings = hardening.get("warnings") if isinstance(hardening, dict) and isinstance(hardening.get("warnings"), list) else []
    result = str(hardening.get("result", "missing")) if isinstance(hardening, dict) else "missing"
    return [
        task(
            "hetzner-non-root-admin",
            "Create non-root sudo admin",
            "hardening",
            "ready" if not has_text(warnings, "non-root", "sudo group") and result != "missing" else "pending",
            "Direct root operational use should not be the normal workflow on the main host.",
            "Create a named sudo admin, confirm key SSH login, then keep root key-only or disable routine root login.",
            "hetzner-hardening-preflight --json",
            str(HARDENING_STATUS),
            60,
        ),
        task(
            "hetzner-firewall",
            "Activate explicit firewall policy",
            "hardening",
            "ready" if not has_text(warnings, "ufw", "firewall") and result != "missing" else "pending",
            "Current hardening preflight still reports firewall/UFW warning if not resolved.",
            "Allow only intentional SSH/web/mail ports and activate the firewall.",
            "hetzner-hardening-preflight --json",
            str(HARDENING_STATUS),
            70,
        ),
        task(
            "hetzner-port-review",
            "Review public mail/service ports",
            "hardening",
            "ready" if not has_text(warnings, "mail ports", "listening ports") and result != "missing" else "pending",
            "Mailcow is running, but public protocol/service exposure must be intentional.",
            "Decide whether 110/143/995/4190 and service ports stay public, local-only, or closed.",
            "hetzner-hardening-preflight --json",
            str(HARDENING_STATUS),
            80,
        ),
    ]


def service_tasks(service_map: Any, scheduler: Any) -> list[dict[str, Any]]:
    items = service_map.get("items") if isinstance(service_map, dict) and isinstance(service_map.get("items"), list) else []
    by_name = {str(item.get("name", "")): item for item in items if isinstance(item, dict)}
    scheduler_mode = str(scheduler.get("mode", "missing")) if isinstance(scheduler, dict) else "missing"
    scheduler_result = str(scheduler.get("result", "missing")) if isinstance(scheduler, dict) else "missing"

    p0_names = ["bot", "can-ops-refresh-loop", "vault-backup"]
    tasks: list[dict[str, Any]] = []
    for index, name in enumerate(p0_names, start=90):
        item = by_name.get(name, {})
        target = str(item.get("target_model", "missing"))
        risk = str(item.get("risk", "unknown"))
        if name == "can-ops-refresh-loop":
            ready = scheduler_result == "success" and scheduler_mode in {"systemd", "systemd-user"}
            status = "ready" if ready else "pending"
            next_action = "Install the ops refresh systemd user timer on Hetzner when user systemd is available."
            verify = "can-ops-scheduler status"
        elif name == "vault-backup":
            status = "blocked"
            next_action = "Do not migrate old raw vault backup; replace with scoped restic/systemd timer after backup gate passes."
            verify = "control-plane-restic-backup --json"
        else:
            status = "pending"
            next_action = str(item.get("action", "Assign owner and supervised target model."))
            verify = "nomarh-service-migration-map --json"
        tasks.append(
            task(
                f"service-{name}",
                f"Migrate service model for {name}",
                "service-model",
                status,
                f"Target `{target}`, risk `{risk}`.",
                next_action,
                verify,
                str(SERVICE_MAP_STATUS),
                index,
            )
        )
    return tasks


def build_payload() -> dict[str, Any]:
    readiness = read_json(READINESS_STATUS)
    service_map = read_json(SERVICE_MAP_STATUS)
    backup_readiness = read_json(BACKUP_READINESS_STATUS)
    intake = read_json(R2_RESTIC_INTAKE_STATUS)
    bootstrap = read_json(R2_RESTIC_BOOTSTRAP_STATUS)
    restic = read_json(RESTIC_STATUS)
    restore_drill = read_json(RESTORE_DRILL_STATUS)
    hardening = read_json(HARDENING_STATUS)
    scheduler = read_json(SCHEDULER_STATUS)

    blockers: list[str] = []
    if not isinstance(readiness, dict):
        blockers.append("migration readiness status missing")
    if not isinstance(service_map, dict):
        blockers.append("service migration map status missing")

    tasks = []
    tasks.extend(backup_tasks(backup_readiness, intake, bootstrap, restic, restore_drill))
    tasks.extend(hardening_tasks(hardening))
    tasks.extend(service_tasks(service_map, scheduler))
    tasks = sorted(tasks, key=lambda item: int(item["order"]))

    counts: dict[str, int] = {}
    for item in tasks:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    result = "blocked" if blockers or counts.get("blocked", 0) else "warn" if counts.get("pending", 0) else "ready"

    next_tasks = [item for item in tasks if item["status"] in {"blocked", "pending"}][:6]
    return {
        "schema": "nomarh-p0-execution-board.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "blockers": blockers,
        "summary": {
            "task_count": len(tasks),
            "counts": dict(sorted(counts.items())),
            "readiness_result": readiness.get("result", "missing") if isinstance(readiness, dict) else "missing",
            "service_map_result": service_map.get("result", "missing") if isinstance(service_map, dict) else "missing",
        },
        "tasks": tasks,
        "next_tasks": next_tasks,
        "paths": {"status": str(STATUS_PATH), "report": str(REPORT_PATH)},
        "sources": {
            "readiness": str(READINESS_STATUS),
            "service_map": str(SERVICE_MAP_STATUS),
            "backup_readiness": str(BACKUP_READINESS_STATUS),
            "r2_restic_intake": str(R2_RESTIC_INTAKE_STATUS),
            "r2_restic_bootstrap": str(R2_RESTIC_BOOTSTRAP_STATUS),
            "restic": str(RESTIC_STATUS),
            "restore_drill": str(RESTORE_DRILL_STATUS),
            "hardening": str(HARDENING_STATUS),
            "scheduler": str(SCHEDULER_STATUS),
        },
    }


def safe_md(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Nomarh P0 Execution Board",
        "",
        "No secrets, env files, tmux pane output, private keys, or mailbox contents are read. This board is generated from existing status JSON only.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Counts: `{safe_md(payload['summary']['counts'])}`",
        "",
        "## Next Tasks",
        "",
        "| Order | Lane | Task | Status | Next Action | Verify |",
        "|---:|---|---|---|---|---|",
    ]
    for item in payload["next_tasks"]:
        lines.append(
            f"| {item['order']} | `{safe_md(item['lane'])}` | {safe_md(item['title'])} | `{safe_md(item['status'])}` | {safe_md(item['next_action'])} | `{safe_md(item['verify'])}` |"
        )

    lines.extend(["", "## Full Board", "", "| Order | Lane | Task | Status | Why | Source |", "|---:|---|---|---|---|---|"])
    for item in payload["tasks"]:
        lines.append(
            f"| {item['order']} | `{safe_md(item['lane'])}` | {safe_md(item['title'])} | `{safe_md(item['status'])}` | {safe_md(item['why'])} | `{safe_md(item['source'])}` |"
        )

    lines.extend(["", "## Sources", ""])
    for key, path in payload["sources"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate no-secret P0 execution board for Nomarh cutover")
    parser.add_argument("--json", action="store_true", help="print JSON payload")
    args = parser.parse_args()

    payload = build_payload()
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Nomarh P0 execution board")
        print(f"Result: {payload['result']}")
        print(f"Tasks: {payload['summary']['task_count']}")
        print(f"Status: {STATUS_PATH}")
        print(f"Report: {REPORT_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

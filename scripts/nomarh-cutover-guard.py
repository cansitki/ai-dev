#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-cutover-guard"
STATUS_PATH = STATE_DIR / "guard.json"
REPORT_PATH = STATE_DIR / "guard.md"

READINESS_STATUS = HOME / ".local/state/nomarh-migration-readiness/readiness.json"
P0_BOARD_STATUS = HOME / ".local/state/nomarh-p0-execution-board/board.json"
BOOTSTRAP_STATUS = HOME / ".local/state/control-plane-r2-restic-bootstrap/status.json"
RESTIC_BACKUP_STATUS = HOME / ".local/state/control-plane-restic-backup/status.json"
RESTORE_DRILL_STATUS = HOME / ".local/state/control-plane-restic-restore-drill/status.json"
HARDENING_STATUS = HOME / ".local/state/hetzner-hardening-preflight/status.json"
HARDENING_REMEDIATION_STATUS = HOME / ".local/state/hetzner-hardening-remediation/status.json"
SUPERVISION_PLAN_STATUS = HOME / ".local/state/nomarh-supervision-plan/plan.json"
DAILY_SNAPSHOT_STATUS = HOME / ".local/state/nomarh-daily-ops-snapshot/snapshot.json"
SECRET_ROTATION_STATUS = HOME / ".local/state/nomarh-secret-rotation-plan/status.json"
STATE_TRANSFER_PLAN_STATUS = HOME / ".local/state/nomarh-state-transfer-plan/status.json"
MAIL_PRODUCTION_GATE_STATUS = HOME / ".local/state/nomarh-mail-production-gate/status.json"


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


def list_len(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def dict_get(payload: Any, key: str, default: Any = None) -> Any:
    return payload.get(key, default) if isinstance(payload, dict) else default


def int_get(payload: Any, key: str) -> int:
    try:
        return int(dict_get(payload, key, 0) or 0)
    except Exception:
        return 0


def first_task(snapshot: Any) -> dict[str, str]:
    task = dict_get(dict_get(snapshot, "today", {}), "do_first", {})
    if not isinstance(task, dict):
        task = {}
    return {
        "title": str(task.get("title", "Run `nomarh-ops --refresh`")),
        "lane": str(task.get("lane", "setup")),
        "status": str(task.get("status", "missing")),
        "next_action": str(task.get("next_action", "Refresh operations status.")),
        "verify": str(task.get("verify", "nomarh-ops --refresh --json")),
    }


def decision(name: str, allowed: bool, reasons: list[str], allowed_when: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "allowed": allowed,
        "status": "allowed" if allowed else "blocked",
        "reasons": reasons,
        "allowed_when": allowed_when,
    }


def build_payload() -> dict[str, Any]:
    readiness = read_json(READINESS_STATUS)
    p0 = read_json(P0_BOARD_STATUS)
    bootstrap = read_json(BOOTSTRAP_STATUS)
    restic = read_json(RESTIC_BACKUP_STATUS)
    restore = read_json(RESTORE_DRILL_STATUS)
    hardening = read_json(HARDENING_STATUS)
    hardening_remediation = read_json(HARDENING_REMEDIATION_STATUS)
    supervision = read_json(SUPERVISION_PLAN_STATUS)
    snapshot = read_json(DAILY_SNAPSHOT_STATUS)
    secret_rotation = read_json(SECRET_ROTATION_STATUS)
    state_transfer = read_json(STATE_TRANSFER_PLAN_STATUS)
    mail_gate = read_json(MAIL_PRODUCTION_GATE_STATUS)

    p0_summary = dict_get(p0, "summary", {})
    p0_counts = dict_get(p0_summary, "counts", {})
    p0_blocked = int(dict_get(p0_counts, "blocked", 0) or 0)
    p0_pending = int(dict_get(p0_counts, "pending", 0) or 0)

    readiness_summary = dict_get(readiness, "summary", {})
    readiness_blocked = int(dict_get(readiness_summary, "blocked", 0) or 0)
    readiness_warn = int(dict_get(readiness_summary, "warn", 0) or 0)

    supervision_summary = dict_get(supervision, "summary", {})
    supervision_counts = dict_get(supervision_summary, "status_counts", {})
    supervision_blocked = int(dict_get(supervision_counts, "blocked", 0) or 0)
    supervision_pending_decision = int(dict_get(supervision_counts, "pending-decision", 0) or 0)

    bootstrap_blockers = list_len(dict_get(bootstrap, "blockers", []))
    restic_blockers = list_len(dict_get(restic, "blockers", []))
    restore_blockers = list_len(dict_get(restore, "blockers", []))
    hardening_warnings = list_len(dict_get(hardening, "warnings", []))
    hardening_actions = list_len(dict_get(hardening_remediation, "actions", []))
    secret_summary = dict_get(secret_rotation, "summary", {})
    secret_risky_files = int(dict_get(secret_summary, "risky_doc_or_source_files", 0) or 0)
    secret_finding_files = int(dict_get(secret_summary, "finding_files", 0) or 0)
    state_transfer_summary = dict_get(state_transfer, "summary", {})
    state_blocked_surfaces = int_get(state_transfer_summary, "blocked_surface_count")
    state_blocked_services = int_get(state_transfer_summary, "blocked_service_count")
    state_pending_items = int_get(state_transfer_summary, "pending_item_count")
    state_cleanup_handoffs = int_get(state_transfer_summary, "cleanup_handoff_count")
    mail_summary = dict_get(mail_gate, "summary", {})
    mail_blockers = int_get(mail_summary, "blocker_count")
    mail_warnings = int_get(mail_summary, "warning_count")
    mail_cutover_ready = bool(dict_get(mail_summary, "cutover_ready", False))

    source_results = {
        "migration_readiness": result_of(readiness),
        "p0_board": result_of(p0),
        "r2_restic_bootstrap": result_of(bootstrap),
        "restic_backup": result_of(restic),
        "restore_drill": result_of(restore),
        "hetzner_hardening": result_of(hardening),
        "hetzner_hardening_remediation": result_of(hardening_remediation),
        "supervision_plan": result_of(supervision),
        "daily_snapshot": result_of(snapshot),
        "secret_rotation": result_of(secret_rotation),
        "state_transfer_plan": result_of(state_transfer),
        "mail_production_gate": result_of(mail_gate),
    }

    hard_stop_reasons: list[str] = []
    warn_reasons: list[str] = []
    if source_results["r2_restic_bootstrap"] != "ready-to-dry-run":
        hard_stop_reasons.append("R2/restic bootstrap is not ready.")
    if source_results["restic_backup"] != "success":
        hard_stop_reasons.append("A real restic backup has not succeeded.")
    if source_results["restore_drill"] != "success":
        hard_stop_reasons.append("Restore drill has not succeeded.")
    if readiness_blocked or source_results["migration_readiness"] == "blocked":
        hard_stop_reasons.append("Migration readiness has blocked gates.")
    if p0_blocked:
        hard_stop_reasons.append(f"P0 board has {p0_blocked} blocked task(s).")
    if supervision_blocked:
        hard_stop_reasons.append(f"Supervision plan has {supervision_blocked} blocked item(s).")
    if secret_risky_files or source_results["secret_rotation"] == "blocked":
        hard_stop_reasons.append(f"Secret rotation plan has {secret_risky_files} risky doc/source file(s).")
    if source_results["state_transfer_plan"] == "blocked" or state_blocked_surfaces or state_blocked_services:
        hard_stop_reasons.append(
            f"State transfer plan is not ready: {state_blocked_surfaces} blocked surface(s), {state_blocked_services} blocked service(s)."
        )
    if hardening_warnings:
        warn_reasons.append(f"Hetzner hardening has {hardening_warnings} warning(s).")
    if hardening_actions:
        warn_reasons.append(f"Hetzner hardening remediation has {hardening_actions} pending action(s).")
    if supervision_pending_decision:
        warn_reasons.append(f"Supervision plan has {supervision_pending_decision} pending decision(s).")
    if p0_pending:
        warn_reasons.append(f"P0 board has {p0_pending} pending task(s).")
    if readiness_warn:
        warn_reasons.append(f"Migration readiness has {readiness_warn} warning gate(s).")

    backup_ok = source_results["restic_backup"] == "success" and source_results["restore_drill"] == "success"
    state_transfer_ready = (
        source_results["state_transfer_plan"] == "ready"
        and state_blocked_surfaces == 0
        and state_blocked_services == 0
        and secret_risky_files == 0
    )
    cutover_allowed = not hard_stop_reasons and not warn_reasons
    state_copy_allowed = backup_ok and state_transfer_ready
    service_migration_allowed = backup_ok and state_transfer_ready and not supervision_blocked
    mail_cutover_allowed = source_results["mail_production_gate"] == "ready" and mail_cutover_ready
    decommission_allowed = cutover_allowed and backup_ok and p0_blocked == 0 and p0_pending == 0

    decisions = [
        decision(
            "state_copy_to_hetzner",
            state_copy_allowed,
            ([] if backup_ok else ["Backup and restore proof is missing."])
            + ([] if state_transfer_ready else [f"State transfer still has {state_blocked_surfaces} blocked surface(s), {state_blocked_services} blocked service(s), {state_pending_items} pending item(s)."])
            + ([] if secret_risky_files == 0 else ["Secret-bearing state still needs rotation/redaction."]),
            [
                "Real restic backup successful.",
                "Restore drill successful.",
                "State transfer plan is ready.",
                "Secret rotation plan is clean.",
                "Live tmux cleanup handoffs are resolved or documented.",
            ],
        ),
        decision(
            "mail_production_cutover",
            mail_cutover_allowed,
            ([] if source_results["mail_production_gate"] == "ready" else [f"Mail production gate is {source_results['mail_production_gate']} with {mail_blockers} blocker(s), {mail_warnings} warning(s)."])
            + ([] if mail_cutover_ready else ["Mail gate does not mark MX/outbound cutover ready."]),
            [
                "Mailcow is healthy.",
                "MX points to the intended Mailcow host.",
                "SPF authorizes the Hetzner mail host/IP.",
                "DKIM selector exists and aligns.",
                "PTR/rDNS, DMARC, TLS, and port 25 checks pass.",
                "Rollback window is chosen.",
            ],
        ),
        decision(
            "aws_main_cutover",
            cutover_allowed,
            hard_stop_reasons + warn_reasons,
            [
                "R2/restic bootstrap ready.",
                "Real restic backup successful.",
                "Restore drill successful.",
                "Migration readiness has no blocked/warn gates.",
                "P0 board has no blocked or pending tasks.",
                "Hetzner hardening warnings are resolved or explicitly accepted.",
                "Supervision plan has no blocked or pending-decision items.",
                "Secret rotation plan has no risky doc/source findings.",
            ],
        ),
        decision(
            "service_migration",
            service_migration_allowed,
            ([] if backup_ok else ["Backup and restore proof is missing."])
            + ([] if state_transfer_ready else ["State transfer plan is not ready for durable service state."])
            + ([] if not supervision_blocked else ["Supervision plan still has blocked items."]),
            [
                "Real restic backup successful.",
                "Restore drill successful.",
                "State transfer plan is ready for the relevant service.",
                "No blocked supervision items for the service being moved.",
            ],
        ),
        decision(
            "aws_decommission",
            decommission_allowed,
            hard_stop_reasons + warn_reasons + ([] if decommission_allowed else ["AWS/main must stay fallback until cutover is proven and observed."]),
            [
                "Cutover has completed successfully.",
                "Fresh backup and restore drill exist after cutover.",
                "P0 board is clean.",
                "Secret rotation plan is clean after state copy.",
                "Observation window has passed without rollback need.",
            ],
        ),
    ]

    result = "blocked" if any(not item["allowed"] for item in decisions) else "ready"
    return {
        "schema": "nomarh-cutover-guard.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "do_first": first_task(snapshot),
        "summary": {
            "hard_stop_count": len(hard_stop_reasons),
            "warning_count": len(warn_reasons),
            "p0_blocked": p0_blocked,
            "p0_pending": p0_pending,
            "readiness_blocked": readiness_blocked,
            "readiness_warn": readiness_warn,
            "bootstrap_blockers": bootstrap_blockers,
            "restic_blockers": restic_blockers,
            "restore_blockers": restore_blockers,
            "hardening_warnings": hardening_warnings,
            "hardening_actions": hardening_actions,
            "supervision_blocked": supervision_blocked,
            "supervision_pending_decision": supervision_pending_decision,
            "secret_finding_files": secret_finding_files,
            "secret_risky_doc_or_source_files": secret_risky_files,
            "state_transfer_blocked_surfaces": state_blocked_surfaces,
            "state_transfer_blocked_services": state_blocked_services,
            "state_transfer_pending_items": state_pending_items,
            "state_transfer_cleanup_handoffs": state_cleanup_handoffs,
            "mail_production_blockers": mail_blockers,
            "mail_production_warnings": mail_warnings,
            "mail_production_cutover_ready": mail_cutover_ready,
        },
        "source_results": source_results,
        "hard_stops": hard_stop_reasons,
        "warnings": warn_reasons,
        "decisions": decisions,
        "do_not": [
            "Do not cut over AWS/main runtime to Hetzner.",
            "Do not decommission AWS/main.",
            "Do not migrate durable services before backup/restore proof exists.",
            "Do not copy state to Hetzner outside the state transfer plan.",
            "Do not cut production MX/outbound mail to Mailcow while the mail production gate is blocked.",
            "Do not copy vault/source state to Hetzner before rotating and redacting exposed secrets.",
        ]
        if result == "blocked"
        else [],
        "paths": {"status": str(STATUS_PATH), "report": str(REPORT_PATH)},
        "sources": {
            "migration_readiness": str(READINESS_STATUS),
            "p0_board": str(P0_BOARD_STATUS),
            "bootstrap": str(BOOTSTRAP_STATUS),
            "restic_backup": str(RESTIC_BACKUP_STATUS),
            "restore_drill": str(RESTORE_DRILL_STATUS),
            "hardening": str(HARDENING_STATUS),
            "hardening_remediation": str(HARDENING_REMEDIATION_STATUS),
            "supervision_plan": str(SUPERVISION_PLAN_STATUS),
            "daily_snapshot": str(DAILY_SNAPSHOT_STATUS),
            "secret_rotation": str(SECRET_ROTATION_STATUS),
            "state_transfer_plan": str(STATE_TRANSFER_PLAN_STATUS),
            "mail_production_gate": str(MAIL_PRODUCTION_GATE_STATUS),
        },
    }


def safe_md(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(payload: dict[str, Any]) -> str:
    first = payload["do_first"]
    lines = [
        "# Nomarh Cutover Guard",
        "",
        "No secrets, env values, private keys, tmux pane output, or mailbox contents are read. This guard aggregates existing status JSON and blocks unsafe cutover/decommission decisions.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Hard stops: `{payload['summary']['hard_stop_count']}`",
        f"- Warnings: `{payload['summary']['warning_count']}`",
        f"- Secret findings: `{payload['summary']['secret_finding_files']}`, risky doc/source `{payload['summary']['secret_risky_doc_or_source_files']}`",
        f"- State transfer: blocked surfaces `{payload['summary']['state_transfer_blocked_surfaces']}`, blocked services `{payload['summary']['state_transfer_blocked_services']}`, pending items `{payload['summary']['state_transfer_pending_items']}`, cleanup handoffs `{payload['summary']['state_transfer_cleanup_handoffs']}`",
        f"- Mail production: blockers `{payload['summary']['mail_production_blockers']}`, warnings `{payload['summary']['mail_production_warnings']}`, cutover ready `{payload['summary']['mail_production_cutover_ready']}`",
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
    if payload["do_not"]:
        lines.extend(["## Do Not", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["do_not"])
        lines.append("")

    lines.extend(["## Decisions", "", "| Decision | Status | Reasons | Allowed When |", "|---|---|---|---|"])
    for item in payload["decisions"]:
        lines.append(
            f"| `{safe_md(item['name'])}` | `{safe_md(item['status'])}` | "
            f"{safe_md('; '.join(item['reasons']) or 'none')} | {safe_md('; '.join(item['allowed_when']))} |"
        )

    lines.extend(["", "## Source Results", "", "| Source | Result |", "|---|---|"])
    for key, result in payload["source_results"].items():
        lines.append(f"| `{safe_md(key)}` | `{safe_md(result)}` |")

    lines.extend(["", "## Sources", ""])
    for key, path in payload["sources"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="No-secret cutover/decommission guard for Nomarh AWS/main to Hetzner migration")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_payload()
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Nomarh cutover guard")
        print(f"Result: {payload['result']}")
        print(f"Hard stops: {payload['summary']['hard_stop_count']}")
        print(f"Warnings: {payload['summary']['warning_count']}")
        print(f"Report: {REPORT_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

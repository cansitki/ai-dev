#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
VAULT = HOME / "Can"
INFRA_DIR = VAULT / "infrastructure"
STATE_DIR = HOME / ".local/state/nomarh-objective-coverage"
STATUS_PATH = STATE_DIR / "status.json"
REPORT_PATH = STATE_DIR / "coverage.md"

EVIDENCE_STATUS = HOME / ".local/state/nomarh-ops-evidence-digest/status.json"
VM_STRUCTURE_STATUS = HOME / ".local/state/nomarh-vm-structure-map/status.json"
OPERATIONS_ROADMAP_STATUS = HOME / ".local/state/nomarh-operations-roadmap/status.json"
NOMARH_OPS_STATUS = HOME / ".local/state/nomarh-ops/status.json"
OPERATOR_CARD_STATUS = HOME / ".local/state/nomarh-operator-card/status.json"
ACTION_PACK_STATUS = HOME / ".local/state/nomarh-action-pack/status.json"
CUTOVER_GUARD_STATUS = HOME / ".local/state/nomarh-cutover-guard/guard.json"
STATE_TRANSFER_STATUS = HOME / ".local/state/nomarh-state-transfer-plan/status.json"
MAIL_GATE_STATUS = HOME / ".local/state/nomarh-mail-production-gate/status.json"
SECRET_ROTATION_STATUS = HOME / ".local/state/nomarh-secret-rotation-plan/status.json"
GUARDED_APPLY_STATUS = HOME / ".local/state/nomarh-guarded-apply-readiness/status.json"
RUNTIME_STABILIZATION_STATUS = HOME / ".local/state/nomarh-runtime-stabilization-board/status.json"
R2_PACKET_STATUS = HOME / ".local/state/control-plane-r2-secure-input-packet/status.json"
R2_REMOTE_STATUS = HOME / ".local/state/control-plane-r2-remote-config/status.json"
RESTIC_BACKUP_STATUS = HOME / ".local/state/control-plane-restic-backup/status.json"
RESTORE_DRILL_STATUS = HOME / ".local/state/control-plane-restic-restore-drill/status.json"
HETZNER_HARDENING_STATUS = HOME / ".local/state/hetzner-hardening-preflight/status.json"

MAIN_PLAN_DOC = INFRA_DIR / "Nomarh Main Server Migration and Daily Operations Plan 2026-07-04.md"
EXECUTION_PLAN_DOC = INFRA_DIR / "Nomarh Hetzner Main Migration Execution Plan 2026-07-04.md"
BACKLOG_DOC = INFRA_DIR / "Nomarh Daily Operations Improvement Backlog 2026-07-04.md"
SERVICE_INVENTORY_DOC = INFRA_DIR / "Nomarh Control Plane Service Inventory 2026-07-04.md"
ROADMAP_RUNBOOK_DOC = INFRA_DIR / "Nomarh Operations Roadmap Runbook.md"
VM_MAP_RUNBOOK_DOC = INFRA_DIR / "Nomarh VM Structure Map Runbook.md"


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
    if not text.endswith("\n"):
        text += "\n"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def dict_get(payload: Any, key: str, default: Any = None) -> Any:
    return payload.get(key, default) if isinstance(payload, dict) else default


def list_get(payload: Any, key: str) -> list[Any]:
    value = dict_get(payload, key, [])
    return value if isinstance(value, list) else []


def int_get(payload: Any, key: str) -> int:
    try:
        return int(dict_get(payload, key, 0) or 0)
    except Exception:
        return 0


def bool_get(payload: Any, key: str) -> bool:
    return bool(dict_get(payload, key, False))


def safe_md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def doc_evidence(path: Path) -> dict[str, Any]:
    exists = path.exists()
    line_count = 0
    heading_count = 0
    if exists:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            line_count = len(lines)
            heading_count = sum(1 for line in lines if line.startswith("#"))
        except Exception:
            pass
    return {
        "path": str(path),
        "exists": exists,
        "line_count": line_count,
        "heading_count": heading_count,
    }


def covered_doc(path: Path, min_lines: int = 20) -> bool:
    evidence = doc_evidence(path)
    return bool(evidence["exists"] and int(evidence["line_count"]) >= min_lines)


def requirement(
    req_id: str,
    title: str,
    status: str,
    evidence: list[str],
    next_action: str,
    verify: str,
    implementation_blocked: bool = False,
) -> dict[str, Any]:
    return {
        "id": req_id,
        "title": title,
        "status": status,
        "implementation_blocked": implementation_blocked,
        "evidence": evidence,
        "next_action": next_action,
        "verify": verify,
    }


def build_payload() -> dict[str, Any]:
    evidence = read_json(EVIDENCE_STATUS)
    vm_structure = read_json(VM_STRUCTURE_STATUS)
    roadmap = read_json(OPERATIONS_ROADMAP_STATUS)
    ops = read_json(NOMARH_OPS_STATUS)
    operator_card = read_json(OPERATOR_CARD_STATUS)
    action_pack = read_json(ACTION_PACK_STATUS)
    cutover = read_json(CUTOVER_GUARD_STATUS)
    state_transfer = read_json(STATE_TRANSFER_STATUS)
    mail_gate = read_json(MAIL_GATE_STATUS)
    secret_rotation = read_json(SECRET_ROTATION_STATUS)
    guarded_apply = read_json(GUARDED_APPLY_STATUS)
    runtime = read_json(RUNTIME_STABILIZATION_STATUS)
    r2_packet = read_json(R2_PACKET_STATUS)
    r2_remote = read_json(R2_REMOTE_STATUS)
    restic_backup = read_json(RESTIC_BACKUP_STATUS)
    restore_drill = read_json(RESTORE_DRILL_STATUS)
    hardening = read_json(HETZNER_HARDENING_STATUS)

    evidence_summary = dict_get(evidence, "summary", {})
    vm_summary = dict_get(vm_structure, "summary", {})
    roadmap_summary = dict_get(roadmap, "summary", {})
    ops_summary = dict_get(ops, "summary", {})
    action_summary = dict_get(action_pack, "summary", {})
    cutover_hard_stops = list_get(cutover, "hard_stops")
    state_summary = dict_get(state_transfer, "summary", {})
    mail_summary = dict_get(mail_gate, "summary", {})
    secret_summary = dict_get(secret_rotation, "summary", {})
    guarded_summary = dict_get(guarded_apply, "summary", {})
    runtime_summary = dict_get(runtime, "summary", {})
    r2_summary = dict_get(r2_packet, "summary", {})
    r2_remote_summary = dict_get(r2_remote, "summary", {})

    docs = {
        "main_plan": doc_evidence(MAIN_PLAN_DOC),
        "execution_plan": doc_evidence(EXECUTION_PLAN_DOC),
        "daily_backlog": doc_evidence(BACKLOG_DOC),
        "service_inventory": doc_evidence(SERVICE_INVENTORY_DOC),
        "roadmap_runbook": doc_evidence(ROADMAP_RUNBOOK_DOC),
        "vm_map_runbook": doc_evidence(VM_MAP_RUNBOOK_DOC),
    }

    daily_notes = int_get(evidence_summary, "daily_note_count")
    missing_days = int_get(evidence_summary, "missing_day_count")
    secret_pattern_files = int_get(evidence_summary, "secret_pattern_file_count")
    service_count = int_get(vm_summary, "service_count")
    roadmap_phases = int_get(roadmap_summary, "phase_count")
    roadmap_actions = int_get(roadmap_summary, "action_count")
    r2_missing_groups = int_get(r2_summary, "missing_required_input_groups")
    backup_ready = (
        dict_get(r2_packet, "result") == "ready"
        and dict_get(r2_remote, "result") in {"ready", "success"}
        and dict_get(restic_backup, "result") == "success"
        and dict_get(restore_drill, "result") == "success"
    )
    secret_clean = int_get(secret_summary, "finding_file_count") == 0 and int_get(secret_summary, "risky_doc_or_source_files") == 0
    daily_entrypoint_present = isinstance(ops, dict) and isinstance(operator_card, dict)
    cloudflare_r2_active = bool_get(r2_summary, "active_r2_remote") or bool_get(r2_remote_summary, "active_r2_after")
    hardening_ready = dict_get(hardening, "result") == "ready"
    state_ready = dict_get(state_transfer, "result") == "ready"
    mail_ready = bool_get(mail_summary, "cutover_ready")
    guarded_can_run = bool_get(guarded_apply, "can_run_guarded_actions")

    requirements = [
        requirement(
            "daily-notes-evidence",
            "Extract recent daily operations evidence from vault daily notes",
            "covered" if daily_notes >= 40 and secret_pattern_files == 0 else "warn" if daily_notes else "missing",
            [
                f"daily notes scanned: {daily_notes}",
                f"missing calendar days: {missing_days}",
                f"secret-pattern files: {secret_pattern_files}",
                f"evidence result: {dict_get(evidence, 'result', 'missing')}",
            ],
            "Keep the evidence digest in the morning refresh and write only changed decisions/blockers to daily notes.",
            "nomarh-ops-evidence-digest --json",
        ),
        requirement(
            "vm-structure-map",
            "Map the current VM/control-plane structure",
            "covered" if service_count else "missing",
            [
                f"services: {service_count}",
                f"P0/P1: {int_get(vm_summary, 'p0_count')}/{int_get(vm_summary, 'p1_count')}",
                f"tmux sessions: {int_get(vm_summary, 'tmux_total')}",
                f"provider workers: {int_get(vm_summary, 'provider_workers')}",
                f"blocked surfaces: {int_get(vm_summary, 'blocked_surfaces')}",
            ],
            "Use the VM map before any service move; do not copy blocked or secret-bearing state directly.",
            "nomarh-vm-structure-map --json",
        ),
        requirement(
            "plans-and-backlog",
            "Have a concrete migration plan, execution plan, and improvement backlog",
            "covered"
            if covered_doc(MAIN_PLAN_DOC, 80) and covered_doc(EXECUTION_PLAN_DOC, 80) and covered_doc(BACKLOG_DOC, 80)
            else "missing",
            [
                f"main plan exists: {docs['main_plan']['exists']} lines {docs['main_plan']['line_count']}",
                f"execution plan exists: {docs['execution_plan']['exists']} lines {docs['execution_plan']['line_count']}",
                f"daily backlog exists: {docs['daily_backlog']['exists']} lines {docs['daily_backlog']['line_count']}",
            ],
            "Keep these as destination docs; add changes only when the operating model or priority changes.",
            "obsidian outline path=\"infrastructure/Nomarh Hetzner Main Migration Execution Plan 2026-07-04.md\"",
        ),
        requirement(
            "daily-entrypoint",
            "Make day-to-day operations easier with one command and one card",
            "covered" if daily_entrypoint_present else "missing",
            [
                f"nomarh-ops result: {dict_get(ops, 'result', 'missing')}",
                f"operator-card result: {dict_get(operator_card, 'result', 'missing')}",
                f"ops top priorities: {len(list_get(ops, 'top_priorities'))}",
                f"roadmap now: {safe_md(dict_get(dict_get(roadmap, 'now', {}), 'title', 'missing'))}",
            ],
            "Start the day with the operator card, then follow only the named blocker or safe review.",
            "nomarh-operator-card --refresh --json",
        ),
        requirement(
            "security-and-access",
            "Improve security: secret hygiene, scoped tokens, guarded applies, hardening",
            "blocked" if not secret_clean or not hardening_ready or not guarded_can_run else "covered",
            [
                f"secret rotation result: {dict_get(secret_rotation, 'result', 'missing')}",
                f"secret finding files: {int_get(secret_summary, 'finding_file_count')}",
                f"risky doc/source files: {int_get(secret_summary, 'risky_doc_or_source_files')}",
                f"hardening result: {dict_get(hardening, 'result', 'missing')}",
                f"guarded apply can run: {guarded_can_run}",
                f"guarded gate blockers: {int_get(guarded_summary, 'gate_blocker_count')}",
            ],
            "Keep secret scans clean, complete R2/restic input, then apply reviewed hardening only through guarded readiness.",
            "nomarh-secret-rotation-plan --json && nomarh-guarded-apply-readiness --json",
            implementation_blocked=not (secret_clean and hardening_ready and guarded_can_run),
        ),
        requirement(
            "backup-restore",
            "Make Hetzner recoverable before it becomes the main server",
            "blocked" if not backup_ready else "covered",
            [
                f"secure packet result: {dict_get(r2_packet, 'result', 'missing')}",
                f"missing R2/restic input groups: {r2_missing_groups}",
                f"active r2 remote: {cloudflare_r2_active}",
                f"restic backup result: {dict_get(restic_backup, 'result', 'missing')}",
                f"restore drill result: {dict_get(restore_drill, 'result', 'missing')}",
            ],
            "Complete the secure R2/restic input packet, configure active r2, run real backup, then run restore drill.",
            "control-plane-r2-secure-input-packet --json",
            implementation_blocked=not backup_ready,
        ),
        requirement(
            "runtime-fluidity",
            "Make operations more fluid by reducing tmux sprawl and supervising durable work",
            "warn" if int_get(runtime_summary, "decision_needed_count") or int_get(runtime_summary, "tmux_review_count") else "covered",
            [
                f"runtime board result: {dict_get(runtime, 'result', 'missing')}",
                f"runtime actions: {int_get(runtime_summary, 'action_count')}",
                f"tmux handoffs: {int_get(runtime_summary, 'tmux_review_count')}",
                f"decisions needed: {int_get(runtime_summary, 'decision_needed_count')}",
                f"safe reviews: {int_get(action_summary, 'safe_review_count')}",
            ],
            "Review tmux handoffs and convert only durable P0/P1 loops into supervised services/timers.",
            "nomarh-runtime-stabilization-board --json",
        ),
        requirement(
            "aws-to-hetzner-cutover",
            "Move the AWS/main role to Hetzner through gated cutover",
            "blocked" if cutover_hard_stops or not state_ready or not backup_ready else "covered",
            [
                f"cutover result: {dict_get(cutover, 'result', 'missing')}",
                f"hard stops: {len(cutover_hard_stops)}",
                f"state transfer result: {dict_get(state_transfer, 'result', 'missing')}",
                f"blocked state surfaces: {int_get(state_summary, 'blocked_surface_count')}",
                f"blocked services: {int_get(state_summary, 'blocked_service_count')}",
            ],
            "Do not copy state or cut over AWS/main until backup/restore and state-transfer gates are green.",
            "nomarh-cutover-guard --json",
            implementation_blocked=bool(cutover_hard_stops or not state_ready or not backup_ready),
        ),
        requirement(
            "mail-production",
            "Keep mail migration as a separate reputation-sensitive gate",
            "blocked" if not mail_ready else "covered",
            [
                f"mail gate result: {dict_get(mail_gate, 'result', 'missing')}",
                f"mail blockers: {int_get(mail_summary, 'blocker_count')}",
                f"mail warnings: {int_get(mail_summary, 'warning_count')}",
                f"MX aligned: {bool_get(mail_summary, 'mx_points_to_mailhost')}",
                f"SPF aligned: {bool_get(mail_summary, 'spf_authorizes_mailhost')}",
                f"DKIM selectors: {int_get(mail_summary, 'dkim_selector_count')}",
            ],
            "Keep MX/outbound on the current provider until SPF/DKIM/DMARC/PTR/TLS/client tests and warm-up are acceptable.",
            "nomarh-mail-production-gate --json",
            implementation_blocked=not mail_ready,
        ),
        requirement(
            "roadmap-acceptance",
            "Expose a single ordered roadmap with acceptance checks",
            "covered" if roadmap_phases >= 6 and roadmap_actions >= 4 else "missing",
            [
                f"roadmap result: {dict_get(roadmap, 'result', 'missing')}",
                f"phases: {roadmap_phases}",
                f"actions: {roadmap_actions}",
                f"blockers: {int_get(roadmap_summary, 'blocker_count')}",
                f"acceptance checks: {len(list_get(roadmap, 'acceptance'))}",
            ],
            "Follow the roadmap `now` item and re-run it after every operational change.",
            "nomarh-operations-roadmap --json",
        ),
    ]

    missing = [item for item in requirements if item["status"] == "missing"]
    blocked = [item for item in requirements if item["status"] == "blocked"]
    warnings = [item for item in requirements if item["status"] == "warn"]
    covered = [item for item in requirements if item["status"] == "covered"]
    implementation_blocked = [item for item in requirements if item["implementation_blocked"]]

    coverage_complete = not missing
    result = "missing" if missing else "blocked" if implementation_blocked else "warn" if warnings or blocked else "covered"
    preferred_next_ids = ["backup-restore", "security-and-access", "aws-to-hetzner-cutover", "mail-production"]
    prioritized_blockers = [
        item
        for req_id in preferred_next_ids
        for item in requirements
        if item["id"] == req_id and (item["status"] in {"blocked", "missing"} or item["implementation_blocked"])
    ]
    next_requirement = (missing or prioritized_blockers or blocked or implementation_blocked or warnings or requirements)[0]
    next_action = {
        "requirement": next_requirement["id"],
        "title": next_requirement["title"],
        "status": next_requirement["status"],
        "next_action": next_requirement["next_action"],
        "verify": next_requirement["verify"],
    }

    return {
        "schema": "nomarh-objective-coverage.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "coverage_complete": coverage_complete,
        "implementation_ready": not implementation_blocked,
        "next_action": next_action,
        "summary": {
            "requirement_count": len(requirements),
            "covered_count": len(covered),
            "missing_count": len(missing),
            "blocked_count": len(blocked),
            "warning_count": len(warnings),
            "implementation_blocked_count": len(implementation_blocked),
            "daily_notes": daily_notes,
            "missing_days": missing_days,
            "service_count": service_count,
            "roadmap_phases": roadmap_phases,
            "roadmap_actions": roadmap_actions,
            "r2_missing_groups": r2_missing_groups,
            "backup_ready": backup_ready,
            "state_ready": state_ready,
            "mail_ready": mail_ready,
            "hardening_ready": hardening_ready,
            "secret_clean": secret_clean,
        },
        "requirements": requirements,
        "docs": docs,
        "paths": {
            "status": str(STATUS_PATH),
            "report": str(REPORT_PATH),
            "evidence": str(EVIDENCE_STATUS),
            "vm_structure": str(VM_STRUCTURE_STATUS),
            "operations_roadmap": str(OPERATIONS_ROADMAP_STATUS),
            "nomarh_ops": str(NOMARH_OPS_STATUS),
            "operator_card": str(OPERATOR_CARD_STATUS),
            "cutover_guard": str(CUTOVER_GUARD_STATUS),
            "state_transfer": str(STATE_TRANSFER_STATUS),
            "mail_gate": str(MAIL_GATE_STATUS),
            "secret_rotation": str(SECRET_ROTATION_STATUS),
            "guarded_apply": str(GUARDED_APPLY_STATUS),
            "runtime_stabilization": str(RUNTIME_STABILIZATION_STATUS),
            "r2_secure_packet": str(R2_PACKET_STATUS),
            "r2_remote": str(R2_REMOTE_STATUS),
            "restic_backup": str(RESTIC_BACKUP_STATUS),
            "restore_drill": str(RESTORE_DRILL_STATUS),
            "hetzner_hardening": str(HETZNER_HARDENING_STATUS),
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    next_action = payload["next_action"]
    lines = [
        "# Nomarh Objective Coverage",
        "",
        "No secrets, env values, tmux pane output, private keys, mailbox contents, or remote command bodies are read. This audit proves which parts of the large operations objective have evidence and which parts are still implementation-blocked.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Coverage complete: `{payload['coverage_complete']}`",
        f"- Implementation ready: `{payload['implementation_ready']}`",
        f"- Requirements: `{summary['requirement_count']}`; covered `{summary['covered_count']}`, missing `{summary['missing_count']}`, blocked `{summary['blocked_count']}`, warn `{summary['warning_count']}`",
        f"- Daily evidence: `{summary['daily_notes']}` notes, missing days `{summary['missing_days']}`",
        f"- Structure: services `{summary['service_count']}`, roadmap phases/actions `{summary['roadmap_phases']}`/`{summary['roadmap_actions']}`",
        f"- Gates: backup `{summary['backup_ready']}`, state `{summary['state_ready']}`, mail `{summary['mail_ready']}`, hardening `{summary['hardening_ready']}`, secrets clean `{summary['secret_clean']}`",
        "",
        "## Next Action",
        "",
        f"- Requirement: `{safe_md(next_action['requirement'])}`",
        f"- Task: **{safe_md(next_action['title'])}**",
        f"- Status: `{safe_md(next_action['status'])}`",
        f"- Next action: {safe_md(next_action['next_action'])}",
        f"- Verify: `{safe_md(next_action['verify'])}`",
        "",
        "## Requirement Matrix",
        "",
        "| Requirement | Status | Implementation Blocked | Evidence | Verify |",
        "|---|---|---|---|---|",
    ]
    for item in payload["requirements"]:
        evidence = "; ".join(str(value) for value in item["evidence"])
        lines.append(
            f"| `{safe_md(item['id'])}` {safe_md(item['title'])} | `{safe_md(item['status'])}` | `{safe_md(item['implementation_blocked'])}` | {safe_md(evidence)} | `{safe_md(item['verify'])}` |"
        )

    lines.extend(["", "## Document Evidence", "", "| Doc | Exists | Lines | Headings |", "|---|---:|---:|---:|"])
    for key, doc in payload["docs"].items():
        lines.append(f"| `{safe_md(key)}` | `{safe_md(doc['exists'])}` | `{safe_md(doc['line_count'])}` | `{safe_md(doc['heading_count'])}` |")

    lines.extend(["", "## Source Paths", ""])
    for key, path in payload["paths"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def render_console(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    next_action = payload["next_action"]
    return "\n".join(
        [
            "Nomarh Objective Coverage",
            f"Result: {payload['result']}",
            f"Coverage complete: {payload['coverage_complete']} | implementation ready: {payload['implementation_ready']}",
            f"Requirements: covered={summary['covered_count']} missing={summary['missing_count']} blocked={summary['blocked_count']} warn={summary['warning_count']} impl_blocked={summary['implementation_blocked_count']}",
            f"Evidence: daily_notes={summary['daily_notes']} services={summary['service_count']} roadmap={summary['roadmap_phases']}/{summary['roadmap_actions']}",
            f"Gates: backup={summary['backup_ready']} state={summary['state_ready']} mail={summary['mail_ready']} hardening={summary['hardening_ready']} secrets_clean={summary['secret_clean']}",
            f"Next: {next_action['title']} [{next_action['status']}]",
            f"Verify: {next_action['verify']}",
            f"Report: {REPORT_PATH}",
            f"Status: {STATUS_PATH}",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit coverage of the Nomarh daily-ops and AWS-to-Hetzner objective")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_payload()
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_console(payload))
    return 2 if payload["result"] in {"blocked", "missing"} else 0


if __name__ == "__main__":
    raise SystemExit(main())

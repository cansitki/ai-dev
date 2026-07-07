#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-operations-roadmap"
STATUS_PATH = STATE_DIR / "status.json"
REPORT_PATH = STATE_DIR / "roadmap.md"

OPERATOR_CARD_STATUS = HOME / ".local/state/nomarh-operator-card/status.json"
OPS_STATUS = HOME / ".local/state/nomarh-ops/status.json"
VM_STRUCTURE_STATUS = HOME / ".local/state/nomarh-vm-structure-map/status.json"
ACTION_PACK_STATUS = HOME / ".local/state/nomarh-action-pack/status.json"
GUARDED_APPLY_STATUS = HOME / ".local/state/nomarh-guarded-apply-readiness/status.json"
CUTOVER_GUARD_STATUS = HOME / ".local/state/nomarh-cutover-guard/guard.json"
MIGRATION_READINESS_STATUS = HOME / ".local/state/nomarh-migration-readiness/readiness.json"
STATE_TRANSFER_STATUS = HOME / ".local/state/nomarh-state-transfer-plan/status.json"
SERVICE_MAP_STATUS = HOME / ".local/state/nomarh-service-migration-map/map.json"
RUNTIME_BOARD_STATUS = HOME / ".local/state/nomarh-runtime-stabilization-board/status.json"
MAIL_GATE_STATUS = HOME / ".local/state/nomarh-mail-production-gate/status.json"
OPS_EVIDENCE_STATUS = HOME / ".local/state/nomarh-ops-evidence-digest/status.json"
R2_PACKET_STATUS = HOME / ".local/state/control-plane-r2-secure-input-packet/status.json"
R2_REMOTE_STATUS = HOME / ".local/state/control-plane-r2-remote-config/status.json"
R2_BOOTSTRAP_STATUS = HOME / ".local/state/control-plane-r2-restic-bootstrap/status.json"
RESTIC_BACKUP_STATUS = HOME / ".local/state/control-plane-restic-backup/status.json"
RESTORE_DRILL_STATUS = HOME / ".local/state/control-plane-restic-restore-drill/status.json"
HETZNER_HARDENING_STATUS = HOME / ".local/state/hetzner-hardening-preflight/status.json"
HARDENING_BUNDLE_STATUS = HOME / ".local/state/hetzner-hardening-command-bundle/status.json"


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


def unique_strings(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        key = text.lower().rstrip(".")
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def action(
    action_id: str,
    phase: str,
    priority: str,
    lane: str,
    title: str,
    status: str,
    next_action: str,
    verify: str,
    reason: str,
    allowed_now: bool,
) -> dict[str, Any]:
    return {
        "id": action_id,
        "phase": phase,
        "priority": priority,
        "lane": lane,
        "title": title,
        "status": status,
        "next_action": next_action,
        "verify": verify,
        "reason": reason,
        "allowed_now": allowed_now,
    }


def phase(
    phase_id: str,
    order: int,
    title: str,
    status: str,
    goal: str,
    entry_gate: str,
    exit_gate: str,
    actions: list[str],
) -> dict[str, Any]:
    return {
        "id": phase_id,
        "order": order,
        "title": title,
        "status": status,
        "goal": goal,
        "entry_gate": entry_gate,
        "exit_gate": exit_gate,
        "actions": actions,
    }


def build_payload() -> dict[str, Any]:
    operator_card = read_json(OPERATOR_CARD_STATUS)
    ops = read_json(OPS_STATUS)
    vm_structure = read_json(VM_STRUCTURE_STATUS)
    action_pack = read_json(ACTION_PACK_STATUS)
    guarded_apply = read_json(GUARDED_APPLY_STATUS)
    cutover = read_json(CUTOVER_GUARD_STATUS)
    readiness = read_json(MIGRATION_READINESS_STATUS)
    state_transfer = read_json(STATE_TRANSFER_STATUS)
    service_map = read_json(SERVICE_MAP_STATUS)
    runtime_board = read_json(RUNTIME_BOARD_STATUS)
    mail_gate = read_json(MAIL_GATE_STATUS)
    evidence = read_json(OPS_EVIDENCE_STATUS)
    r2_packet = read_json(R2_PACKET_STATUS)
    r2_remote = read_json(R2_REMOTE_STATUS)
    r2_bootstrap = read_json(R2_BOOTSTRAP_STATUS)
    restic_backup = read_json(RESTIC_BACKUP_STATUS)
    restore_drill = read_json(RESTORE_DRILL_STATUS)
    hetzner_hardening = read_json(HETZNER_HARDENING_STATUS)
    hardening_bundle = read_json(HARDENING_BUNDLE_STATUS)

    op_summary = dict_get(operator_card, "summary", {})
    ops_summary = dict_get(ops, "summary", {})
    vm_summary = dict_get(vm_structure, "summary", {})
    guarded_summary = dict_get(guarded_apply, "summary", {})
    state_summary = dict_get(state_transfer, "summary", {})
    service_summary = dict_get(service_map, "summary", {})
    runtime_summary = dict_get(runtime_board, "summary", {})
    mail_summary = dict_get(mail_gate, "summary", {})
    evidence_summary = dict_get(evidence, "summary", {})
    r2_summary = dict_get(r2_packet, "summary", {})
    r2_remote_summary = dict_get(r2_remote, "summary", {})
    hardening_bundle_summary = dict_get(hardening_bundle, "summary", {})

    backup_ready = (
        dict_get(r2_packet, "result") == "ready"
        and dict_get(r2_remote, "result") in {"ready", "success"}
        and dict_get(r2_bootstrap, "result") in {"ready", "success"}
        and dict_get(restic_backup, "result") == "success"
        and dict_get(restore_drill, "result") == "success"
    )
    state_ready = dict_get(state_transfer, "result") == "ready"
    mail_ready = bool_get(mail_summary, "cutover_ready")
    hardening_ready = dict_get(hetzner_hardening, "result") == "ready"
    guarded_can_run = bool_get(guarded_apply, "can_run_guarded_actions")

    hard_stops = [str(item) for item in list_get(cutover, "hard_stops")]
    do_not = unique_strings(list_get(cutover, "do_not") + list_get(action_pack, "do_not") + list_get(guarded_apply, "do_not"))
    blockers: list[str] = []
    warnings: list[str] = []

    if not backup_ready:
        blockers.append("Backup/restore proof is missing: R2/restic input, real backup, or restore drill is not green.")
    if not state_ready:
        blockers.append("State transfer is blocked; do not copy state or migrate durable services.")
    if not mail_ready:
        blockers.append("Mail production cutover is blocked; keep production MX/outbound on the current provider.")
    if hard_stops:
        blockers.append(f"Cutover guard has {len(hard_stops)} hard stop(s).")
    if not hardening_ready:
        warnings.append("Hetzner hardening is still warn/pending; apply only after guarded readiness allows it.")
    if int_get(runtime_summary, "decision_needed_count"):
        warnings.append(f"Runtime stabilization still needs {int_get(runtime_summary, 'decision_needed_count')} decision(s).")
    if int_get(evidence_summary, "missing_day_count"):
        warnings.append(f"Daily-note evidence has {int_get(evidence_summary, 'missing_day_count')} missing day(s) in the window.")

    current_actions = [
        action(
            "r2-secure-input",
            "phase-0-now",
            "P0",
            "backup",
            "Complete secure R2/restic input packet",
            str(dict_get(r2_packet, "result", "missing")),
            "Collect the required R2/restic inputs through the secure packet path, then configure the real active `r2:` remote.",
            "control-plane-r2-secure-input-packet --json",
            f"Missing input groups {int_get(r2_summary, 'missing_required_input_groups')}; active r2 {bool_get(r2_summary, 'active_r2_remote')}.",
            True,
        ),
        action(
            "r2-remote-config",
            "phase-0-now",
            "P0",
            "backup",
            "Configure active R2 remote",
            str(dict_get(r2_remote, "result", "missing")),
            "Create the secure env/password files and activate the real `r2:` remote without exposing secret values.",
            "control-plane-r2-remote-config --json",
            f"Remote config blockers {int_get(r2_remote_summary, 'blocker_count')}; active r2 {bool_get(r2_remote_summary, 'active_r2_after')}.",
            int_get(r2_summary, "missing_required_input_groups") == 0,
        ),
        action(
            "backup-restore-proof",
            "phase-1-backup",
            "P0",
            "backup",
            "Run real backup and restore drill",
            "blocked" if not backup_ready else "ready",
            "Run bootstrap, backup, and restore drill after R2/restic input is complete.",
            "control-plane-restic-backup --json && control-plane-restic-restore-drill --json",
            f"Backup result {dict_get(restic_backup, 'result', 'missing')}; restore result {dict_get(restore_drill, 'result', 'missing')}.",
            dict_get(r2_remote, "result") in {"ready", "success"},
        ),
        action(
            "hetzner-hardening-review",
            "phase-2-hardening",
            "P0",
            "hardening",
            "Review Hetzner hardening bundle",
            str(dict_get(hetzner_hardening, "result", "missing")),
            "Review non-root admin, firewall policy, and port review scripts. Apply only after guarded readiness permits.",
            "nomarh-guarded-apply-readiness --json && hetzner-hardening-preflight --json",
            f"Hardening warnings {len(list_get(hetzner_hardening, 'warnings'))}; pending actions {int_get(hardening_bundle_summary, 'pending_action_count')}.",
            guarded_can_run,
        ),
        action(
            "runtime-stabilization",
            "phase-3-runtime",
            "P1",
            "runtime",
            "Resolve runtime cleanup and supervision decisions",
            str(dict_get(runtime_board, "result", "missing")),
            "Review tmux handoffs, pending supervision decisions, and ready unit specs without stopping sessions automatically.",
            "nomarh-runtime-stabilization-board --json",
            f"Actions {int_get(runtime_summary, 'action_count')}; tmux handoffs {int_get(runtime_summary, 'tmux_review_count')}; decisions {int_get(runtime_summary, 'decision_needed_count')}.",
            True,
        ),
        action(
            "mail-production-gate",
            "phase-5-mail",
            "P1",
            "mail",
            "Keep mail production as separate gate",
            str(dict_get(mail_gate, "result", "missing")),
            "Align MX/SPF/DKIM/DMARC/port25/TLS before production mail cutover.",
            "nomarh-mail-production-gate --json",
            f"Mail blockers {int_get(mail_summary, 'blocker_count')}; warnings {int_get(mail_summary, 'warning_count')}; cutover ready {mail_ready}.",
            False,
        ),
    ]

    phases = [
        phase(
            "phase-0-now",
            0,
            "Today: stabilize the gate view and secure inputs",
            "blocked" if not backup_ready else "ready",
            "Make the current operating picture unambiguous and collect missing backup inputs safely.",
            "Start here every day with the operator card.",
            "R2/restic secure input packet has no missing required groups.",
            ["Run operator card", "Complete R2/restic secure input packet", "Keep do-not rules visible"],
        ),
        phase(
            "phase-1-backup-restore",
            1,
            "Backup foundation",
            "blocked" if not backup_ready else "ready",
            "Create a scoped encrypted backup and prove restore before any migration.",
            "R2/restic input exists and active `r2:` is configured.",
            "Real backup and restore drill succeed.",
            ["Configure remote", "Run bootstrap", "Run real backup", "Run restore drill"],
        ),
        phase(
            "phase-2-hardening",
            2,
            "Hetzner hardening",
            "ready" if hardening_ready else "warn",
            "Make Hetzner safe enough to host daily control-plane duties.",
            "Backup/restore proof exists or operator accepts guarded review-only work.",
            "Non-root admin, firewall policy, and port review are verified.",
            ["Review guarded hardening bundle", "Apply only when guarded readiness allows", "Rerun preflight"],
        ),
        phase(
            "phase-3-runtime-supervision",
            3,
            "Runtime supervision",
            "warn" if int_get(runtime_summary, "action_count") else "ready",
            "Turn durable tmux loops into reviewed services/timers and retire stale work.",
            "Backup proof exists and hardening policy is known.",
            "P0/P1 services have target model, owner, and verify command.",
            ["Resolve tmux handoffs", "Resolve supervision decisions", "Install only reviewed unit specs"],
        ),
        phase(
            "phase-4-state-copy",
            4,
            "State transfer",
            "ready" if state_ready else "blocked",
            "Restore or recreate the minimum state needed on Hetzner.",
            "Backup/restore proof exists and state transfer status is ready.",
            "Secret-bearing state restored only through encrypted backup/restore.",
            ["Restore scoped state", "Recreate services from source", "Exclude retired/status-only state"],
        ),
        phase(
            "phase-5-mail-production",
            5,
            "Mail production",
            "ready" if mail_ready else "blocked",
            "Cut mail only when deliverability and protocol checks are ready.",
            "Mail gate ready and rollback window chosen.",
            "MX/SPF/DKIM/DMARC/PTR/TLS/port25 and client tests pass.",
            ["Keep current MX until ready", "Confirm DNS auth records", "Run delivery tests", "Warm up slowly"],
        ),
        phase(
            "phase-6-cutover",
            6,
            "AWS/main cutover",
            "blocked" if hard_stops or not backup_ready or not state_ready else "warn",
            "Make Hetzner primary while AWS remains rollback.",
            "Cutover guard allows runtime cutover.",
            "Hetzner runs daily ops for the observation window.",
            ["Run parallel validation", "Move primary workflows", "Keep AWS rollback"],
        ),
        phase(
            "phase-7-steady-state",
            7,
            "Steady operations",
            "pending",
            "Make daily operations boring: one command, supervised services, clean backups, reviewed access.",
            "Cutover observation window passes.",
            "AWS can be downsized/decommissioned without losing daily ops.",
            ["Schedule restore drills", "Rotate access", "Review service inventory weekly", "Archive stale sessions"],
        ),
    ]

    daily_ritual = [
        {
            "slot": "morning",
            "command": "nomarh-operator-card --refresh --json",
            "purpose": "Get the compact daily blocker and do-not view.",
        },
        {
            "slot": "after-any-change",
            "command": "nomarh-operations-roadmap --json && nomarh-cutover-guard --json",
            "purpose": "Confirm the change did not weaken gates or reorder work unsafely.",
        },
        {
            "slot": "end-of-day",
            "command": "nomarh-ops --refresh --json && obsidian sync:status",
            "purpose": "Persist status and confirm vault sync.",
        },
    ]

    acceptance = [
        "One command shows daily status and next safe action.",
        "R2/restic backup and restore drill are green.",
        "Secret scans remain clean after docs/script changes.",
        "Hetzner hardening is green or explicitly accepted with rollback.",
        "P0/P1 durable services are supervised, retired, or intentionally manual.",
        "Mail gate is ready before MX/outbound cutover.",
        "Cutover guard allows state copy, service migration, runtime cutover, and decommission decisions separately.",
    ]

    result = "blocked" if blockers else "warn" if warnings else "ready"
    now = next((item for item in current_actions if item["allowed_now"] and item["status"] != "ready"), current_actions[0])
    return {
        "schema": "nomarh-operations-roadmap.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "status_path": str(STATUS_PATH),
        "report_path": str(REPORT_PATH),
        "now": now,
        "summary": {
            "phase_count": len(phases),
            "action_count": len(current_actions),
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
            "hard_stop_count": len(hard_stops),
            "do_not_count": len(do_not),
            "r2_missing_groups": int_get(r2_summary, "missing_required_input_groups"),
            "r2_active": bool_get(r2_summary, "active_r2_remote") or bool_get(r2_remote_summary, "active_r2_after"),
            "backup_ready": backup_ready,
            "state_ready": state_ready,
            "mail_ready": mail_ready,
            "hardening_ready": hardening_ready,
            "guarded_can_run": guarded_can_run,
            "tmux_total": int_get(op_summary, "tmux_total") or int_get(ops_summary, "tmux_total"),
            "provider_workers": int_get(ops_summary, "provider_worker_count") or int_get(vm_summary, "provider_workers"),
            "service_count": int_get(service_summary, "total_items") or int_get(vm_summary, "service_count"),
            "p0_count": int_get(dict_get(service_summary, "by_priority", {}), "P0") or int_get(vm_summary, "p0_count"),
            "p1_count": int_get(dict_get(service_summary, "by_priority", {}), "P1") or int_get(vm_summary, "p1_count"),
            "blocked_surfaces": int_get(state_summary, "blocked_surface_count") or int_get(vm_summary, "blocked_surfaces"),
            "blocked_services": int_get(state_summary, "blocked_service_count") or int_get(vm_summary, "blocked_services"),
            "mail_blockers": int_get(mail_summary, "blocker_count"),
            "mail_warnings": int_get(mail_summary, "warning_count"),
            "daily_notes": int_get(evidence_summary, "daily_note_count"),
            "missing_days": int_get(evidence_summary, "missing_day_count"),
            "secret_pattern_files": int_get(evidence_summary, "secret_pattern_file_count"),
        },
        "blockers": blockers,
        "warnings": warnings,
        "phases": phases,
        "actions": current_actions,
        "daily_ritual": daily_ritual,
        "acceptance": acceptance,
        "do_not": do_not,
        "hard_stops": hard_stops,
        "manual_inputs_required": [
            "Cloudflare R2 endpoint/account or endpoint URL",
            "R2 bucket name for control-plane restic",
            "R2 access key ID with scoped object access",
            "R2 secret access key with scoped object access",
            "Restic repository password or password file",
        ],
        "verify_sequence": [
            "nomarh-operator-card --refresh --json",
            "control-plane-r2-secure-input-packet --json",
            "control-plane-r2-remote-config --json",
            "control-plane-restic-backup --json",
            "control-plane-restic-restore-drill --json",
            "nomarh-vm-structure-map --json",
            "nomarh-operations-roadmap --json",
            "nomarh-cutover-guard --json",
        ],
        "paths": {
            "status": str(STATUS_PATH),
            "report": str(REPORT_PATH),
            "operator_card": str(OPERATOR_CARD_STATUS),
            "ops": str(OPS_STATUS),
            "vm_structure": str(VM_STRUCTURE_STATUS),
            "action_pack": str(ACTION_PACK_STATUS),
            "guarded_apply": str(GUARDED_APPLY_STATUS),
            "cutover_guard": str(CUTOVER_GUARD_STATUS),
            "migration_readiness": str(MIGRATION_READINESS_STATUS),
            "state_transfer": str(STATE_TRANSFER_STATUS),
            "service_map": str(SERVICE_MAP_STATUS),
            "runtime_board": str(RUNTIME_BOARD_STATUS),
            "mail_gate": str(MAIL_GATE_STATUS),
            "ops_evidence": str(OPS_EVIDENCE_STATUS),
            "r2_secure_packet": str(R2_PACKET_STATUS),
            "r2_remote_config": str(R2_REMOTE_STATUS),
            "r2_bootstrap": str(R2_BOOTSTRAP_STATUS),
            "restic_backup": str(RESTIC_BACKUP_STATUS),
            "restore_drill": str(RESTORE_DRILL_STATUS),
            "hetzner_hardening": str(HETZNER_HARDENING_STATUS),
            "hardening_bundle": str(HARDENING_BUNDLE_STATUS),
        },
    }


def render_action_table(actions: list[dict[str, Any]]) -> list[str]:
    lines = ["| Phase | Priority | Lane | Title | Status | Allowed Now | Verify |", "|---|---|---|---|---|---|---|"]
    for item in actions:
        lines.append(
            f"| `{safe_md(item['phase'])}` | `{safe_md(item['priority'])}` | `{safe_md(item['lane'])}` | {safe_md(item['title'])} | `{safe_md(item['status'])}` | `{safe_md(item['allowed_now'])}` | `{safe_md(item['verify'])}` |"
        )
    return lines


def render_phase_table(phases: list[dict[str, Any]]) -> list[str]:
    lines = ["| Order | Phase | Status | Goal | Exit Gate |", "|---:|---|---|---|---|"]
    for item in phases:
        lines.append(
            f"| {safe_md(item['order'])} | {safe_md(item['title'])} | `{safe_md(item['status'])}` | {safe_md(item['goal'])} | {safe_md(item['exit_gate'])} |"
        )
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    now = payload["now"]
    lines = [
        "# Nomarh Operations Roadmap",
        "",
        "No secrets, env values, tmux pane output, private keys, mailbox contents, or remote command bodies are read. This roadmap aggregates generated status JSON and daily/vault evidence.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Phases: `{summary['phase_count']}`",
        f"- Actions: `{summary['action_count']}`",
        f"- Blockers: `{summary['blocker_count']}`",
        f"- Warnings: `{summary['warning_count']}`",
        f"- Hard stops: `{summary['hard_stop_count']}`",
        f"- Backup ready: `{summary['backup_ready']}`; active r2 `{summary['r2_active']}`; missing groups `{summary['r2_missing_groups']}`",
        f"- State ready: `{summary['state_ready']}`; blocked surfaces `{summary['blocked_surfaces']}`; blocked services `{summary['blocked_services']}`",
        f"- Mail ready: `{summary['mail_ready']}`; blockers `{summary['mail_blockers']}`; warnings `{summary['mail_warnings']}`",
        f"- Runtime: tmux `{summary['tmux_total']}`, providers `{summary['provider_workers']}`, services `{summary['service_count']}`, P0/P1 `{summary['p0_count']}`/`{summary['p1_count']}`",
        "",
        "## Now",
        "",
        f"- Lane: `{safe_md(now['lane'])}`",
        f"- Task: **{safe_md(now['title'])}**",
        f"- Status: `{safe_md(now['status'])}`",
        f"- Next action: {safe_md(now['next_action'])}",
        f"- Verify: `{safe_md(now['verify'])}`",
        f"- Reason: {safe_md(now['reason'])}",
        "",
    ]

    if payload["blockers"]:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["blockers"])
        lines.append("")
    if payload["warnings"]:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["warnings"])
        lines.append("")

    lines.extend(["## Phases", ""])
    lines.extend(render_phase_table(payload["phases"]))
    lines.extend(["", "## Current Actions", ""])
    lines.extend(render_action_table(payload["actions"]))

    lines.extend(["", "## Daily Ritual", "", "| Slot | Command | Purpose |", "|---|---|---|"])
    for item in payload["daily_ritual"]:
        lines.append(f"| `{safe_md(item['slot'])}` | `{safe_md(item['command'])}` | {safe_md(item['purpose'])} |")

    lines.extend(["", "## Acceptance", ""])
    lines.extend(f"- {safe_md(item)}" for item in payload["acceptance"])

    lines.extend(["", "## Manual Inputs Required", ""])
    lines.extend(f"- {safe_md(item)}" for item in payload["manual_inputs_required"])

    lines.extend(["", "## Do Not", ""])
    if payload["do_not"]:
        lines.extend(f"- {safe_md(item)}" for item in payload["do_not"])
    else:
        lines.append("- No do-not rules listed.")

    lines.extend(["", "## Verify Sequence", ""])
    lines.extend(f"{idx}. `{safe_md(command)}`" for idx, command in enumerate(payload["verify_sequence"], start=1))

    lines.extend(["", "## Source Paths", ""])
    for key, path in payload["paths"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def render_console(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    now = payload["now"]
    return "\n".join(
        [
            "Nomarh Operations Roadmap",
            f"Result: {payload['result']}",
            f"Now: {now['title']} [{now['lane']}/{now['status']}]",
            f"Verify: {now['verify']}",
            f"Backup: ready={summary['backup_ready']} active_r2={summary['r2_active']} missing_groups={summary['r2_missing_groups']}",
            f"State: ready={summary['state_ready']} blocked_surfaces={summary['blocked_surfaces']} blocked_services={summary['blocked_services']}",
            f"Mail: ready={summary['mail_ready']} blockers={summary['mail_blockers']} warnings={summary['mail_warnings']}",
            f"Runtime: services={summary['service_count']} p0={summary['p0_count']} p1={summary['p1_count']} tmux={summary['tmux_total']} providers={summary['provider_workers']}",
            f"Report: {REPORT_PATH}",
            f"Status: {STATUS_PATH}",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the no-secret Nomarh operations roadmap")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_payload()
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_console(payload))
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

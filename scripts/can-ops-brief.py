#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/can-ops-brief"
STATUS_PATH = STATE_DIR / "status.json"
BRIEF_PATH = STATE_DIR / "brief.md"
CAN_DOCTOR_STATUS = Path(os.environ.get("CAN_OPS_CAN_DOCTOR_STATUS") or HOME / ".local/state/can-doctor/status.json")
RUNTIME_DASHBOARD_STATUS = Path(
    os.environ.get("CAN_OPS_RUNTIME_DASHBOARD_STATUS")
    or HOME / ".local/state/control-plane-runtime-dashboard/status.json"
)
TMUX_CLEANUP_STATUS = Path(
    os.environ.get("CAN_OPS_TMUX_CLEANUP_STATUS")
    or HOME / ".local/state/tmux-cleanup-review/status.json"
)
BACKUP_READINESS_STATUS = Path(
    os.environ.get("CAN_OPS_BACKUP_READINESS_STATUS")
    or HOME / ".local/state/control-plane-backup-readiness/status.json"
)
R2_RESTIC_INTAKE_STATUS = Path(
    os.environ.get("CAN_OPS_R2_RESTIC_INTAKE_STATUS")
    or HOME / ".local/state/control-plane-r2-restic-intake/status.json"
)
R2_SECURE_INPUT_PACKET_STATUS = Path(
    os.environ.get("CAN_OPS_R2_SECURE_INPUT_PACKET_STATUS")
    or HOME / ".local/state/control-plane-r2-secure-input-packet/status.json"
)
R2_REMOTE_CONFIG_STATUS = Path(
    os.environ.get("CAN_OPS_R2_REMOTE_CONFIG_STATUS")
    or HOME / ".local/state/control-plane-r2-remote-config/status.json"
)
R2_RESTIC_BOOTSTRAP_STATUS = Path(
    os.environ.get("CAN_OPS_R2_RESTIC_BOOTSTRAP_STATUS")
    or HOME / ".local/state/control-plane-r2-restic-bootstrap/status.json"
)
RESTIC_BACKUP_STATUS = Path(
    os.environ.get("CAN_OPS_RESTIC_BACKUP_STATUS")
    or HOME / ".local/state/control-plane-restic-backup/status.json"
)
SECRET_ROTATION_STATUS = Path(
    os.environ.get("CAN_OPS_SECRET_ROTATION_STATUS")
    or HOME / ".local/state/nomarh-secret-rotation-plan/status.json"
)
HARDENING_COMMAND_BUNDLE_STATUS = Path(
    os.environ.get("CAN_OPS_HARDENING_COMMAND_BUNDLE_STATUS")
    or HOME / ".local/state/hetzner-hardening-command-bundle/status.json"
)
SUPERVISION_UNIT_BUNDLE_STATUS = Path(
    os.environ.get("CAN_OPS_SUPERVISION_UNIT_BUNDLE_STATUS")
    or HOME / ".local/state/nomarh-supervision-unit-bundle/status.json"
)
RUNTIME_STABILIZATION_STATUS = Path(
    os.environ.get("CAN_OPS_RUNTIME_STABILIZATION_STATUS")
    or HOME / ".local/state/nomarh-runtime-stabilization-board/status.json"
)
ACTION_PACK_STATUS = Path(
    os.environ.get("CAN_OPS_ACTION_PACK_STATUS")
    or HOME / ".local/state/nomarh-action-pack/status.json"
)
VM_STRUCTURE_MAP_STATUS = Path(
    os.environ.get("CAN_OPS_VM_STRUCTURE_MAP_STATUS")
    or HOME / ".local/state/nomarh-vm-structure-map/status.json"
)
OPERATIONS_ROADMAP_STATUS = Path(
    os.environ.get("CAN_OPS_OPERATIONS_ROADMAP_STATUS")
    or HOME / ".local/state/nomarh-operations-roadmap/status.json"
)
GUARDED_APPLY_READINESS_STATUS = Path(
    os.environ.get("CAN_OPS_GUARDED_APPLY_READINESS_STATUS")
    or HOME / ".local/state/nomarh-guarded-apply-readiness/status.json"
)
GUARDED_ACTION_AUDIT_STATUS = Path(
    os.environ.get("CAN_OPS_GUARDED_ACTION_AUDIT_STATUS")
    or HOME / ".local/state/nomarh-guarded-action-audit/status.json"
)
MIGRATION_STATE_MANIFEST_STATUS = Path(
    os.environ.get("CAN_OPS_MIGRATION_STATE_MANIFEST_STATUS")
    or HOME / ".local/state/nomarh-migration-state-manifest/manifest.json"
)
STATE_TRANSFER_PLAN_STATUS = Path(
    os.environ.get("CAN_OPS_STATE_TRANSFER_PLAN_STATUS")
    or HOME / ".local/state/nomarh-state-transfer-plan/status.json"
)
MAIL_PRODUCTION_GATE_STATUS = Path(
    os.environ.get("CAN_OPS_MAIL_PRODUCTION_GATE_STATUS")
    or HOME / ".local/state/nomarh-mail-production-gate/status.json"
)
OPS_EVIDENCE_DIGEST_STATUS = Path(
    os.environ.get("CAN_OPS_EVIDENCE_DIGEST_STATUS")
    or HOME / ".local/state/nomarh-ops-evidence-digest/status.json"
)
OBJECTIVE_COVERAGE_STATUS = Path(
    os.environ.get("CAN_OPS_OBJECTIVE_COVERAGE_STATUS")
    or HOME / ".local/state/nomarh-objective-coverage/status.json"
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


def run_quiet(args: list[str], timeout: int = 90) -> dict[str, Any]:
    if not shutil.which(args[0]):
        return {"command": args[0], "returncode": 127, "stderr_tail": "command not found"}
    try:
        proc = subprocess.run(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        return {
            "command": " ".join(args),
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-500:],
            "stderr_tail": proc.stderr[-500:],
        }
    except Exception as exc:
        return {"command": " ".join(args), "returncode": 1, "stderr_tail": str(exc)}


def check_status_age(label: str, status: Any, warnings: list[str], *, max_age_hours: float = 2.0) -> None:
    if not isinstance(status, dict):
        warnings.append(f"{label} status missing")
        return
    age = age_hours(status.get("updated_at"))
    if age is None:
        warnings.append(f"{label} status has no valid updated_at")
    elif age > max_age_hours:
        warnings.append(f"{label} status is stale: {age:.1f}h old")


def warning_checks(can_doctor: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(can_doctor, dict):
        return []
    checks = can_doctor.get("checks") if isinstance(can_doctor.get("checks"), list) else []
    return [
        {
            "category": str(check.get("category", "")),
            "label": str(check.get("label", "")),
            "detail": str(check.get("detail", "")),
            "status": str(check.get("status", "")),
        }
        for check in checks
        if isinstance(check, dict) and check.get("status") in {"warn", "fail"}
    ]


def top_priorities(
    can_doctor: dict[str, Any] | None,
    runtime: dict[str, Any] | None,
    cleanup: dict[str, Any] | None,
    readiness: dict[str, Any] | None,
    intake: dict[str, Any] | None,
    remote_config: dict[str, Any] | None,
    bootstrap: dict[str, Any] | None,
    restic: dict[str, Any] | None,
    runtime_stabilization: dict[str, Any] | None,
    state_transfer: dict[str, Any] | None,
    mail_gate: dict[str, Any] | None,
    secret_rotation: dict[str, Any] | None,
    vm_structure_map: dict[str, Any] | None,
    operations_roadmap: dict[str, Any] | None,
    guarded_apply_readiness: dict[str, Any] | None,
    objective_coverage: dict[str, Any] | None,
) -> list[str]:
    priorities: list[str] = []
    intake_blockers = intake.get("blockers") if isinstance(intake, dict) else []
    remote_config_summary = remote_config.get("summary") if isinstance(remote_config, dict) else {}
    remote_config_blockers = (
        int(remote_config_summary.get("blocker_count", 0) or 0) if isinstance(remote_config_summary, dict) else 0
    )
    bootstrap_blockers = bootstrap.get("blockers") if isinstance(bootstrap, dict) else []
    restic_blockers = restic.get("blockers") if isinstance(restic, dict) else []
    readiness_blockers = readiness.get("blockers") if isinstance(readiness, dict) else []
    runtime_actions = runtime.get("next_actions") if isinstance(runtime, dict) else []
    cleanup_summary = cleanup.get("summary") if isinstance(cleanup, dict) and isinstance(cleanup.get("summary"), dict) else {}
    runtime_stabilization_summary = (
        runtime_stabilization.get("summary")
        if isinstance(runtime_stabilization, dict) and isinstance(runtime_stabilization.get("summary"), dict)
        else {}
    )
    state_transfer_summary = (
        state_transfer.get("summary")
        if isinstance(state_transfer, dict) and isinstance(state_transfer.get("summary"), dict)
        else {}
    )
    mail_gate_summary = (
        mail_gate.get("summary")
        if isinstance(mail_gate, dict) and isinstance(mail_gate.get("summary"), dict)
        else {}
    )
    secret_summary = secret_rotation.get("summary") if isinstance(secret_rotation, dict) else {}
    vm_structure_summary = (
        vm_structure_map.get("summary")
        if isinstance(vm_structure_map, dict) and isinstance(vm_structure_map.get("summary"), dict)
        else {}
    )
    roadmap_summary = (
        operations_roadmap.get("summary")
        if isinstance(operations_roadmap, dict) and isinstance(operations_roadmap.get("summary"), dict)
        else {}
    )
    guarded_apply_summary = (
        guarded_apply_readiness.get("summary")
        if isinstance(guarded_apply_readiness, dict) and isinstance(guarded_apply_readiness.get("summary"), dict)
        else {}
    )
    objective_summary = (
        objective_coverage.get("summary")
        if isinstance(objective_coverage, dict) and isinstance(objective_coverage.get("summary"), dict)
        else {}
    )

    if remote_config_blockers or intake_blockers:
        priorities.append("Open `control-plane-r2-secure-input-packet --json`: collect the missing R2/restic inputs through the secure path, then configure the real active `r2:` remote.")
    if remote_config_blockers:
        priorities.append("Complete `control-plane-r2-remote-config --json`: configure the real active `r2:` remote from secure R2/restic inputs.")
    if intake_blockers:
        priorities.append("Complete `control-plane-r2-restic-intake --json`: fill secure R2/restic inputs and configure active `r2:`.")
    if bootstrap_blockers:
        priorities.append("Resolve `control-plane-r2-restic-bootstrap --json`: provide scoped R2/restic inputs and configure active `r2:`.")
    if restic_blockers:
        priorities.append("Configure scoped R2/restic credentials, then run `control-plane-restic-backup --init --dry-run`.")
    if readiness_blockers:
        priorities.append("Resolve backup readiness blocker: active `r2:` remote is missing.")
    if isinstance(mail_gate, dict) and str(mail_gate.get("result", "missing")) != "ready":
        priorities.append(
            "Resolve mail production gate before MX/outbound cutover: "
            f"{int(mail_gate_summary.get('blocker_count', 0) or 0)} blocker(s), "
            f"{int(mail_gate_summary.get('warning_count', 0) or 0)} warning(s), "
            f"MX aligned `{bool(mail_gate_summary.get('mx_points_to_mailhost', False))}`, "
            f"SPF aligned `{bool(mail_gate_summary.get('spf_authorizes_mailhost', False))}`."
        )
    if isinstance(secret_summary, dict) and int(secret_summary.get("risky_doc_or_source_files", 0) or 0):
        priorities.append("Rotate and redact secrets detected in vault/source before copying state or cutting over AWS/main.")
    if isinstance(vm_structure_map, dict) and str(vm_structure_map.get("result", "missing")) != "ready":
        next_safe = vm_structure_map.get("next_safe_thing")
        verify = next_safe.get("verify") if isinstance(next_safe, dict) else "nomarh-vm-structure-map --json"
        title = next_safe.get("title") if isinstance(next_safe, dict) else "Review VM structure map"
        priorities.append(
            "Use VM structure map before service migration: "
            f"{title}; verify `{verify}`; "
            f"services {int(vm_structure_summary.get('service_count', 0) or 0)}, "
            f"blocked surfaces {int(vm_structure_summary.get('blocked_surfaces', 0) or 0)}, "
            f"hard stops {int(vm_structure_summary.get('cutover_hard_stops', 0) or 0)}."
        )
    if isinstance(operations_roadmap, dict) and str(operations_roadmap.get("result", "missing")) != "ready":
        now = operations_roadmap.get("now")
        verify = now.get("verify") if isinstance(now, dict) else "nomarh-operations-roadmap --json"
        title = now.get("title") if isinstance(now, dict) else "Review operations roadmap"
        priorities.append(
            "Follow operations roadmap now item: "
            f"{title}; verify `{verify}`; "
            f"blockers {int(roadmap_summary.get('blocker_count', 0) or 0)}, "
            f"warnings {int(roadmap_summary.get('warning_count', 0) or 0)}."
        )
    if isinstance(guarded_apply_readiness, dict) and str(guarded_apply_readiness.get("result", "missing")) != "ready":
        next_safe = guarded_apply_readiness.get("next_safe_thing")
        command = next_safe.get("command") if isinstance(next_safe, dict) else "nomarh-guarded-apply-readiness --json"
        title = next_safe.get("title") if isinstance(next_safe, dict) else "Review guarded apply readiness"
        priorities.append(
            "Use guarded apply readiness before running any gated script: "
            f"{title}; command `{command}`; "
            f"gate blockers {int(guarded_apply_summary.get('gate_blocker_count', 0) or 0)}, "
            f"hard stops {int(guarded_apply_summary.get('hard_stop_count', 0) or 0)}."
        )
    if isinstance(objective_coverage, dict) and str(objective_coverage.get("result", "missing")) not in {"covered", "ready"}:
        next_action = objective_coverage.get("next_action")
        title = next_action.get("title") if isinstance(next_action, dict) else "Review objective coverage"
        verify = next_action.get("verify") if isinstance(next_action, dict) else "nomarh-objective-coverage --json"
        priorities.append(
            "Check objective coverage: "
            f"{title}; verify `{verify}`; "
            f"covered {int(objective_summary.get('covered_count', 0) or 0)}/"
            f"{int(objective_summary.get('requirement_count', 0) or 0)}, "
            f"implementation blockers {int(objective_summary.get('implementation_blocked_count', 0) or 0)}."
        )
    if int(cleanup_summary.get("candidate_count", 0) or 0):
        priorities.append(
            "Review "
            f"{int(cleanup_summary.get('candidate_count', 0) or 0)} tmux cleanup candidates via `tmux-cleanup-review --json`: "
            f"{int(cleanup_summary.get('review_high_count', 0) or 0)} high, "
            f"{int(cleanup_summary.get('review_medium_count', 0) or 0)} medium, "
            f"{int(cleanup_summary.get('stop_candidate_count', 0) or 0)} stop candidates."
        )
    if int(runtime_stabilization_summary.get("action_count", 0) or 0):
        priorities.append(
            "Review runtime stabilization board: "
            f"{int(runtime_stabilization_summary.get('tmux_review_count', 0) or 0)} tmux handoff(s), "
            f"{int(runtime_stabilization_summary.get('decision_needed_count', 0) or 0)} decision(s), "
            f"{int(runtime_stabilization_summary.get('ready_spec_count', 0) or 0)} ready systemd spec(s)."
        )
    if int(state_transfer_summary.get("blocked_surface_count", 0) or 0) or int(
        state_transfer_summary.get("blocked_service_count", 0) or 0
    ):
        priorities.append(
            "Review state transfer plan: "
            f"{int(state_transfer_summary.get('blocked_surface_count', 0) or 0)} blocked surface(s), "
            f"{int(state_transfer_summary.get('blocked_service_count', 0) or 0)} blocked service(s), "
            f"{int(state_transfer_summary.get('cleanup_handoff_count', 0) or 0)} cleanup handoff(s)."
        )
    for check in warning_checks(can_doctor):
        if check["label"] == "Hetzner SSH":
            priorities.append("Fix Hetzner SSH key access before moving Coder and vault services.")
        elif check["label"] == "Hetzner hardening preflight":
            priorities.append("Harden Hetzner: create a non-root sudo admin, activate firewall policy, and review exposed mail/service ports before cutover.")
        elif check["label"] == "Tmux cleanup candidates":
            priorities.append("Review tmux cleanup candidates before copying runtime state to Hetzner.")
        elif check["label"] == "tmux sprawl":
            priorities.append("Convert durable tmux loops to supervised services/timers before cutover.")

    if isinstance(runtime_actions, list):
        for action in runtime_actions:
            text = str(action)
            if text and text not in priorities:
                priorities.append(text)

    seen: set[str] = set()
    unique: list[str] = []
    for item in priorities:
        key = priority_key(item)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:8]


def priority_key(item: str) -> str:
    lowered = item.lower()
    if "control-plane-r2-restic-intake" in lowered:
        return "r2-restic-intake"
    if "control-plane-r2-remote-config" in lowered:
        return "r2-remote-config"
    if "r2/restic" in lowered or "scoped r2" in lowered or "restic credential" in lowered:
        return "r2-restic-credentials"
    if "backup-readiness" in lowered or "backup readiness" in lowered or "active `r2:`" in lowered:
        return "backup-readiness"
    if "rotate and redact" in lowered or "secrets detected" in lowered:
        return "secret-rotation"
    if "cleanup candidate" in lowered:
        return "tmux-cleanup"
    if "runtime stabilization board" in lowered:
        return "runtime-stabilization"
    if "state transfer plan" in lowered:
        return "state-transfer-plan"
    if "guarded apply readiness" in lowered:
        return "guarded-apply-readiness"
    if "vm structure map" in lowered:
        return "vm-structure-map"
    if "operations roadmap" in lowered:
        return "operations-roadmap"
    if "hetzner ssh" in lowered:
        return "hetzner-ssh"
    if "harden hetzner" in lowered or "non-root sudo" in lowered or "firewall policy" in lowered:
        return "hetzner-hardening"
    if "supervised services" in lowered or "tmux loops" in lowered:
        return "supervise-tmux"
    return lowered


def build_payload(refresh_results: list[dict[str, Any]]) -> dict[str, Any]:
    warnings: list[str] = []
    blockers: list[str] = []
    can_doctor = read_json(CAN_DOCTOR_STATUS)
    runtime = read_json(RUNTIME_DASHBOARD_STATUS)
    cleanup = read_json(TMUX_CLEANUP_STATUS)
    readiness = read_json(BACKUP_READINESS_STATUS)
    intake = read_json(R2_RESTIC_INTAKE_STATUS)
    secure_packet = read_json(R2_SECURE_INPUT_PACKET_STATUS)
    r2_remote_config = read_json(R2_REMOTE_CONFIG_STATUS)
    bootstrap = read_json(R2_RESTIC_BOOTSTRAP_STATUS)
    restic = read_json(RESTIC_BACKUP_STATUS)
    secret_rotation = read_json(SECRET_ROTATION_STATUS)
    hardening_bundle = read_json(HARDENING_COMMAND_BUNDLE_STATUS)
    supervision_bundle = read_json(SUPERVISION_UNIT_BUNDLE_STATUS)
    runtime_stabilization = read_json(RUNTIME_STABILIZATION_STATUS)
    guarded_action_audit = read_json(GUARDED_ACTION_AUDIT_STATUS)
    migration_state_manifest = read_json(MIGRATION_STATE_MANIFEST_STATUS)
    state_transfer = read_json(STATE_TRANSFER_PLAN_STATUS)
    mail_gate = read_json(MAIL_PRODUCTION_GATE_STATUS)
    ops_evidence_digest = read_json(OPS_EVIDENCE_DIGEST_STATUS)
    objective_coverage = read_json(OBJECTIVE_COVERAGE_STATUS)
    action_pack = read_json(ACTION_PACK_STATUS)
    vm_structure_map = read_json(VM_STRUCTURE_MAP_STATUS)
    operations_roadmap = read_json(OPERATIONS_ROADMAP_STATUS)
    guarded_apply_readiness = read_json(GUARDED_APPLY_READINESS_STATUS)

    check_status_age("can-doctor", can_doctor, warnings)
    check_status_age("runtime dashboard", runtime, warnings)
    check_status_age("tmux cleanup review", cleanup, warnings)
    check_status_age("backup readiness", readiness, warnings)
    check_status_age("R2/restic intake", intake, warnings)
    check_status_age("R2 secure input packet", secure_packet, warnings)
    check_status_age("R2 remote config", r2_remote_config, warnings)
    check_status_age("R2/restic bootstrap", bootstrap, warnings)
    check_status_age("restic backup", restic, warnings)
    check_status_age("secret rotation plan", secret_rotation, warnings)
    check_status_age("hardening command bundle", hardening_bundle, warnings)
    check_status_age("supervision unit bundle", supervision_bundle, warnings)
    check_status_age("runtime stabilization board", runtime_stabilization, warnings)
    check_status_age("guarded action audit", guarded_action_audit, warnings)
    check_status_age("migration state manifest", migration_state_manifest, warnings)
    check_status_age("state transfer plan", state_transfer, warnings)
    check_status_age("mail production gate", mail_gate, warnings)
    check_status_age("ops evidence digest", ops_evidence_digest, warnings)
    check_status_age("objective coverage", objective_coverage, warnings)
    check_status_age("action pack", action_pack, warnings)
    check_status_age("VM structure map", vm_structure_map, warnings)
    check_status_age("operations roadmap", operations_roadmap, warnings)
    check_status_age("guarded apply readiness", guarded_apply_readiness, warnings)

    doctor_warnings = warning_checks(can_doctor if isinstance(can_doctor, dict) else None)
    doctor_failures = [check for check in doctor_warnings if check["status"] == "fail"]
    if doctor_failures:
        blockers.append(f"can-doctor has {len(doctor_failures)} failure(s)")

    runtime_tmux = runtime.get("tmux") if isinstance(runtime, dict) and isinstance(runtime.get("tmux"), dict) else {}
    cleanup_summary = cleanup.get("summary") if isinstance(cleanup, dict) and isinstance(cleanup.get("summary"), dict) else {}
    readiness_blockers = readiness.get("blockers") if isinstance(readiness, dict) else []
    intake_blockers = intake.get("blockers") if isinstance(intake, dict) else []
    bootstrap_blockers = bootstrap.get("blockers") if isinstance(bootstrap, dict) else []
    restic_blockers = restic.get("blockers") if isinstance(restic, dict) else []
    secret_summary = secret_rotation.get("summary") if isinstance(secret_rotation, dict) else {}
    secret_risky_files = int(secret_summary.get("risky_doc_or_source_files", 0) or 0) if isinstance(secret_summary, dict) else 0
    hardening_bundle_summary = hardening_bundle.get("summary") if isinstance(hardening_bundle, dict) else {}
    supervision_bundle_summary = supervision_bundle.get("summary") if isinstance(supervision_bundle, dict) else {}
    runtime_stabilization_summary = (
        runtime_stabilization.get("summary")
        if isinstance(runtime_stabilization, dict) and isinstance(runtime_stabilization.get("summary"), dict)
        else {}
    )
    intake_summary = intake.get("summary") if isinstance(intake, dict) and isinstance(intake.get("summary"), dict) else {}
    secure_packet_summary = (
        secure_packet.get("summary")
        if isinstance(secure_packet, dict) and isinstance(secure_packet.get("summary"), dict)
        else {}
    )
    r2_remote_config_summary = (
        r2_remote_config.get("summary")
        if isinstance(r2_remote_config, dict) and isinstance(r2_remote_config.get("summary"), dict)
        else {}
    )
    action_summary = action_pack.get("summary") if isinstance(action_pack, dict) and isinstance(action_pack.get("summary"), dict) else {}
    vm_structure_summary = (
        vm_structure_map.get("summary")
        if isinstance(vm_structure_map, dict) and isinstance(vm_structure_map.get("summary"), dict)
        else {}
    )
    roadmap_summary = (
        operations_roadmap.get("summary")
        if isinstance(operations_roadmap, dict) and isinstance(operations_roadmap.get("summary"), dict)
        else {}
    )
    guarded_apply_summary = (
        guarded_apply_readiness.get("summary")
        if isinstance(guarded_apply_readiness, dict) and isinstance(guarded_apply_readiness.get("summary"), dict)
        else {}
    )
    guarded_audit_summary = (
        guarded_action_audit.get("summary")
        if isinstance(guarded_action_audit, dict) and isinstance(guarded_action_audit.get("summary"), dict)
        else {}
    )
    manifest_summary = (
        migration_state_manifest.get("summary")
        if isinstance(migration_state_manifest, dict) and isinstance(migration_state_manifest.get("summary"), dict)
        else {}
    )
    state_transfer_summary = (
        state_transfer.get("summary")
        if isinstance(state_transfer, dict) and isinstance(state_transfer.get("summary"), dict)
        else {}
    )
    mail_gate_summary = (
        mail_gate.get("summary")
        if isinstance(mail_gate, dict) and isinstance(mail_gate.get("summary"), dict)
        else {}
    )
    evidence_summary = (
        ops_evidence_digest.get("summary")
        if isinstance(ops_evidence_digest, dict) and isinstance(ops_evidence_digest.get("summary"), dict)
        else {}
    )
    objective_summary = (
        objective_coverage.get("summary")
        if isinstance(objective_coverage, dict) and isinstance(objective_coverage.get("summary"), dict)
        else {}
    )
    manifest_blockers = migration_state_manifest.get("blockers") if isinstance(migration_state_manifest, dict) else []
    if secret_risky_files:
        blockers.append(f"secret rotation plan has {secret_risky_files} risky doc/source file(s)")
    migration_warnings = [check for check in doctor_warnings if check["category"] == "migration"]

    result = (
        "blocked"
        if blockers or secret_risky_files
        else "warn"
        if warnings or doctor_warnings or readiness_blockers or intake_blockers or restic_blockers or manifest_blockers
        else "ok"
    )
    return {
        "schema": "can-ops-brief.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "paths": {
            "status": str(STATUS_PATH),
            "brief": str(BRIEF_PATH),
            "can_doctor": str(CAN_DOCTOR_STATUS),
            "runtime_dashboard": str(RUNTIME_DASHBOARD_STATUS),
            "tmux_cleanup": str(TMUX_CLEANUP_STATUS),
            "backup_readiness": str(BACKUP_READINESS_STATUS),
            "r2_restic_intake": str(R2_RESTIC_INTAKE_STATUS),
            "r2_secure_input_packet": str(R2_SECURE_INPUT_PACKET_STATUS),
            "r2_remote_config": str(R2_REMOTE_CONFIG_STATUS),
            "r2_restic_bootstrap": str(R2_RESTIC_BOOTSTRAP_STATUS),
            "restic_backup": str(RESTIC_BACKUP_STATUS),
            "secret_rotation": str(SECRET_ROTATION_STATUS),
            "hardening_command_bundle": str(HARDENING_COMMAND_BUNDLE_STATUS),
            "supervision_unit_bundle": str(SUPERVISION_UNIT_BUNDLE_STATUS),
            "runtime_stabilization": str(RUNTIME_STABILIZATION_STATUS),
            "guarded_action_audit": str(GUARDED_ACTION_AUDIT_STATUS),
            "migration_state_manifest": str(MIGRATION_STATE_MANIFEST_STATUS),
            "state_transfer_plan": str(STATE_TRANSFER_PLAN_STATUS),
            "mail_production_gate": str(MAIL_PRODUCTION_GATE_STATUS),
            "ops_evidence_digest": str(OPS_EVIDENCE_DIGEST_STATUS),
            "objective_coverage": str(OBJECTIVE_COVERAGE_STATUS),
            "action_pack": str(ACTION_PACK_STATUS),
            "vm_structure_map": str(VM_STRUCTURE_MAP_STATUS),
            "operations_roadmap": str(OPERATIONS_ROADMAP_STATUS),
            "guarded_apply_readiness": str(GUARDED_APPLY_READINESS_STATUS),
        },
        "blockers": blockers,
        "warnings": warnings,
        "refresh_results": refresh_results,
        "summary": {
            "can_doctor_result": can_doctor.get("result", "missing") if isinstance(can_doctor, dict) else "missing",
            "can_doctor_warning_count": len(doctor_warnings),
            "runtime_result": runtime.get("result", "missing") if isinstance(runtime, dict) else "missing",
            "tmux_total": runtime_tmux.get("total", "?"),
            "provider_worker_count": runtime_tmux.get("provider_worker_count", "?"),
            "cleanup_candidate_count": runtime_tmux.get("cleanup_candidate_count", "?"),
            "tmux_cleanup_result": cleanup.get("result", "missing") if isinstance(cleanup, dict) else "missing",
            "tmux_cleanup_review_high": int(cleanup_summary.get("review_high_count", 0) or 0),
            "tmux_cleanup_review_medium": int(cleanup_summary.get("review_medium_count", 0) or 0),
            "tmux_cleanup_stop_candidates": int(cleanup_summary.get("stop_candidate_count", 0) or 0),
            "backup_readiness_result": readiness.get("result", "missing") if isinstance(readiness, dict) else "missing",
            "backup_readiness_blockers": len(readiness_blockers) if isinstance(readiness_blockers, list) else 0,
            "r2_restic_intake_result": intake.get("result", "missing") if isinstance(intake, dict) else "missing",
            "r2_restic_intake_blockers": len(intake_blockers) if isinstance(intake_blockers, list) else 0,
            "r2_restic_intake_input_groups": int(intake_summary.get("present_required_input_groups", 0) or 0),
            "r2_restic_intake_required_groups": int(intake_summary.get("required_input_groups", 0) or 0),
            "r2_secure_input_packet_result": secure_packet.get("result", "missing")
            if isinstance(secure_packet, dict)
            else "missing",
            "r2_secure_input_missing_groups": int(secure_packet_summary.get("missing_required_input_groups", 0) or 0),
            "r2_secure_input_active_r2": bool(secure_packet_summary.get("active_r2_remote", False)),
            "r2_remote_config_result": r2_remote_config.get("result", "missing")
            if isinstance(r2_remote_config, dict)
            else "missing",
            "r2_remote_config_blockers": int(r2_remote_config_summary.get("blocker_count", 0) or 0),
            "r2_remote_config_active_r2": bool(r2_remote_config_summary.get("active_r2_after", False)),
            "r2_restic_bootstrap_result": bootstrap.get("result", "missing") if isinstance(bootstrap, dict) else "missing",
            "r2_restic_bootstrap_blockers": len(bootstrap_blockers) if isinstance(bootstrap_blockers, list) else 0,
            "restic_backup_result": restic.get("result", "missing") if isinstance(restic, dict) else "missing",
            "restic_backup_blockers": len(restic_blockers) if isinstance(restic_blockers, list) else 0,
            "secret_rotation_result": secret_rotation.get("result", "missing") if isinstance(secret_rotation, dict) else "missing",
            "secret_risky_doc_or_source_files": secret_risky_files,
            "secret_finding_files": int(secret_summary.get("finding_files", 0) or 0) if isinstance(secret_summary, dict) else 0,
            "hardening_bundle_result": hardening_bundle.get("result", "missing") if isinstance(hardening_bundle, dict) else "missing",
            "hardening_bundle_pending_actions": int(hardening_bundle_summary.get("pending_action_count", 0) or 0)
            if isinstance(hardening_bundle_summary, dict)
            else 0,
            "supervision_unit_bundle_result": supervision_bundle.get("result", "missing") if isinstance(supervision_bundle, dict) else "missing",
            "supervision_unit_bundle_generated_files": int(supervision_bundle_summary.get("generated_file_count", 0) or 0)
            if isinstance(supervision_bundle_summary, dict)
            else 0,
            "supervision_unit_bundle_ready_files": int(supervision_bundle_summary.get("ready_to_install_file_count", 0) or 0)
            if isinstance(supervision_bundle_summary, dict)
            else 0,
            "runtime_stabilization_result": runtime_stabilization.get("result", "missing")
            if isinstance(runtime_stabilization, dict)
            else "missing",
            "runtime_stabilization_actions": int(runtime_stabilization_summary.get("action_count", 0) or 0),
            "runtime_stabilization_tmux_handoffs": int(
                runtime_stabilization_summary.get("tmux_review_count", 0) or 0
            ),
            "runtime_stabilization_decisions": int(
                runtime_stabilization_summary.get("decision_needed_count", 0) or 0
            ),
            "runtime_stabilization_ready_specs": int(runtime_stabilization_summary.get("ready_spec_count", 0) or 0),
            "guarded_action_audit_result": guarded_action_audit.get("result", "missing")
            if isinstance(guarded_action_audit, dict)
            else "missing",
            "guarded_action_audit_actions": int(guarded_audit_summary.get("action_count", 0) or 0),
            "guarded_action_audit_blockers": int(guarded_audit_summary.get("blocker_count", 0) or 0),
            "migration_state_manifest_result": migration_state_manifest.get("result", "missing")
            if isinstance(migration_state_manifest, dict)
            else "missing",
            "migration_state_manifest_surfaces": int(manifest_summary.get("surface_count", 0) or 0),
            "migration_state_manifest_secret_surfaces": int(
                manifest_summary.get("secret_bearing_surface_count", 0) or 0
            ),
            "migration_state_manifest_services": int(manifest_summary.get("service_count", 0) or 0),
            "migration_state_manifest_blockers": len(manifest_blockers) if isinstance(manifest_blockers, list) else 0,
            "state_transfer_result": state_transfer.get("result", "missing")
            if isinstance(state_transfer, dict)
            else "missing",
            "state_transfer_blocked_surfaces": int(state_transfer_summary.get("blocked_surface_count", 0) or 0),
            "state_transfer_blocked_services": int(state_transfer_summary.get("blocked_service_count", 0) or 0),
            "state_transfer_pending_items": int(state_transfer_summary.get("pending_item_count", 0) or 0),
            "state_transfer_cleanup_handoffs": int(state_transfer_summary.get("cleanup_handoff_count", 0) or 0),
            "state_transfer_backup_ready": bool(state_transfer_summary.get("backup_ready", False)),
            "mail_production_gate_result": mail_gate.get("result", "missing")
            if isinstance(mail_gate, dict)
            else "missing",
            "mail_production_blockers": int(mail_gate_summary.get("blocker_count", 0) or 0),
            "mail_production_warnings": int(mail_gate_summary.get("warning_count", 0) or 0),
            "mail_production_mx_aligned": bool(mail_gate_summary.get("mx_points_to_mailhost", False)),
            "mail_production_spf_aligned": bool(mail_gate_summary.get("spf_authorizes_mailhost", False)),
            "mail_production_dkim_selectors": int(mail_gate_summary.get("dkim_selector_count", 0) or 0),
            "mail_production_port25_status": str(mail_gate_summary.get("port25_status", "missing")),
            "mail_production_cutover_ready": bool(mail_gate_summary.get("cutover_ready", False)),
            "ops_evidence_digest_result": ops_evidence_digest.get("result", "missing")
            if isinstance(ops_evidence_digest, dict)
            else "missing",
            "ops_evidence_daily_notes": int(evidence_summary.get("daily_note_count", 0) or 0),
            "ops_evidence_missing_days": int(evidence_summary.get("missing_day_count", 0) or 0),
            "ops_evidence_secret_pattern_files": int(evidence_summary.get("secret_pattern_file_count", 0) or 0),
            "objective_coverage_result": objective_coverage.get("result", "missing")
            if isinstance(objective_coverage, dict)
            else "missing",
            "objective_coverage_complete": bool(objective_coverage.get("coverage_complete", False))
            if isinstance(objective_coverage, dict)
            else False,
            "objective_implementation_ready": bool(objective_coverage.get("implementation_ready", False))
            if isinstance(objective_coverage, dict)
            else False,
            "objective_requirements": int(objective_summary.get("requirement_count", 0) or 0),
            "objective_covered": int(objective_summary.get("covered_count", 0) or 0),
            "objective_blocked": int(objective_summary.get("blocked_count", 0) or 0),
            "objective_missing": int(objective_summary.get("missing_count", 0) or 0),
            "objective_implementation_blocked": int(objective_summary.get("implementation_blocked_count", 0) or 0),
            "action_pack_result": action_pack.get("result", "missing") if isinstance(action_pack, dict) else "missing",
            "action_pack_external_blockers": int(action_summary.get("external_blocker_count", 0) or 0),
            "action_pack_safe_reviews": int(action_summary.get("safe_review_count", 0) or 0),
            "action_pack_guarded_actions": int(action_summary.get("guarded_action_count", 0) or 0),
            "vm_structure_map_result": vm_structure_map.get("result", "missing")
            if isinstance(vm_structure_map, dict)
            else "missing",
            "vm_structure_map_services": int(vm_structure_summary.get("service_count", 0) or 0),
            "vm_structure_map_p0": int(vm_structure_summary.get("p0_count", 0) or 0),
            "vm_structure_map_p1": int(vm_structure_summary.get("p1_count", 0) or 0),
            "vm_structure_map_blocked_surfaces": int(vm_structure_summary.get("blocked_surfaces", 0) or 0),
            "vm_structure_map_blocked_services": int(vm_structure_summary.get("blocked_services", 0) or 0),
            "vm_structure_map_hard_stops": int(vm_structure_summary.get("cutover_hard_stops", 0) or 0),
            "operations_roadmap_result": operations_roadmap.get("result", "missing")
            if isinstance(operations_roadmap, dict)
            else "missing",
            "operations_roadmap_phases": int(roadmap_summary.get("phase_count", 0) or 0),
            "operations_roadmap_blockers": int(roadmap_summary.get("blocker_count", 0) or 0),
            "operations_roadmap_warnings": int(roadmap_summary.get("warning_count", 0) or 0),
            "operations_roadmap_now": (
                operations_roadmap.get("now", {}).get("title", "")
                if isinstance(operations_roadmap, dict) and isinstance(operations_roadmap.get("now"), dict)
                else ""
            ),
            "guarded_apply_readiness_result": guarded_apply_readiness.get("result", "missing")
            if isinstance(guarded_apply_readiness, dict)
            else "missing",
            "guarded_apply_readiness_can_run": bool(
                guarded_apply_readiness.get("can_run_guarded_actions", False)
            )
            if isinstance(guarded_apply_readiness, dict)
            else False,
            "guarded_apply_readiness_requires_input": int(guarded_apply_summary.get("requires_input_count", 0) or 0),
            "guarded_apply_readiness_gate_blockers": int(guarded_apply_summary.get("gate_blocker_count", 0) or 0),
            "guarded_apply_readiness_hard_stops": int(guarded_apply_summary.get("hard_stop_count", 0) or 0),
            "migration_warning_count": len(migration_warnings),
        },
        "warn_or_fail_checks": doctor_warnings,
        "top_priorities": top_priorities(
            can_doctor if isinstance(can_doctor, dict) else None,
            runtime if isinstance(runtime, dict) else None,
            cleanup if isinstance(cleanup, dict) else None,
            readiness if isinstance(readiness, dict) else None,
            intake if isinstance(intake, dict) else None,
            r2_remote_config if isinstance(r2_remote_config, dict) else None,
            bootstrap if isinstance(bootstrap, dict) else None,
            restic if isinstance(restic, dict) else None,
            runtime_stabilization if isinstance(runtime_stabilization, dict) else None,
            state_transfer if isinstance(state_transfer, dict) else None,
            mail_gate if isinstance(mail_gate, dict) else None,
            secret_rotation if isinstance(secret_rotation, dict) else None,
            vm_structure_map if isinstance(vm_structure_map, dict) else None,
            operations_roadmap if isinstance(operations_roadmap, dict) else None,
            guarded_apply_readiness if isinstance(guarded_apply_readiness, dict) else None,
            objective_coverage if isinstance(objective_coverage, dict) else None,
        ),
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Can Ops Brief",
        "",
        "No secret values are read or printed. This brief aggregates existing status JSON.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Can-doctor: `{summary['can_doctor_result']}` with {summary['can_doctor_warning_count']} warning/fail check(s)",
        f"- Runtime: `{summary['runtime_result']}`; tmux {summary['tmux_total']}, providers {summary['provider_worker_count']}, cleanup {summary['cleanup_candidate_count']}",
        f"- Tmux cleanup review: `{summary['tmux_cleanup_result']}`; high {summary['tmux_cleanup_review_high']}, medium {summary['tmux_cleanup_review_medium']}, stop {summary['tmux_cleanup_stop_candidates']}",
        f"- Backup readiness: `{summary['backup_readiness_result']}` with {summary['backup_readiness_blockers']} blocker(s)",
        f"- R2/restic intake: `{summary['r2_restic_intake_result']}` with {summary['r2_restic_intake_blockers']} blocker(s), input groups {summary['r2_restic_intake_input_groups']}/{summary['r2_restic_intake_required_groups']}",
        f"- R2 secure input packet: `{summary['r2_secure_input_packet_result']}` with missing groups {summary['r2_secure_input_missing_groups']}, active r2 `{summary['r2_secure_input_active_r2']}`",
        f"- R2 remote config: `{summary['r2_remote_config_result']}` with {summary['r2_remote_config_blockers']} blocker(s), active r2 `{summary['r2_remote_config_active_r2']}`",
        f"- R2/restic bootstrap: `{summary['r2_restic_bootstrap_result']}` with {summary['r2_restic_bootstrap_blockers']} blocker(s)",
        f"- Restic backup: `{summary['restic_backup_result']}` with {summary['restic_backup_blockers']} blocker(s)",
        f"- Secret rotation: `{summary['secret_rotation_result']}` with {summary['secret_risky_doc_or_source_files']} risky doc/source file(s)",
        f"- Hardening bundle: `{summary['hardening_bundle_result']}` with {summary['hardening_bundle_pending_actions']} pending action(s)",
        f"- Supervision unit bundle: `{summary['supervision_unit_bundle_result']}` with {summary['supervision_unit_bundle_generated_files']} generated file(s), {summary['supervision_unit_bundle_ready_files']} ready file(s)",
        f"- Runtime stabilization: `{summary['runtime_stabilization_result']}` with {summary['runtime_stabilization_actions']} action(s), {summary['runtime_stabilization_tmux_handoffs']} tmux handoff(s), {summary['runtime_stabilization_decisions']} decision(s), {summary['runtime_stabilization_ready_specs']} ready spec(s)",
        f"- Guarded action audit: `{summary['guarded_action_audit_result']}` with {summary['guarded_action_audit_actions']} action(s), {summary['guarded_action_audit_blockers']} blocker(s)",
        f"- Migration state manifest: `{summary['migration_state_manifest_result']}` with {summary['migration_state_manifest_surfaces']} surface(s), {summary['migration_state_manifest_secret_surfaces']} secret-bearing surface(s), {summary['migration_state_manifest_services']} service item(s), {summary['migration_state_manifest_blockers']} blocker(s)",
        f"- State transfer plan: `{summary['state_transfer_result']}` with {summary['state_transfer_blocked_surfaces']} blocked surface(s), {summary['state_transfer_blocked_services']} blocked service(s), {summary['state_transfer_pending_items']} pending item(s), backup ready `{summary['state_transfer_backup_ready']}`",
        f"- Mail production gate: `{summary['mail_production_gate_result']}` with {summary['mail_production_blockers']} blocker(s), {summary['mail_production_warnings']} warning(s), MX `{summary['mail_production_mx_aligned']}`, SPF `{summary['mail_production_spf_aligned']}`, DKIM selectors `{summary['mail_production_dkim_selectors']}`, port25 `{summary['mail_production_port25_status']}`",
        f"- Ops evidence digest: `{summary['ops_evidence_digest_result']}` with {summary['ops_evidence_daily_notes']} daily note(s), {summary['ops_evidence_missing_days']} missing day(s), {summary['ops_evidence_secret_pattern_files']} secret-pattern file(s)",
        f"- Objective coverage: `{summary['objective_coverage_result']}` complete `{summary['objective_coverage_complete']}`, implementation ready `{summary['objective_implementation_ready']}`, covered `{summary['objective_covered']}`/`{summary['objective_requirements']}`, missing `{summary['objective_missing']}`, blocked `{summary['objective_blocked']}`, implementation blockers `{summary['objective_implementation_blocked']}`",
        f"- Action pack: `{summary['action_pack_result']}` with {summary['action_pack_external_blockers']} external blocker(s), {summary['action_pack_safe_reviews']} safe review(s), {summary['action_pack_guarded_actions']} guarded action(s)",
        f"- VM structure map: `{summary['vm_structure_map_result']}` with services `{summary['vm_structure_map_services']}`, P0/P1 `{summary['vm_structure_map_p0']}`/`{summary['vm_structure_map_p1']}`, blocked surfaces `{summary['vm_structure_map_blocked_surfaces']}`, blocked services `{summary['vm_structure_map_blocked_services']}`, hard stops `{summary['vm_structure_map_hard_stops']}`",
        f"- Operations roadmap: `{summary['operations_roadmap_result']}` with phases `{summary['operations_roadmap_phases']}`, blockers `{summary['operations_roadmap_blockers']}`, warnings `{summary['operations_roadmap_warnings']}`, now `{safe_md(summary['operations_roadmap_now'])}`",
        f"- Guarded apply readiness: `{summary['guarded_apply_readiness_result']}` can run `{summary['guarded_apply_readiness_can_run']}`, requires input `{summary['guarded_apply_readiness_requires_input']}`, gate blockers `{summary['guarded_apply_readiness_gate_blockers']}`, hard stops `{summary['guarded_apply_readiness_hard_stops']}`",
        f"- Migration warnings: {summary['migration_warning_count']}",
        "",
    ]

    if payload["blockers"]:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {item}" for item in payload["blockers"])
        lines.append("")

    if payload["warnings"]:
        lines.extend(["## Status Freshness Warnings", ""])
        lines.extend(f"- {item}" for item in payload["warnings"])
        lines.append("")

    lines.extend(["## Top Priorities", ""])
    if payload["top_priorities"]:
        lines.extend(f"{idx}. {item}" for idx, item in enumerate(payload["top_priorities"], start=1))
    else:
        lines.append("- No priority generated. Run `can-doctor` and review manually.")

    lines.extend(["", "## Warning Checks", "", "| Category | Label | Detail |", "|---|---|---|"])
    for check in payload["warn_or_fail_checks"]:
        lines.append(f"| `{check['category']}` | `{check['label']}` | {safe_md(check['detail'])} |")
    if not payload["warn_or_fail_checks"]:
        lines.append("| none | none | none |")

    lines.extend(["", "## Source Paths", ""])
    for key, path in payload["paths"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def safe_md(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def refresh_statuses() -> list[dict[str, Any]]:
    # Order matters: can-doctor writes tmux inventory, runtime/service maps consume it, readiness summarizes the fresh state.
    commands = [
        ["control-plane-backup-readiness"],
        ["control-plane-r2-restic-intake", "--json"],
        ["control-plane-r2-secure-input-packet", "--json"],
        ["control-plane-r2-remote-config", "--json"],
        ["control-plane-r2-restic-bootstrap", "--json"],
        ["control-plane-restic-backup", "--json"],
        ["control-plane-restic-restore-drill", "--json"],
        ["nomarh-ops-evidence-digest", "--json"],
        ["hetzner-hardening-preflight", "--json"],
        ["hetzner-hardening-remediation", "--json"],
        ["hetzner-hardening-command-bundle", "--json"],
        ["nomarh-secret-rotation-plan", "--json"],
        ["can-doctor", "--json"],
        ["control-plane-runtime-dashboard"],
        ["tmux-cleanup-review", "--json"],
        ["nomarh-service-migration-map", "--json"],
        ["nomarh-supervision-plan", "--json"],
        ["nomarh-supervision-unit-bundle", "--json"],
        ["nomarh-runtime-stabilization-board", "--json"],
        ["can-doctor", "--json"],
        ["nomarh-mail-production-gate", "--json"],
        ["nomarh-migration-readiness", "--json"],
        ["nomarh-p0-execution-board", "--json"],
        ["nomarh-daily-ops-snapshot", "--json"],
        ["nomarh-cutover-guard", "--json"],
        ["nomarh-migration-state-manifest", "--json"],
        ["nomarh-state-transfer-plan", "--json"],
        ["nomarh-guarded-action-audit", "--json"],
        ["nomarh-action-pack", "--json"],
        ["nomarh-guarded-apply-readiness", "--json"],
        ["nomarh-vm-structure-map", "--json"],
        ["nomarh-operations-roadmap", "--json"],
        ["nomarh-objective-coverage", "--json"],
    ]
    return [run_quiet(command) for command in commands]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a no-secret daily operations brief")
    parser.add_argument("--refresh", action="store_true", help="refresh source status commands before building the brief")
    parser.add_argument("--json", action="store_true", help="print JSON payload")
    args = parser.parse_args()

    refresh_results = refresh_statuses() if args.refresh else []
    payload = build_payload(refresh_results)
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(BRIEF_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Can ops brief")
        print(f"Result: {payload['result']}")
        print(f"Top priorities: {len(payload['top_priorities'])}")
        print(f"Status: {STATUS_PATH}")
        print(f"Brief: {BRIEF_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

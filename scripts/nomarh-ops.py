#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-ops"
STATUS_PATH = STATE_DIR / "status.json"
SUMMARY_PATH = STATE_DIR / "summary.md"
HISTORY_PATH = STATE_DIR / "history.jsonl"

SNAPSHOT_STATUS = HOME / ".local/state/nomarh-daily-ops-snapshot/snapshot.json"
P0_BOARD_STATUS = HOME / ".local/state/nomarh-p0-execution-board/board.json"
BRIEF_STATUS = HOME / ".local/state/can-ops-brief/status.json"
MIGRATION_READINESS_STATUS = HOME / ".local/state/nomarh-migration-readiness/readiness.json"
R2_RESTIC_INTAKE_STATUS = HOME / ".local/state/control-plane-r2-restic-intake/status.json"
R2_SECURE_INPUT_PACKET_STATUS = HOME / ".local/state/control-plane-r2-secure-input-packet/status.json"
R2_REMOTE_CONFIG_STATUS = HOME / ".local/state/control-plane-r2-remote-config/status.json"
BOOTSTRAP_STATUS = HOME / ".local/state/control-plane-r2-restic-bootstrap/status.json"
RESTIC_BACKUP_STATUS = HOME / ".local/state/control-plane-restic-backup/status.json"
RESTORE_DRILL_STATUS = HOME / ".local/state/control-plane-restic-restore-drill/status.json"
HARDENING_STATUS = HOME / ".local/state/hetzner-hardening-preflight/status.json"
HARDENING_REMEDIATION_STATUS = HOME / ".local/state/hetzner-hardening-remediation/status.json"
HARDENING_COMMAND_BUNDLE_STATUS = HOME / ".local/state/hetzner-hardening-command-bundle/status.json"
SERVICE_MAP_STATUS = HOME / ".local/state/nomarh-service-migration-map/map.json"
SUPERVISION_PLAN_STATUS = HOME / ".local/state/nomarh-supervision-plan/plan.json"
SUPERVISION_UNIT_BUNDLE_STATUS = HOME / ".local/state/nomarh-supervision-unit-bundle/status.json"
RUNTIME_STABILIZATION_STATUS = HOME / ".local/state/nomarh-runtime-stabilization-board/status.json"
CUTOVER_GUARD_STATUS = HOME / ".local/state/nomarh-cutover-guard/guard.json"
CAN_DOCTOR_STATUS = HOME / ".local/state/can-doctor/status.json"
SECRET_ROTATION_STATUS = HOME / ".local/state/nomarh-secret-rotation-plan/status.json"
TMUX_CLEANUP_STATUS = HOME / ".local/state/tmux-cleanup-review/status.json"
ACTION_PACK_STATUS = HOME / ".local/state/nomarh-action-pack/status.json"
VM_STRUCTURE_MAP_STATUS = HOME / ".local/state/nomarh-vm-structure-map/status.json"
OPERATIONS_ROADMAP_STATUS = HOME / ".local/state/nomarh-operations-roadmap/status.json"
GUARDED_APPLY_READINESS_STATUS = HOME / ".local/state/nomarh-guarded-apply-readiness/status.json"
GUARDED_ACTION_AUDIT_STATUS = HOME / ".local/state/nomarh-guarded-action-audit/status.json"
MIGRATION_STATE_MANIFEST_STATUS = HOME / ".local/state/nomarh-migration-state-manifest/manifest.json"
STATE_TRANSFER_PLAN_STATUS = HOME / ".local/state/nomarh-state-transfer-plan/status.json"
MAIL_PRODUCTION_GATE_STATUS = HOME / ".local/state/nomarh-mail-production-gate/status.json"
OPS_EVIDENCE_DIGEST_STATUS = HOME / ".local/state/nomarh-ops-evidence-digest/status.json"
OBJECTIVE_COVERAGE_STATUS = HOME / ".local/state/nomarh-objective-coverage/status.json"


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


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def run_refresh(timeout: int) -> dict[str, Any]:
    if not shutil.which("can-ops-refresh"):
        return {
            "command": "can-ops-refresh --json",
            "returncode": 127,
            "duration_seconds": 0,
            "stderr_tail": "command not found: can-ops-refresh",
        }
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["can-ops-refresh", "--json"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return {
            "command": "can-ops-refresh --json",
            "returncode": 124,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout_tail": stdout[-500:],
            "stderr_tail": (stderr or f"timed out after {timeout}s")[-500:],
        }
    except Exception as exc:
        return {
            "command": "can-ops-refresh --json",
            "returncode": 1,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stderr_tail": str(exc)[-500:],
        }
    return {
        "command": "can-ops-refresh --json",
        "returncode": proc.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "stdout_tail": (proc.stdout or "")[-500:],
        "stderr_tail": (proc.stderr or "")[-500:],
    }


def result_rank(result: str) -> int:
    return {"ready": 0, "ok": 0, "success": 0, "warn": 1, "dry-run-ok": 1, "blocked": 2, "fail": 3, "missing": 3}.get(
        result,
        2,
    )


def overall_result(*results: str) -> str:
    worst = max((result_rank(item) for item in results), default=3)
    if worst >= 3:
        return "fail"
    if worst == 2:
        return "blocked"
    if worst == 1:
        return "warn"
    return "ready"


def list_len(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def dict_get(payload: Any, key: str, default: Any = None) -> Any:
    return payload.get(key, default) if isinstance(payload, dict) else default


def first_action(snapshot: Any) -> dict[str, Any]:
    today = dict_get(snapshot, "today", {})
    action = dict_get(today, "do_first", {})
    if isinstance(action, dict) and action:
        return {
            "title": str(action.get("title", "unknown")),
            "lane": str(action.get("lane", "unknown")),
            "status": str(action.get("status", "unknown")),
            "next_action": str(action.get("next_action", "")),
            "verify": str(action.get("verify", "")),
        }
    return {
        "title": "Run `nomarh-ops --refresh`",
        "lane": "setup",
        "status": "missing",
        "next_action": "Refresh daily operations status.",
        "verify": "nomarh-ops --refresh --json",
    }


def build_payload(refresh_result: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = read_json(SNAPSHOT_STATUS)
    p0 = read_json(P0_BOARD_STATUS)
    brief = read_json(BRIEF_STATUS)
    readiness = read_json(MIGRATION_READINESS_STATUS)
    intake = read_json(R2_RESTIC_INTAKE_STATUS)
    secure_packet = read_json(R2_SECURE_INPUT_PACKET_STATUS)
    r2_remote_config = read_json(R2_REMOTE_CONFIG_STATUS)
    bootstrap = read_json(BOOTSTRAP_STATUS)
    restic = read_json(RESTIC_BACKUP_STATUS)
    restore = read_json(RESTORE_DRILL_STATUS)
    hardening = read_json(HARDENING_STATUS)
    hardening_remediation = read_json(HARDENING_REMEDIATION_STATUS)
    hardening_bundle = read_json(HARDENING_COMMAND_BUNDLE_STATUS)
    service_map = read_json(SERVICE_MAP_STATUS)
    supervision = read_json(SUPERVISION_PLAN_STATUS)
    supervision_bundle = read_json(SUPERVISION_UNIT_BUNDLE_STATUS)
    runtime_stabilization = read_json(RUNTIME_STABILIZATION_STATUS)
    cutover = read_json(CUTOVER_GUARD_STATUS)
    doctor = read_json(CAN_DOCTOR_STATUS)
    secret_rotation = read_json(SECRET_ROTATION_STATUS)
    tmux_cleanup = read_json(TMUX_CLEANUP_STATUS)
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

    p0_summary = dict_get(p0, "summary", {})
    brief_summary = dict_get(brief, "summary", {})
    readiness_summary = dict_get(readiness, "summary", {})
    service_summary = dict_get(service_map, "summary", {})
    hardening_warnings = dict_get(hardening, "warnings", [])
    manifest_summary = dict_get(migration_state_manifest, "summary", {})
    state_transfer_summary = dict_get(state_transfer, "summary", {})
    mail_gate_summary = dict_get(mail_gate, "summary", {})
    evidence_summary = dict_get(ops_evidence_digest, "summary", {})
    objective_summary = dict_get(objective_coverage, "summary", {})
    vm_structure_summary = dict_get(vm_structure_map, "summary", {})
    roadmap_summary = dict_get(operations_roadmap, "summary", {})
    runtime_stabilization_summary = dict_get(runtime_stabilization, "summary", {})
    secure_packet_summary = dict_get(secure_packet, "summary", {})
    guarded_apply_summary = dict_get(guarded_apply_readiness, "summary", {})
    r2_remote_config_summary = dict_get(r2_remote_config, "summary", {})
    secret_summary = dict_get(secret_rotation, "summary", {})
    secret_risky_files = int(dict_get(secret_summary, "risky_doc_or_source_files", 0) or 0)
    secret_finding_files = int(dict_get(secret_summary, "finding_files", 0) or 0)
    doctor_checks = dict_get(doctor, "checks", [])
    warn_or_fail_checks = [
        {
            "category": str(item.get("category", "")),
            "label": str(item.get("label", "")),
            "status": str(item.get("status", "")),
            "detail": str(item.get("detail", "")),
        }
        for item in doctor_checks
        if isinstance(item, dict) and item.get("status") in {"warn", "fail"}
    ]

    do_not = dict_get(dict_get(snapshot, "today", {}), "do_not", [])
    verify_after_change = dict_get(dict_get(snapshot, "today", {}), "verify_after_change", [])
    top_priorities = dict_get(brief, "top_priorities", [])
    next_tasks = dict_get(p0, "next_tasks", [])

    source_results = {
        "snapshot": str(dict_get(snapshot, "result", "missing")),
        "p0_board": str(dict_get(p0, "result", "missing")),
        "brief": str(dict_get(brief, "result", "missing")),
        "migration_readiness": str(dict_get(readiness, "result", "missing")),
        "r2_restic_intake": str(dict_get(intake, "result", "missing")),
        "r2_secure_input_packet": str(dict_get(secure_packet, "result", "missing")),
        "r2_remote_config": str(dict_get(r2_remote_config, "result", "missing")),
        "r2_restic_bootstrap": str(dict_get(bootstrap, "result", "missing")),
        "restic_backup": str(dict_get(restic, "result", "missing")),
        "restore_drill": str(dict_get(restore, "result", "missing")),
        "hetzner_hardening": str(dict_get(hardening, "result", "missing")),
        "hetzner_hardening_remediation": str(dict_get(hardening_remediation, "result", "missing")),
        "hetzner_hardening_command_bundle": str(dict_get(hardening_bundle, "result", "missing")),
        "service_map": str(dict_get(service_map, "result", "missing")),
        "supervision_plan": str(dict_get(supervision, "result", "missing")),
        "supervision_unit_bundle": str(dict_get(supervision_bundle, "result", "missing")),
        "runtime_stabilization": str(dict_get(runtime_stabilization, "result", "missing")),
        "cutover_guard": str(dict_get(cutover, "result", "missing")),
        "can_doctor": str(dict_get(doctor, "result", "missing")),
        "secret_rotation": str(dict_get(secret_rotation, "result", "missing")),
        "tmux_cleanup": str(dict_get(tmux_cleanup, "result", "missing")),
        "guarded_action_audit": str(dict_get(guarded_action_audit, "result", "missing")),
        "migration_state_manifest": str(dict_get(migration_state_manifest, "result", "missing")),
        "state_transfer_plan": str(dict_get(state_transfer, "result", "missing")),
        "mail_production_gate": str(dict_get(mail_gate, "result", "missing")),
        "ops_evidence_digest": str(dict_get(ops_evidence_digest, "result", "missing")),
        "objective_coverage": str(dict_get(objective_coverage, "result", "missing")),
        "action_pack": str(dict_get(action_pack, "result", "missing")),
        "vm_structure_map": str(dict_get(vm_structure_map, "result", "missing")),
        "operations_roadmap": str(dict_get(operations_roadmap, "result", "missing")),
        "guarded_apply_readiness": str(dict_get(guarded_apply_readiness, "result", "missing")),
    }
    refresh_status = "success" if not refresh_result else "success" if refresh_result.get("returncode") == 0 else "fail"
    result = overall_result(
        source_results["snapshot"],
        source_results["p0_board"],
        source_results["r2_remote_config"],
        source_results["r2_restic_bootstrap"],
        source_results["runtime_stabilization"],
        source_results["migration_state_manifest"],
        source_results["state_transfer_plan"],
        source_results["mail_production_gate"],
        source_results["vm_structure_map"],
        source_results["operations_roadmap"],
        source_results["objective_coverage"],
        source_results["guarded_apply_readiness"],
        source_results["secret_rotation"],
        refresh_status,
    )

    return {
        "schema": "nomarh-ops.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "refresh": refresh_result,
        "do_first": first_action(snapshot),
        "do_not": [str(item) for item in do_not[:6]] if isinstance(do_not, list) else [],
        "top_priorities": [str(item) for item in top_priorities[:8]] if isinstance(top_priorities, list) else [],
        "next_tasks": next_tasks[:8] if isinstance(next_tasks, list) else [],
        "verify_after_change": [str(item) for item in verify_after_change[:8]] if isinstance(verify_after_change, list) else [],
        "summary": {
            "source_results": source_results,
            "p0_counts": p0_summary.get("counts", {}),
            "p0_task_count": p0_summary.get("task_count", "?"),
            "readiness_counts": {
                "ready": readiness_summary.get("ready", "?"),
                "warn": readiness_summary.get("warn", "?"),
                "blocked": readiness_summary.get("blocked", "?"),
            },
            "service_priority": service_summary.get("by_priority", {}),
            "service_risk": service_summary.get("by_risk", {}),
            "supervision_status_counts": dict_get(dict_get(supervision, "summary", {}), "status_counts", {}),
            "supervision_plan_count": dict_get(dict_get(supervision, "summary", {}), "plan_count", "?"),
            "supervision_unit_generated_files": int(
                dict_get(dict_get(supervision_bundle, "summary", {}), "generated_file_count", 0) or 0
            ),
            "supervision_unit_ready_files": int(
                dict_get(dict_get(supervision_bundle, "summary", {}), "ready_to_install_file_count", 0) or 0
            ),
            "runtime_stabilization_actions": int(dict_get(runtime_stabilization_summary, "action_count", 0) or 0),
            "runtime_stabilization_tmux_handoffs": int(
                dict_get(runtime_stabilization_summary, "tmux_review_count", 0) or 0
            ),
            "runtime_stabilization_decisions": int(
                dict_get(runtime_stabilization_summary, "decision_needed_count", 0) or 0
            ),
            "runtime_stabilization_ready_specs": int(
                dict_get(runtime_stabilization_summary, "ready_spec_count", 0) or 0
            ),
            "cutover_hard_stops": dict_get(dict_get(cutover, "summary", {}), "hard_stop_count", "?"),
            "cutover_warnings": dict_get(dict_get(cutover, "summary", {}), "warning_count", "?"),
            "tmux_total": brief_summary.get("tmux_total", "?"),
            "provider_worker_count": brief_summary.get("provider_worker_count", "?"),
            "cleanup_candidate_count": brief_summary.get("cleanup_candidate_count", "?"),
            "tmux_cleanup_review_high": int(
                dict_get(dict_get(tmux_cleanup, "summary", {}), "review_high_count", 0) or 0
            ),
            "tmux_cleanup_review_medium": int(
                dict_get(dict_get(tmux_cleanup, "summary", {}), "review_medium_count", 0) or 0
            ),
            "tmux_cleanup_stop_candidates": int(
                dict_get(dict_get(tmux_cleanup, "summary", {}), "stop_candidate_count", 0) or 0
            ),
            "action_pack_external_blockers": int(
                dict_get(dict_get(action_pack, "summary", {}), "external_blocker_count", 0) or 0
            ),
            "action_pack_safe_reviews": int(
                dict_get(dict_get(action_pack, "summary", {}), "safe_review_count", 0) or 0
            ),
            "action_pack_guarded_actions": int(
                dict_get(dict_get(action_pack, "summary", {}), "guarded_action_count", 0) or 0
            ),
            "vm_structure_map_result": source_results["vm_structure_map"],
            "vm_structure_map_services": int(dict_get(vm_structure_summary, "service_count", 0) or 0),
            "vm_structure_map_p0": int(dict_get(vm_structure_summary, "p0_count", 0) or 0),
            "vm_structure_map_p1": int(dict_get(vm_structure_summary, "p1_count", 0) or 0),
            "vm_structure_map_blocked_surfaces": int(dict_get(vm_structure_summary, "blocked_surfaces", 0) or 0),
            "vm_structure_map_blocked_services": int(dict_get(vm_structure_summary, "blocked_services", 0) or 0),
            "vm_structure_map_hard_stops": int(dict_get(vm_structure_summary, "cutover_hard_stops", 0) or 0),
            "operations_roadmap_result": source_results["operations_roadmap"],
            "operations_roadmap_phases": int(dict_get(roadmap_summary, "phase_count", 0) or 0),
            "operations_roadmap_blockers": int(dict_get(roadmap_summary, "blocker_count", 0) or 0),
            "operations_roadmap_warnings": int(dict_get(roadmap_summary, "warning_count", 0) or 0),
            "operations_roadmap_now": str(
                dict_get(dict_get(operations_roadmap, "now", {}), "title", "")
            ),
            "guarded_apply_readiness_result": source_results["guarded_apply_readiness"],
            "guarded_apply_readiness_can_run": bool(
                dict_get(guarded_apply_readiness, "can_run_guarded_actions", False)
            ),
            "guarded_apply_readiness_requires_input": int(
                dict_get(guarded_apply_summary, "requires_input_count", 0) or 0
            ),
            "guarded_apply_readiness_gate_blockers": int(
                dict_get(guarded_apply_summary, "gate_blocker_count", 0) or 0
            ),
            "guarded_apply_readiness_hard_stops": int(
                dict_get(guarded_apply_summary, "hard_stop_count", 0) or 0
            ),
            "guarded_action_audit_actions": int(
                dict_get(dict_get(guarded_action_audit, "summary", {}), "action_count", 0) or 0
            ),
            "guarded_action_audit_blockers": int(
                dict_get(dict_get(guarded_action_audit, "summary", {}), "blocker_count", 0) or 0
            ),
            "migration_state_manifest_surfaces": int(dict_get(manifest_summary, "surface_count", 0) or 0),
            "migration_state_manifest_secret_surfaces": int(
                dict_get(manifest_summary, "secret_bearing_surface_count", 0) or 0
            ),
            "migration_state_manifest_services": int(dict_get(manifest_summary, "service_count", 0) or 0),
            "migration_state_manifest_blockers": list_len(dict_get(migration_state_manifest, "blockers", [])),
            "state_transfer_blocked_surfaces": int(dict_get(state_transfer_summary, "blocked_surface_count", 0) or 0),
            "state_transfer_blocked_services": int(dict_get(state_transfer_summary, "blocked_service_count", 0) or 0),
            "state_transfer_pending_items": int(dict_get(state_transfer_summary, "pending_item_count", 0) or 0),
            "state_transfer_cleanup_handoffs": int(dict_get(state_transfer_summary, "cleanup_handoff_count", 0) or 0),
            "state_transfer_backup_ready": bool(dict_get(state_transfer_summary, "backup_ready", False)),
            "mail_production_blockers": int(dict_get(mail_gate_summary, "blocker_count", 0) or 0),
            "mail_production_warnings": int(dict_get(mail_gate_summary, "warning_count", 0) or 0),
            "mail_production_mx_aligned": bool(dict_get(mail_gate_summary, "mx_points_to_mailhost", False)),
            "mail_production_spf_aligned": bool(dict_get(mail_gate_summary, "spf_authorizes_mailhost", False)),
            "mail_production_dkim_selectors": int(dict_get(mail_gate_summary, "dkim_selector_count", 0) or 0),
            "mail_production_port25_status": str(dict_get(mail_gate_summary, "port25_status", "missing")),
            "mail_production_cutover_ready": bool(dict_get(mail_gate_summary, "cutover_ready", False)),
            "ops_evidence_daily_notes": int(dict_get(evidence_summary, "daily_note_count", 0) or 0),
            "ops_evidence_missing_days": int(dict_get(evidence_summary, "missing_day_count", 0) or 0),
            "ops_evidence_secret_pattern_files": int(dict_get(evidence_summary, "secret_pattern_file_count", 0) or 0),
            "ops_evidence_top_themes": dict_get(evidence_summary, "top_themes", []),
            "objective_coverage_result": source_results["objective_coverage"],
            "objective_coverage_complete": bool(dict_get(objective_coverage, "coverage_complete", False)),
            "objective_implementation_ready": bool(dict_get(objective_coverage, "implementation_ready", False)),
            "objective_requirements": int(dict_get(objective_summary, "requirement_count", 0) or 0),
            "objective_covered": int(dict_get(objective_summary, "covered_count", 0) or 0),
            "objective_blocked": int(dict_get(objective_summary, "blocked_count", 0) or 0),
            "objective_missing": int(dict_get(objective_summary, "missing_count", 0) or 0),
            "objective_implementation_blocked": int(dict_get(objective_summary, "implementation_blocked_count", 0) or 0),
            "r2_restic_intake_blockers": list_len(dict_get(intake, "blockers", [])),
            "r2_restic_intake_input_groups": int(
                dict_get(dict_get(intake, "summary", {}), "present_required_input_groups", 0) or 0
            ),
            "r2_restic_intake_required_groups": int(
                dict_get(dict_get(intake, "summary", {}), "required_input_groups", 0) or 0
            ),
            "r2_secure_input_missing_groups": int(dict_get(secure_packet_summary, "missing_required_input_groups", 0) or 0),
            "r2_secure_input_active_r2": bool(dict_get(secure_packet_summary, "active_r2_remote", False)),
            "r2_remote_config_blockers": int(dict_get(r2_remote_config_summary, "blocker_count", 0) or 0),
            "r2_remote_config_active_r2": bool(dict_get(r2_remote_config_summary, "active_r2_after", False)),
            "r2_restic_bootstrap_blockers": list_len(dict_get(bootstrap, "blockers", [])),
            "restic_backup_blockers": list_len(dict_get(restic, "blockers", [])),
            "restore_drill_blockers": list_len(dict_get(restore, "blockers", [])),
            "hetzner_hardening_warning_count": list_len(hardening_warnings),
            "hetzner_hardening_remediation_actions": list_len(dict_get(hardening_remediation, "actions", [])),
            "hetzner_hardening_bundle_pending_actions": int(
                dict_get(dict_get(hardening_bundle, "summary", {}), "pending_action_count", 0) or 0
            ),
            "can_doctor_warning_count": len(warn_or_fail_checks),
            "secret_rotation_result": source_results["secret_rotation"],
            "secret_finding_files": secret_finding_files,
            "secret_risky_doc_or_source_files": secret_risky_files,
            "secret_pattern_counts": dict_get(secret_summary, "pattern_counts", {}),
        },
        "warn_or_fail_checks": warn_or_fail_checks[:12],
        "paths": {
            "status": str(STATUS_PATH),
            "summary": str(SUMMARY_PATH),
            "snapshot": str(SNAPSHOT_STATUS),
            "p0_board": str(P0_BOARD_STATUS),
            "brief": str(BRIEF_STATUS),
            "migration_readiness": str(MIGRATION_READINESS_STATUS),
            "r2_restic_intake": str(R2_RESTIC_INTAKE_STATUS),
            "r2_secure_input_packet": str(R2_SECURE_INPUT_PACKET_STATUS),
            "r2_remote_config": str(R2_REMOTE_CONFIG_STATUS),
            "bootstrap": str(BOOTSTRAP_STATUS),
            "restic_backup": str(RESTIC_BACKUP_STATUS),
            "restore_drill": str(RESTORE_DRILL_STATUS),
            "hardening": str(HARDENING_STATUS),
            "hardening_remediation": str(HARDENING_REMEDIATION_STATUS),
            "hardening_command_bundle": str(HARDENING_COMMAND_BUNDLE_STATUS),
            "service_map": str(SERVICE_MAP_STATUS),
            "supervision_plan": str(SUPERVISION_PLAN_STATUS),
            "supervision_unit_bundle": str(SUPERVISION_UNIT_BUNDLE_STATUS),
            "runtime_stabilization": str(RUNTIME_STABILIZATION_STATUS),
            "cutover_guard": str(CUTOVER_GUARD_STATUS),
            "can_doctor": str(CAN_DOCTOR_STATUS),
            "secret_rotation": str(SECRET_ROTATION_STATUS),
            "tmux_cleanup": str(TMUX_CLEANUP_STATUS),
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
    }


def safe_md(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def compact_dict(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value)
    return ", ".join(f"{key}={value[key]}" for key in sorted(value))


def render_markdown(payload: dict[str, Any]) -> str:
    action = payload["do_first"]
    summary = payload["summary"]
    lines = [
        "# Nomarh Ops",
        "",
        "No secrets, env values, tmux pane output, private keys, or mailbox contents are read. This view aggregates existing status JSON.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        "",
        "## Do First",
        "",
        f"- Task: **{safe_md(action['title'])}**",
        f"- Lane: `{safe_md(action['lane'])}`",
        f"- Status: `{safe_md(action['status'])}`",
        f"- Next action: {safe_md(action['next_action'])}",
        f"- Verify: `{safe_md(action['verify'])}`",
        "",
        "## Current Shape",
        "",
        f"- P0 board: counts `{safe_md(summary['p0_counts'])}`, tasks `{safe_md(summary['p0_task_count'])}`",
        f"- Migration readiness: `{safe_md(summary['readiness_counts'])}`",
        f"- Services: priority `{safe_md(summary['service_priority'])}`, risk `{safe_md(summary['service_risk'])}`",
        f"- Supervision: plans `{safe_md(summary['supervision_plan_count'])}`, counts `{safe_md(summary['supervision_status_counts'])}`, unit files `{summary['supervision_unit_generated_files']}`, ready `{summary['supervision_unit_ready_files']}`",
        f"- Runtime stabilization: actions `{summary['runtime_stabilization_actions']}`, tmux handoffs `{summary['runtime_stabilization_tmux_handoffs']}`, decisions `{summary['runtime_stabilization_decisions']}`, ready specs `{summary['runtime_stabilization_ready_specs']}`",
        f"- Cutover guard: hard stops `{safe_md(summary['cutover_hard_stops'])}`, warnings `{safe_md(summary['cutover_warnings'])}`",
        f"- Runtime: tmux `{safe_md(summary['tmux_total'])}`, providers `{safe_md(summary['provider_worker_count'])}`, cleanup candidates `{safe_md(summary['cleanup_candidate_count'])}`; cleanup review high `{summary['tmux_cleanup_review_high']}`, medium `{summary['tmux_cleanup_review_medium']}`, stop `{summary['tmux_cleanup_stop_candidates']}`",
        f"- Action pack: external blockers `{summary['action_pack_external_blockers']}`, safe reviews `{summary['action_pack_safe_reviews']}`, guarded actions `{summary['action_pack_guarded_actions']}`",
        f"- VM structure map: `{summary['vm_structure_map_result']}`, services `{summary['vm_structure_map_services']}`, P0/P1 `{summary['vm_structure_map_p0']}`/`{summary['vm_structure_map_p1']}`, blocked surfaces `{summary['vm_structure_map_blocked_surfaces']}`, blocked services `{summary['vm_structure_map_blocked_services']}`, hard stops `{summary['vm_structure_map_hard_stops']}`",
        f"- Operations roadmap: `{summary['operations_roadmap_result']}`, phases `{summary['operations_roadmap_phases']}`, blockers `{summary['operations_roadmap_blockers']}`, warnings `{summary['operations_roadmap_warnings']}`, now `{safe_md(summary['operations_roadmap_now'])}`",
        f"- Guarded apply readiness: `{summary['guarded_apply_readiness_result']}`, can run `{summary['guarded_apply_readiness_can_run']}`, requires input `{summary['guarded_apply_readiness_requires_input']}`, gate blockers `{summary['guarded_apply_readiness_gate_blockers']}`, hard stops `{summary['guarded_apply_readiness_hard_stops']}`",
        f"- Guarded action audit: actions `{summary['guarded_action_audit_actions']}`, blockers `{summary['guarded_action_audit_blockers']}`",
        f"- Migration state manifest: surfaces `{summary['migration_state_manifest_surfaces']}`, secret-bearing `{summary['migration_state_manifest_secret_surfaces']}`, services `{summary['migration_state_manifest_services']}`, blockers `{summary['migration_state_manifest_blockers']}`",
        f"- State transfer plan: blocked surfaces `{summary['state_transfer_blocked_surfaces']}`, blocked services `{summary['state_transfer_blocked_services']}`, pending items `{summary['state_transfer_pending_items']}`, cleanup handoffs `{summary['state_transfer_cleanup_handoffs']}`, backup ready `{summary['state_transfer_backup_ready']}`",
        f"- Mail production gate: blockers `{summary['mail_production_blockers']}`, warnings `{summary['mail_production_warnings']}`, MX `{summary['mail_production_mx_aligned']}`, SPF `{summary['mail_production_spf_aligned']}`, DKIM selectors `{summary['mail_production_dkim_selectors']}`, port25 `{summary['mail_production_port25_status']}`, cutover ready `{summary['mail_production_cutover_ready']}`",
        f"- Ops evidence digest: daily notes `{summary['ops_evidence_daily_notes']}`, missing days `{summary['ops_evidence_missing_days']}`, secret-pattern files `{summary['ops_evidence_secret_pattern_files']}`",
        f"- Objective coverage: `{summary['objective_coverage_result']}`, complete `{summary['objective_coverage_complete']}`, implementation ready `{summary['objective_implementation_ready']}`, covered `{summary['objective_covered']}`/`{summary['objective_requirements']}`, missing `{summary['objective_missing']}`, blocked `{summary['objective_blocked']}`, implementation blockers `{summary['objective_implementation_blocked']}`",
        f"- Backup gate: secure packet missing groups `{summary['r2_secure_input_missing_groups']}`, active r2 `{summary['r2_secure_input_active_r2']}`, remote config blockers `{summary['r2_remote_config_blockers']}`, active r2 `{summary['r2_remote_config_active_r2']}`, intake blockers `{summary['r2_restic_intake_blockers']}` input groups `{summary['r2_restic_intake_input_groups']}/{summary['r2_restic_intake_required_groups']}`, bootstrap blockers `{summary['r2_restic_bootstrap_blockers']}`, restic blockers `{summary['restic_backup_blockers']}`, restore blockers `{summary['restore_drill_blockers']}`",
        f"- Hetzner hardening warnings: `{summary['hetzner_hardening_warning_count']}`, remediation actions `{summary['hetzner_hardening_remediation_actions']}`, bundle actions `{summary['hetzner_hardening_bundle_pending_actions']}`",
        f"- Can-doctor warning/fail checks: `{summary['can_doctor_warning_count']}`",
        f"- Secret rotation: `{summary['secret_rotation_result']}`, findings `{summary['secret_finding_files']}`, risky doc/source `{summary['secret_risky_doc_or_source_files']}`",
        "",
    ]
    if payload["do_not"]:
        lines.extend(["## Do Not", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["do_not"])
        lines.append("")

    lines.extend(["## Top Priorities", ""])
    if payload["top_priorities"]:
        lines.extend(f"{idx}. {safe_md(item)}" for idx, item in enumerate(payload["top_priorities"], start=1))
    else:
        lines.append("- Run `nomarh-ops --refresh` to generate priorities.")

    lines.extend(["", "## Next Tasks", "", "| Order | Lane | Task | Status | Verify |", "|---:|---|---|---|---|"])
    for item in payload["next_tasks"]:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"| {safe_md(item.get('order'))} | `{safe_md(item.get('lane'))}` | {safe_md(item.get('title'))} | `{safe_md(item.get('status'))}` | `{safe_md(item.get('verify'))}` |"
        )

    lines.extend(["", "## Verify After Change", ""])
    lines.extend(f"- `{safe_md(item)}`" for item in payload["verify_after_change"])
    lines.extend(["", "## Source Results", "", "| Source | Result |", "|---|---|"])
    for key, result in payload["summary"]["source_results"].items():
        lines.append(f"| `{safe_md(key)}` | `{safe_md(result)}` |")
    lines.extend(["", "## Paths", ""])
    for key, path in payload["paths"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def render_console(payload: dict[str, Any]) -> str:
    action = payload["do_first"]
    summary = payload["summary"]
    lines = [
        "Nomarh Ops",
        f"Result: {payload['result']}",
        f"Do first: {action['title']} [{action['lane']}/{action['status']}]",
    ]
    if action["next_action"]:
        lines.append(f"Next action: {action['next_action']}")
    if action["verify"]:
        lines.append(f"Verify: {action['verify']}")
    lines.extend(
        [
            "",
            f"P0: {compact_dict(summary['p0_counts'])} | readiness: {compact_dict(summary['readiness_counts'])}",
            f"Supervision: plans={summary['supervision_plan_count']} {compact_dict(summary['supervision_status_counts'])} unit_files={summary['supervision_unit_generated_files']} ready_files={summary['supervision_unit_ready_files']}",
            f"Runtime stabilization: actions={summary['runtime_stabilization_actions']} tmux_handoffs={summary['runtime_stabilization_tmux_handoffs']} decisions={summary['runtime_stabilization_decisions']} ready_specs={summary['runtime_stabilization_ready_specs']}",
            f"Cutover guard: hard_stops={summary['cutover_hard_stops']} warnings={summary['cutover_warnings']}",
            f"Runtime: tmux={summary['tmux_total']} providers={summary['provider_worker_count']} cleanup={summary['cleanup_candidate_count']} cleanup_review_high={summary['tmux_cleanup_review_high']} medium={summary['tmux_cleanup_review_medium']} stop={summary['tmux_cleanup_stop_candidates']}",
            f"Action pack: external_blockers={summary['action_pack_external_blockers']} safe_reviews={summary['action_pack_safe_reviews']} guarded_actions={summary['action_pack_guarded_actions']}",
            f"VM structure map: result={summary['vm_structure_map_result']} services={summary['vm_structure_map_services']} p0={summary['vm_structure_map_p0']} p1={summary['vm_structure_map_p1']} blocked_surfaces={summary['vm_structure_map_blocked_surfaces']} blocked_services={summary['vm_structure_map_blocked_services']} hard_stops={summary['vm_structure_map_hard_stops']}",
            f"Operations roadmap: result={summary['operations_roadmap_result']} phases={summary['operations_roadmap_phases']} blockers={summary['operations_roadmap_blockers']} warnings={summary['operations_roadmap_warnings']} now={summary['operations_roadmap_now']}",
            f"Guarded apply readiness: result={summary['guarded_apply_readiness_result']} can_run={summary['guarded_apply_readiness_can_run']} requires_input={summary['guarded_apply_readiness_requires_input']} gate_blockers={summary['guarded_apply_readiness_gate_blockers']} hard_stops={summary['guarded_apply_readiness_hard_stops']}",
            f"Guarded action audit: actions={summary['guarded_action_audit_actions']} blockers={summary['guarded_action_audit_blockers']}",
            f"Migration state: surfaces={summary['migration_state_manifest_surfaces']} secret_surfaces={summary['migration_state_manifest_secret_surfaces']} services={summary['migration_state_manifest_services']} blockers={summary['migration_state_manifest_blockers']}",
            f"State transfer: blocked_surfaces={summary['state_transfer_blocked_surfaces']} blocked_services={summary['state_transfer_blocked_services']} pending={summary['state_transfer_pending_items']} handoffs={summary['state_transfer_cleanup_handoffs']} backup_ready={summary['state_transfer_backup_ready']}",
            f"Mail production: blockers={summary['mail_production_blockers']} warnings={summary['mail_production_warnings']} mx={summary['mail_production_mx_aligned']} spf={summary['mail_production_spf_aligned']} dkim_selectors={summary['mail_production_dkim_selectors']} port25={summary['mail_production_port25_status']} cutover_ready={summary['mail_production_cutover_ready']}",
            f"Ops evidence: daily_notes={summary['ops_evidence_daily_notes']} missing_days={summary['ops_evidence_missing_days']} secret_pattern_files={summary['ops_evidence_secret_pattern_files']}",
            f"Objective coverage: result={summary['objective_coverage_result']} complete={summary['objective_coverage_complete']} implementation_ready={summary['objective_implementation_ready']} covered={summary['objective_covered']}/{summary['objective_requirements']} missing={summary['objective_missing']} blocked={summary['objective_blocked']} implementation_blocked={summary['objective_implementation_blocked']}",
            f"Backup: secure_missing_groups={summary['r2_secure_input_missing_groups']} secure_active_r2={summary['r2_secure_input_active_r2']} remote_config_blockers={summary['r2_remote_config_blockers']} active_r2={summary['r2_remote_config_active_r2']} intake blockers={summary['r2_restic_intake_blockers']} input_groups={summary['r2_restic_intake_input_groups']}/{summary['r2_restic_intake_required_groups']} bootstrap blockers={summary['r2_restic_bootstrap_blockers']} restic blockers={summary['restic_backup_blockers']} restore blockers={summary['restore_drill_blockers']}",
            f"Hardening warnings: {summary['hetzner_hardening_warning_count']} remediation actions={summary['hetzner_hardening_remediation_actions']} bundle actions={summary['hetzner_hardening_bundle_pending_actions']} | doctor warnings: {summary['can_doctor_warning_count']}",
            f"Secret rotation: result={summary['secret_rotation_result']} findings={summary['secret_finding_files']} risky_doc_source={summary['secret_risky_doc_or_source_files']}",
        ]
    )
    if payload["do_not"]:
        lines.extend(["", "Do not:"])
        lines.extend(f"- {item}" for item in payload["do_not"][:4])
    if payload["top_priorities"]:
        lines.extend(["", "Top priorities:"])
        lines.extend(f"{idx}. {item}" for idx, item in enumerate(payload["top_priorities"][:5], start=1))
    lines.extend(["", f"Summary: {SUMMARY_PATH}", f"Status: {STATUS_PATH}"])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Single no-secret daily operations entrypoint for Nomarh")
    parser.add_argument("--refresh", action="store_true", help="run can-ops-refresh before building the ops view")
    parser.add_argument("--timeout", type=int, default=240, help="refresh timeout in seconds")
    parser.add_argument("--json", action="store_true", help="print JSON payload")
    parser.add_argument("--no-history", action="store_true", help="do not append to history.jsonl")
    args = parser.parse_args()

    refresh_result = run_refresh(args.timeout) if args.refresh else None
    payload = build_payload(refresh_result)
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(SUMMARY_PATH, render_markdown(payload))
    if not args.no_history:
        append_jsonl(HISTORY_PATH, payload)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_console(payload))
    return 2 if payload["result"] == "blocked" else 1 if payload["result"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())

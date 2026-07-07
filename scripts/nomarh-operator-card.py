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
STATE_DIR = HOME / ".local/state/nomarh-operator-card"
STATUS_PATH = STATE_DIR / "status.json"
CARD_PATH = STATE_DIR / "card.md"

NOMARH_OPS_STATUS = HOME / ".local/state/nomarh-ops/status.json"
ACTION_PACK_STATUS = HOME / ".local/state/nomarh-action-pack/status.json"
VM_STRUCTURE_MAP_STATUS = HOME / ".local/state/nomarh-vm-structure-map/status.json"
OPERATIONS_ROADMAP_STATUS = HOME / ".local/state/nomarh-operations-roadmap/status.json"
GUARDED_APPLY_READINESS_STATUS = HOME / ".local/state/nomarh-guarded-apply-readiness/status.json"
P0_BOARD_STATUS = HOME / ".local/state/nomarh-p0-execution-board/board.json"
EVIDENCE_DIGEST_STATUS = HOME / ".local/state/nomarh-ops-evidence-digest/status.json"
MIGRATION_MANIFEST_STATUS = HOME / ".local/state/nomarh-migration-state-manifest/manifest.json"
STATE_TRANSFER_PLAN_STATUS = HOME / ".local/state/nomarh-state-transfer-plan/status.json"
MAIL_PRODUCTION_GATE_STATUS = HOME / ".local/state/nomarh-mail-production-gate/status.json"
CUTOVER_GUARD_STATUS = HOME / ".local/state/nomarh-cutover-guard/guard.json"
SECRET_ROTATION_STATUS = HOME / ".local/state/nomarh-secret-rotation-plan/status.json"
R2_INTAKE_STATUS = HOME / ".local/state/control-plane-r2-restic-intake/status.json"
R2_SECURE_INPUT_PACKET_STATUS = HOME / ".local/state/control-plane-r2-secure-input-packet/status.json"
R2_REMOTE_CONFIG_STATUS = HOME / ".local/state/control-plane-r2-remote-config/status.json"
RUNTIME_STABILIZATION_STATUS = HOME / ".local/state/nomarh-runtime-stabilization-board/status.json"
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


def safe_md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def run_refresh(timeout: int) -> dict[str, Any]:
    command = ["nomarh-ops", "--refresh", "--json"]
    if not shutil.which(command[0]):
        return {
            "command": " ".join(command),
            "returncode": 127,
            "duration_seconds": 0,
            "stderr_tail": "command not found: nomarh-ops",
        }
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return {
            "command": " ".join(command),
            "returncode": 124,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout_tail": stdout[-500:],
            "stderr_tail": (stderr or f"timed out after {timeout}s")[-500:],
        }
    except Exception as exc:
        return {
            "command": " ".join(command),
            "returncode": 1,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stderr_tail": str(exc)[-500:],
        }
    return {
        "command": " ".join(command),
        "returncode": proc.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "stdout_tail": (proc.stdout or "")[-500:],
        "stderr_tail": (proc.stderr or "")[-500:],
    }


def compact_action(item: Any) -> dict[str, str]:
    if not isinstance(item, dict):
        return {
            "lane": "",
            "title": "",
            "status": "",
            "next_action": "",
            "verify": "",
            "reason": "",
        }
    return {
        "lane": str(item.get("lane", "")),
        "title": str(item.get("title", "")),
        "status": str(item.get("status", "")),
        "next_action": str(item.get("next_action", "")),
        "verify": str(item.get("verify", "")),
        "reason": str(item.get("reason") or item.get("why") or ""),
    }


def build_payload(refresh: dict[str, Any] | None) -> dict[str, Any]:
    ops = read_json(NOMARH_OPS_STATUS)
    action_pack = read_json(ACTION_PACK_STATUS)
    vm_structure_map = read_json(VM_STRUCTURE_MAP_STATUS)
    operations_roadmap = read_json(OPERATIONS_ROADMAP_STATUS)
    guarded_apply_readiness = read_json(GUARDED_APPLY_READINESS_STATUS)
    p0 = read_json(P0_BOARD_STATUS)
    evidence = read_json(EVIDENCE_DIGEST_STATUS)
    manifest = read_json(MIGRATION_MANIFEST_STATUS)
    state_transfer = read_json(STATE_TRANSFER_PLAN_STATUS)
    mail_gate = read_json(MAIL_PRODUCTION_GATE_STATUS)
    cutover = read_json(CUTOVER_GUARD_STATUS)
    secret_rotation = read_json(SECRET_ROTATION_STATUS)
    r2_intake = read_json(R2_INTAKE_STATUS)
    r2_secure_packet = read_json(R2_SECURE_INPUT_PACKET_STATUS)
    r2_remote_config = read_json(R2_REMOTE_CONFIG_STATUS)
    runtime_stabilization = read_json(RUNTIME_STABILIZATION_STATUS)
    objective_coverage = read_json(OBJECTIVE_COVERAGE_STATUS)

    ops_summary = dict_get(ops, "summary", {})
    action_summary = dict_get(action_pack, "summary", {})
    vm_structure_summary = dict_get(vm_structure_map, "summary", {})
    roadmap_summary = dict_get(operations_roadmap, "summary", {})
    guarded_apply_summary = dict_get(guarded_apply_readiness, "summary", {})
    evidence_summary = dict_get(evidence, "summary", {})
    manifest_summary = dict_get(manifest, "summary", {})
    state_transfer_summary = dict_get(state_transfer, "summary", {})
    mail_gate_summary = dict_get(mail_gate, "summary", {})
    p0_summary = dict_get(p0, "summary", {})
    r2_intake_summary = dict_get(r2_intake, "summary", {})
    r2_secure_packet_summary = dict_get(r2_secure_packet, "summary", {})
    r2_remote_config_summary = dict_get(r2_remote_config, "summary", {})
    runtime_stabilization_summary = dict_get(runtime_stabilization, "summary", {})
    objective_summary = dict_get(objective_coverage, "summary", {})
    r2_tools = dict_get(r2_intake, "tools", {})

    do_first = compact_action(dict_get(ops, "do_first", {}))
    external_blockers = [compact_action(item) for item in list_get(action_pack, "external_blockers")]
    safe_reviews = [compact_action(item) for item in list_get(action_pack, "safe_reviews")]
    p0_next = [compact_action(item) for item in list_get(p0, "next_tasks")[:6]]
    do_not = [str(item) for item in (list_get(action_pack, "do_not") or list_get(ops, "do_not"))]
    hard_stops = [str(item) for item in list_get(cutover, "hard_stops")]
    top_priorities = [str(item) for item in list_get(ops, "top_priorities")[:5]]
    evidence_recommendations = [compact_action(item) for item in list_get(evidence, "recommendations")[:5]]

    blockers = int_get(action_summary, "external_blocker_count") + len(hard_stops)
    vm_structure_blockers = int_get(vm_structure_summary, "blocker_count")
    roadmap_blockers = int_get(roadmap_summary, "blocker_count")
    objective_blockers = int_get(objective_summary, "implementation_blocked_count")
    guarded_apply_gate_blockers = int_get(guarded_apply_summary, "gate_blocker_count")
    refresh_failed = refresh is not None and refresh.get("returncode") not in {0, 2}
    result = (
        "fail"
        if refresh_failed
        else "blocked"
        if blockers or guarded_apply_gate_blockers or vm_structure_blockers or roadmap_blockers or objective_blockers
        else "warn"
        if safe_reviews
        else str(dict_get(ops, "result", "missing"))
    )

    return {
        "schema": "nomarh-operator-card.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "refresh": refresh,
        "do_first": do_first,
        "external_blockers": external_blockers,
        "safe_reviews": safe_reviews,
        "p0_next": p0_next,
        "do_not": do_not,
        "hard_stops": hard_stops,
        "top_priorities": top_priorities,
        "evidence_recommendations": evidence_recommendations,
        "summary": {
            "ops_result": dict_get(ops, "result", "missing"),
            "p0_result": dict_get(p0, "result", "missing"),
            "action_pack_result": dict_get(action_pack, "result", "missing"),
            "vm_structure_map_result": dict_get(vm_structure_map, "result", "missing"),
            "vm_structure_map_services": int_get(vm_structure_summary, "service_count"),
            "vm_structure_map_p0": int_get(vm_structure_summary, "p0_count"),
            "vm_structure_map_p1": int_get(vm_structure_summary, "p1_count"),
            "vm_structure_map_blocked_surfaces": int_get(vm_structure_summary, "blocked_surfaces"),
            "vm_structure_map_blocked_services": int_get(vm_structure_summary, "blocked_services"),
            "vm_structure_map_hard_stops": int_get(vm_structure_summary, "cutover_hard_stops"),
            "operations_roadmap_result": dict_get(operations_roadmap, "result", "missing"),
            "operations_roadmap_phases": int_get(roadmap_summary, "phase_count"),
            "operations_roadmap_blockers": roadmap_blockers,
            "operations_roadmap_warnings": int_get(roadmap_summary, "warning_count"),
            "operations_roadmap_now": str(dict_get(dict_get(operations_roadmap, "now", {}), "title", "")),
            "operations_roadmap_now_verify": str(dict_get(dict_get(operations_roadmap, "now", {}), "verify", "")),
            "objective_coverage_result": dict_get(objective_coverage, "result", "missing"),
            "objective_coverage_complete": bool(dict_get(objective_coverage, "coverage_complete", False)),
            "objective_implementation_ready": bool(dict_get(objective_coverage, "implementation_ready", False)),
            "objective_requirements": int_get(objective_summary, "requirement_count"),
            "objective_covered": int_get(objective_summary, "covered_count"),
            "objective_blocked": int_get(objective_summary, "blocked_count"),
            "objective_missing": int_get(objective_summary, "missing_count"),
            "objective_implementation_blocked": objective_blockers,
            "guarded_apply_readiness_result": dict_get(guarded_apply_readiness, "result", "missing"),
            "guarded_apply_readiness_can_run": bool(
                dict_get(guarded_apply_readiness, "can_run_guarded_actions", False)
            ),
            "guarded_apply_readiness_requires_input": int_get(guarded_apply_summary, "requires_input_count"),
            "guarded_apply_readiness_gate_blockers": guarded_apply_gate_blockers,
            "guarded_apply_readiness_hard_stops": int_get(guarded_apply_summary, "hard_stop_count"),
            "cutover_result": dict_get(cutover, "result", "missing"),
            "migration_manifest_result": dict_get(manifest, "result", "missing"),
            "state_transfer_result": dict_get(state_transfer, "result", "missing"),
            "mail_production_gate_result": dict_get(mail_gate, "result", "missing"),
            "evidence_digest_result": dict_get(evidence, "result", "missing"),
            "secret_rotation_result": dict_get(secret_rotation, "result", "missing"),
            "runtime_stabilization_result": dict_get(runtime_stabilization, "result", "missing"),
            "runtime_stabilization_actions": int_get(runtime_stabilization_summary, "action_count"),
            "runtime_stabilization_tmux_handoffs": int_get(runtime_stabilization_summary, "tmux_review_count"),
            "runtime_stabilization_decisions": int_get(runtime_stabilization_summary, "decision_needed_count"),
            "runtime_stabilization_ready_specs": int_get(runtime_stabilization_summary, "ready_spec_count"),
            "r2_remote_config_result": dict_get(r2_remote_config, "result", "missing"),
            "r2_remote_config_blockers": int_get(r2_remote_config_summary, "blocker_count"),
            "r2_remote_config_active_r2": bool(dict_get(r2_remote_config_summary, "active_r2_after", False)),
            "external_blockers": int_get(action_summary, "external_blocker_count"),
            "safe_reviews": int_get(action_summary, "safe_review_count"),
            "guarded_actions": int_get(action_summary, "guarded_action_count"),
            "hard_stops": len(hard_stops),
            "p0_tasks": int_get(p0_summary, "task_count"),
            "p0_blocked": int_get(dict_get(p0_summary, "counts", {}), "blocked"),
            "tmux_total": int_get(ops_summary, "tmux_total"),
            "tmux_cleanup_candidates": int_get(ops_summary, "cleanup_candidate_count"),
            "daily_notes": int_get(evidence_summary, "daily_note_count"),
            "missing_days": int_get(evidence_summary, "missing_day_count"),
            "secret_pattern_files": int_get(evidence_summary, "secret_pattern_file_count"),
            "r2_intake_result": dict_get(r2_intake, "result", "missing"),
            "r2_secure_input_packet_result": dict_get(r2_secure_packet, "result", "missing"),
            "r2_secure_input_missing_groups": int_get(r2_secure_packet_summary, "missing_required_input_groups"),
            "r2_secure_input_active_r2": bool(dict_get(r2_secure_packet_summary, "active_r2_remote", False)),
            "r2_input_groups": int_get(r2_intake_summary, "present_required_input_groups"),
            "r2_required_input_groups": int_get(r2_intake_summary, "required_input_groups"),
            "restic_installed": bool(dict_get(r2_tools, "restic_installed", False)),
            "rclone_installed": bool(dict_get(r2_tools, "rclone_installed", False)),
            "active_r2_remote": bool(dict_get(r2_tools, "active_r2_remote", False)),
            "state_surfaces": int_get(manifest_summary, "surface_count"),
            "secret_bearing_surfaces": int_get(manifest_summary, "secret_bearing_surface_count"),
            "service_items": int_get(manifest_summary, "service_count"),
            "state_transfer_blocked_surfaces": int_get(state_transfer_summary, "blocked_surface_count"),
            "state_transfer_blocked_services": int_get(state_transfer_summary, "blocked_service_count"),
            "state_transfer_pending_items": int_get(state_transfer_summary, "pending_item_count"),
            "state_transfer_cleanup_handoffs": int_get(state_transfer_summary, "cleanup_handoff_count"),
            "mail_production_blockers": int_get(mail_gate_summary, "blocker_count"),
            "mail_production_warnings": int_get(mail_gate_summary, "warning_count"),
            "mail_production_mx_aligned": bool(dict_get(mail_gate_summary, "mx_points_to_mailhost", False)),
            "mail_production_spf_aligned": bool(dict_get(mail_gate_summary, "spf_authorizes_mailhost", False)),
            "mail_production_dkim_selectors": int_get(mail_gate_summary, "dkim_selector_count"),
            "mail_production_cutover_ready": bool(dict_get(mail_gate_summary, "cutover_ready", False)),
        },
        "verify_sequence": [
            "nomarh-ops --refresh --json",
            "control-plane-r2-secure-input-packet --json",
            "control-plane-r2-remote-config --json",
            do_first["verify"] or "control-plane-r2-restic-intake --json",
            "nomarh-runtime-stabilization-board --json",
            "nomarh-state-transfer-plan --json",
            "nomarh-mail-production-gate --json",
            "nomarh-action-pack --json",
            "nomarh-guarded-apply-readiness --json",
            "nomarh-vm-structure-map --json",
            "nomarh-operations-roadmap --json",
            "nomarh-objective-coverage --json",
            "nomarh-cutover-guard --json",
        ],
        "paths": {
            "status": str(STATUS_PATH),
            "card": str(CARD_PATH),
            "nomarh_ops": str(NOMARH_OPS_STATUS),
            "action_pack": str(ACTION_PACK_STATUS),
            "vm_structure_map": str(VM_STRUCTURE_MAP_STATUS),
            "operations_roadmap": str(OPERATIONS_ROADMAP_STATUS),
            "objective_coverage": str(OBJECTIVE_COVERAGE_STATUS),
            "guarded_apply_readiness": str(GUARDED_APPLY_READINESS_STATUS),
            "p0_board": str(P0_BOARD_STATUS),
            "evidence_digest": str(EVIDENCE_DIGEST_STATUS),
            "migration_manifest": str(MIGRATION_MANIFEST_STATUS),
            "state_transfer_plan": str(STATE_TRANSFER_PLAN_STATUS),
            "mail_production_gate": str(MAIL_PRODUCTION_GATE_STATUS),
            "cutover_guard": str(CUTOVER_GUARD_STATUS),
            "secret_rotation": str(SECRET_ROTATION_STATUS),
            "r2_intake": str(R2_INTAKE_STATUS),
            "r2_secure_input_packet": str(R2_SECURE_INPUT_PACKET_STATUS),
            "r2_remote_config": str(R2_REMOTE_CONFIG_STATUS),
            "runtime_stabilization": str(RUNTIME_STABILIZATION_STATUS),
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    do_first = payload["do_first"]
    lines = [
        "# Nomarh Operator Card",
        "",
        "No secrets, env values, mailbox contents, tmux pane output, private keys, or long logs are read. This card is the compact daily action view.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Ops: `{summary['ops_result']}`; P0: `{summary['p0_result']}`; cutover: `{summary['cutover_result']}`",
        f"- External blockers: `{summary['external_blockers']}`; hard stops: `{summary['hard_stops']}`; safe reviews: `{summary['safe_reviews']}`; guarded actions: `{summary['guarded_actions']}`",
        f"- VM structure map: `{summary['vm_structure_map_result']}` services `{summary['vm_structure_map_services']}`, P0/P1 `{summary['vm_structure_map_p0']}`/`{summary['vm_structure_map_p1']}`, blocked surfaces `{summary['vm_structure_map_blocked_surfaces']}`, blocked services `{summary['vm_structure_map_blocked_services']}`, hard stops `{summary['vm_structure_map_hard_stops']}`",
        f"- Operations roadmap: `{summary['operations_roadmap_result']}` phases `{summary['operations_roadmap_phases']}`, blockers `{summary['operations_roadmap_blockers']}`, warnings `{summary['operations_roadmap_warnings']}`, now `{safe_md(summary['operations_roadmap_now'])}`",
        f"- Objective coverage: `{summary['objective_coverage_result']}` complete `{summary['objective_coverage_complete']}`, implementation ready `{summary['objective_implementation_ready']}`, covered `{summary['objective_covered']}`/`{summary['objective_requirements']}`, missing `{summary['objective_missing']}`, blocked `{summary['objective_blocked']}`, implementation blockers `{summary['objective_implementation_blocked']}`",
        f"- Guarded apply readiness: `{summary['guarded_apply_readiness_result']}` can run `{summary['guarded_apply_readiness_can_run']}`, requires input `{summary['guarded_apply_readiness_requires_input']}`, gate blockers `{summary['guarded_apply_readiness_gate_blockers']}`, hard stops `{summary['guarded_apply_readiness_hard_stops']}`",
        f"- Evidence: `{summary['daily_notes']}` daily notes, `{summary['missing_days']}` missing days, `{summary['secret_pattern_files']}` secret-pattern files",
        f"- Runtime: tmux `{summary['tmux_total']}`, cleanup candidates `{summary['tmux_cleanup_candidates']}`, stabilization `{summary['runtime_stabilization_result']}` actions `{summary['runtime_stabilization_actions']}`, handoffs `{summary['runtime_stabilization_tmux_handoffs']}`, decisions `{summary['runtime_stabilization_decisions']}`",
        f"- Backup tooling: restic `{summary['restic_installed']}`, rclone `{summary['rclone_installed']}`, secure packet `{summary['r2_secure_input_packet_result']}` missing groups `{summary['r2_secure_input_missing_groups']}`, remote config `{summary['r2_remote_config_result']}` with `{summary['r2_remote_config_blockers']}` blocker(s), active r2 remote `{summary['active_r2_remote']}`/`{summary['r2_remote_config_active_r2']}`, input groups `{summary['r2_input_groups']}/{summary['r2_required_input_groups']}`",
        f"- Migration state: surfaces `{summary['state_surfaces']}`, secret-bearing `{summary['secret_bearing_surfaces']}`, services `{summary['service_items']}`, transfer `{summary['state_transfer_result']}` blocked surfaces `{summary['state_transfer_blocked_surfaces']}`, blocked services `{summary['state_transfer_blocked_services']}`",
        f"- Mail production: `{summary['mail_production_gate_result']}` blockers `{summary['mail_production_blockers']}`, warnings `{summary['mail_production_warnings']}`, MX `{summary['mail_production_mx_aligned']}`, SPF `{summary['mail_production_spf_aligned']}`, DKIM selectors `{summary['mail_production_dkim_selectors']}`, cutover ready `{summary['mail_production_cutover_ready']}`",
        "",
    ]
    if payload.get("refresh"):
        refresh = payload["refresh"]
        lines.extend(
            [
                "## Refresh",
                "",
                f"- Command: `{safe_md(refresh.get('command'))}`",
                f"- Return code: `{safe_md(refresh.get('returncode'))}`",
                f"- Duration: `{safe_md(refresh.get('duration_seconds'))}` seconds",
                "",
            ]
        )
    lines.extend(
        [
            "## Do First",
            "",
            f"- Lane: `{safe_md(do_first['lane'])}`",
            f"- Task: **{safe_md(do_first['title'])}**",
            f"- Status: `{safe_md(do_first['status'])}`",
            f"- Next action: {safe_md(do_first['next_action'])}",
            f"- Verify: `{safe_md(do_first['verify'])}`",
            "",
            "## Blockers",
            "",
        ]
    )
    if payload["external_blockers"]:
        for item in payload["external_blockers"]:
            lines.append(f"- `{safe_md(item['lane'])}` {safe_md(item['title'])}: {safe_md(item['next_action'])}")
    else:
        lines.append("- No external blockers listed.")

    lines.extend(["", "## Do Not", ""])
    if payload["do_not"]:
        lines.extend(f"- {safe_md(item)}" for item in payload["do_not"])
    else:
        lines.append("- No do-not rules listed.")

    lines.extend(["", "## Safe Reviews", ""])
    if payload["safe_reviews"]:
        for item in payload["safe_reviews"]:
            lines.append(
                f"- `{safe_md(item['lane'])}` {safe_md(item['title'])}: {safe_md(item['next_action'])} Verify `{safe_md(item['verify'])}`"
            )
    else:
        lines.append("- No safe local reviews listed.")

    lines.extend(["", "## P0 Queue", ""])
    for item in payload["p0_next"]:
        lines.append(
            f"- `{safe_md(item['lane'])}` {safe_md(item['title'])} [{safe_md(item['status'])}] -> `{safe_md(item['verify'])}`"
        )

    lines.extend(["", "## Verify Sequence", ""])
    for idx, command in enumerate(payload["verify_sequence"], start=1):
        lines.append(f"{idx}. `{safe_md(command)}`")

    lines.extend(["", "## Source Paths", ""])
    for key, path in payload["paths"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def render_console(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    do_first = payload["do_first"]
    lines = [
        "Nomarh Operator Card",
        f"Result: {payload['result']}",
        f"Do first: {do_first['title']} [{do_first['lane']}/{do_first['status']}]",
        f"Next: {do_first['next_action']}",
        f"Verify: {do_first['verify']}",
        "",
        f"Blockers: external={summary['external_blockers']} hard_stops={summary['hard_stops']} | safe_reviews={summary['safe_reviews']} guarded={summary['guarded_actions']}",
        f"VM structure map: result={summary['vm_structure_map_result']} services={summary['vm_structure_map_services']} p0={summary['vm_structure_map_p0']} p1={summary['vm_structure_map_p1']} blocked_surfaces={summary['vm_structure_map_blocked_surfaces']} blocked_services={summary['vm_structure_map_blocked_services']} hard_stops={summary['vm_structure_map_hard_stops']}",
        f"Operations roadmap: result={summary['operations_roadmap_result']} phases={summary['operations_roadmap_phases']} blockers={summary['operations_roadmap_blockers']} warnings={summary['operations_roadmap_warnings']} now={summary['operations_roadmap_now']} verify={summary['operations_roadmap_now_verify']}",
        f"Objective coverage: result={summary['objective_coverage_result']} complete={summary['objective_coverage_complete']} implementation_ready={summary['objective_implementation_ready']} covered={summary['objective_covered']}/{summary['objective_requirements']} missing={summary['objective_missing']} blocked={summary['objective_blocked']} implementation_blocked={summary['objective_implementation_blocked']}",
        f"Guarded apply readiness: result={summary['guarded_apply_readiness_result']} can_run={summary['guarded_apply_readiness_can_run']} requires_input={summary['guarded_apply_readiness_requires_input']} gate_blockers={summary['guarded_apply_readiness_gate_blockers']} hard_stops={summary['guarded_apply_readiness_hard_stops']}",
        f"Evidence: daily_notes={summary['daily_notes']} missing_days={summary['missing_days']} secret_pattern_files={summary['secret_pattern_files']}",
        f"Backup tooling: restic={summary['restic_installed']} rclone={summary['rclone_installed']} secure_packet={summary['r2_secure_input_packet_result']} missing_groups={summary['r2_secure_input_missing_groups']} remote_config={summary['r2_remote_config_result']} remote_config_blockers={summary['r2_remote_config_blockers']} active_r2={summary['active_r2_remote']}/{summary['r2_remote_config_active_r2']} input_groups={summary['r2_input_groups']}/{summary['r2_required_input_groups']}",
        f"Runtime: tmux={summary['tmux_total']} cleanup={summary['tmux_cleanup_candidates']} stabilization={summary['runtime_stabilization_result']} actions={summary['runtime_stabilization_actions']} handoffs={summary['runtime_stabilization_tmux_handoffs']} decisions={summary['runtime_stabilization_decisions']} | migration services={summary['service_items']} secret_surfaces={summary['secret_bearing_surfaces']} transfer={summary['state_transfer_result']} blocked_surfaces={summary['state_transfer_blocked_surfaces']} blocked_services={summary['state_transfer_blocked_services']}",
        f"Mail production: result={summary['mail_production_gate_result']} blockers={summary['mail_production_blockers']} warnings={summary['mail_production_warnings']} mx={summary['mail_production_mx_aligned']} spf={summary['mail_production_spf_aligned']} dkim_selectors={summary['mail_production_dkim_selectors']} cutover_ready={summary['mail_production_cutover_ready']}",
    ]
    if payload["do_not"]:
        lines.extend(["", "Do not:"])
        lines.extend(f"- {item}" for item in payload["do_not"][:4])
    lines.extend(["", f"Card: {CARD_PATH}", f"Status: {STATUS_PATH}"])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate compact no-secret Nomarh daily operator card")
    parser.add_argument("--refresh", action="store_true", help="run nomarh-ops --refresh --json before rendering the card")
    parser.add_argument("--timeout", type=int, default=240, help="refresh timeout in seconds")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    refresh = run_refresh(args.timeout) if args.refresh else None
    payload = build_payload(refresh)
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(CARD_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_console(payload))
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

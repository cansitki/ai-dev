#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-action-pack"
STATUS_PATH = STATE_DIR / "status.json"
REPORT_PATH = STATE_DIR / "action-pack.md"

SNAPSHOT_STATUS = HOME / ".local/state/nomarh-daily-ops-snapshot/snapshot.json"
P0_BOARD_STATUS = HOME / ".local/state/nomarh-p0-execution-board/board.json"
R2_INTAKE_STATUS = HOME / ".local/state/control-plane-r2-restic-intake/status.json"
R2_SECURE_INPUT_PACKET_STATUS = HOME / ".local/state/control-plane-r2-secure-input-packet/status.json"
TMUX_CLEANUP_STATUS = HOME / ".local/state/tmux-cleanup-review/status.json"
RUNTIME_STABILIZATION_STATUS = HOME / ".local/state/nomarh-runtime-stabilization-board/status.json"
HARDENING_BUNDLE_STATUS = HOME / ".local/state/hetzner-hardening-command-bundle/status.json"
SUPERVISION_BUNDLE_STATUS = HOME / ".local/state/nomarh-supervision-unit-bundle/status.json"
CUTOVER_GUARD_STATUS = HOME / ".local/state/nomarh-cutover-guard/guard.json"
SECRET_ROTATION_STATUS = HOME / ".local/state/nomarh-secret-rotation-plan/status.json"
GUARDED_ACTION_AUDIT_STATUS = HOME / ".local/state/nomarh-guarded-action-audit/status.json"
MIGRATION_STATE_MANIFEST_STATUS = HOME / ".local/state/nomarh-migration-state-manifest/manifest.json"
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
    if not text.endswith("\n"):
        text += "\n"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def dict_get(payload: Any, key: str, default: Any = None) -> Any:
    return payload.get(key, default) if isinstance(payload, dict) else default


def int_get(payload: Any, key: str) -> int:
    try:
        return int(dict_get(payload, key, 0) or 0)
    except Exception:
        return 0


def list_get(payload: Any, key: str) -> list[Any]:
    value = dict_get(payload, key, [])
    return value if isinstance(value, list) else []


def safe_md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def action(
    action_id: str,
    lane: str,
    title: str,
    status: str,
    kind: str,
    next_action: str,
    verify: str,
    source: Path | str,
    reason: str,
    guard: str = "",
) -> dict[str, Any]:
    return {
        "id": action_id,
        "lane": lane,
        "title": title,
        "status": status,
        "kind": kind,
        "next_action": next_action,
        "verify": verify,
        "source": str(source),
        "reason": reason,
        "guard": guard,
    }


def unique_strings(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        key = text.lower().strip().rstrip(".")
        if key.endswith(" yet"):
            key = key[:-4].strip()
        key = key.rstrip(".")
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def build_payload() -> dict[str, Any]:
    snapshot = read_json(SNAPSHOT_STATUS)
    p0 = read_json(P0_BOARD_STATUS)
    intake = read_json(R2_INTAKE_STATUS)
    secure_packet = read_json(R2_SECURE_INPUT_PACKET_STATUS)
    cleanup = read_json(TMUX_CLEANUP_STATUS)
    runtime_stabilization = read_json(RUNTIME_STABILIZATION_STATUS)
    hardening_bundle = read_json(HARDENING_BUNDLE_STATUS)
    supervision_bundle = read_json(SUPERVISION_BUNDLE_STATUS)
    cutover = read_json(CUTOVER_GUARD_STATUS)
    secret_rotation = read_json(SECRET_ROTATION_STATUS)
    guarded_audit = read_json(GUARDED_ACTION_AUDIT_STATUS)
    migration_state_manifest = read_json(MIGRATION_STATE_MANIFEST_STATUS)
    state_transfer = read_json(STATE_TRANSFER_PLAN_STATUS)
    mail_gate = read_json(MAIL_PRODUCTION_GATE_STATUS)

    external_blockers: list[dict[str, Any]] = []
    safe_reviews: list[dict[str, Any]] = []
    guarded_actions: list[dict[str, Any]] = []

    intake_summary = dict_get(intake, "summary", {})
    secure_packet_summary = dict_get(secure_packet, "summary", {})
    if dict_get(intake, "result") == "blocked":
        external_blockers.append(
            action(
                "r2-restic-intake",
                "backup",
                "Complete secure R2/restic intake",
                "blocked",
                "requires-secure-input",
                "Use the generated secure input packet to collect missing R2/restic values without putting secrets in chat, vault notes, Git, or shell history.",
                "control-plane-r2-secure-input-packet --json",
                R2_SECURE_INPUT_PACKET_STATUS,
                f"Input groups {int_get(intake_summary, 'present_required_input_groups')}/{int_get(intake_summary, 'required_input_groups')}; missing packet groups {int_get(secure_packet_summary, 'missing_required_input_groups')}; blockers {int_get(intake_summary, 'blocker_count')}.",
            )
        )

    cleanup_summary = dict_get(cleanup, "summary", {})
    cleanup_count = int_get(cleanup_summary, "candidate_count")
    runtime_summary = dict_get(runtime_stabilization, "summary", {})
    runtime_action_count = int_get(runtime_summary, "action_count")
    if runtime_action_count:
        safe_reviews.append(
            action(
                "runtime-stabilization-board",
                "runtime",
                "Review runtime stabilization board",
                str(dict_get(runtime_stabilization, "result", "warn")),
                "safe-local-review",
                "Resolve tmux handoffs and supervision decisions; do not stop sessions or install units automatically.",
                "nomarh-runtime-stabilization-board --json",
                RUNTIME_STABILIZATION_STATUS,
                f"{runtime_action_count} action(s): {int_get(runtime_summary, 'tmux_review_count')} tmux handoff(s), {int_get(runtime_summary, 'decision_needed_count')} decision(s), {int_get(runtime_summary, 'ready_spec_count')} ready spec(s).",
            )
        )
    elif cleanup_count:
        safe_reviews.append(
            action(
                "tmux-cleanup-review",
                "runtime",
                "Review tmux cleanup candidates",
                str(dict_get(cleanup, "result", "warn")),
                "safe-local-review",
                "Inspect review-high and review-medium candidates; do not stop sessions automatically.",
                "tmux-cleanup-review --json",
                TMUX_CLEANUP_STATUS,
                f"{cleanup_count} candidates: {int_get(cleanup_summary, 'review_high_count')} high, {int_get(cleanup_summary, 'review_medium_count')} medium, {int_get(cleanup_summary, 'stop_candidate_count')} stop candidates.",
            )
        )

    hardening_summary = dict_get(hardening_bundle, "summary", {})
    hardening_pending = int_get(hardening_summary, "pending_action_count")
    if hardening_pending:
        safe_reviews.append(
            action(
                "hetzner-hardening-review",
                "hardening",
                "Review Hetzner hardening command bundle",
                "pending",
                "safe-local-review",
                "Read the generated apply and rollback scripts before any remote hardening change.",
                "hetzner-hardening-command-bundle --json",
                HARDENING_BUNDLE_STATUS,
                f"{hardening_pending} guarded hardening action(s) pending.",
            )
        )
        guarded_actions.append(
            action(
                "hetzner-hardening-apply",
                "hardening",
                "Apply reviewed Hetzner hardening bundle",
                "guarded",
                "guarded-remote-apply",
                "Run only after review, with a live root SSH session kept open for rollback.",
                "hetzner-hardening-preflight --json",
                dict_get(dict_get(hardening_bundle, "paths", {}), "apply", HARDENING_BUNDLE_STATUS),
                "Applies non-root admin, firewall policy, and port-review commands.",
                str(dict_get(dict_get(hardening_bundle, "guards", {}), "apply", "")),
            )
        )

    supervision_summary = dict_get(supervision_bundle, "summary", {})
    ready_unit_files = int_get(supervision_summary, "ready_to_install_file_count")
    if ready_unit_files:
        safe_reviews.append(
            action(
                "supervision-unit-review",
                "supervision",
                "Review ready systemd user unit candidates",
                "pending",
                "safe-local-review",
                "Review generated unit examples; currently only ready candidates should be considered.",
                "nomarh-supervision-unit-bundle --json",
                SUPERVISION_BUNDLE_STATUS,
                f"{ready_unit_files} ready unit file(s); {int_get(supervision_summary, 'pending_decision_plan_count')} pending-decision plan(s).",
            )
        )
        guarded_actions.append(
            action(
                "supervision-unit-install",
                "supervision",
                "Install reviewed ready systemd user units",
                "guarded",
                "guarded-local-install",
                "Run only after reviewing generated units and confirming user systemd behavior.",
                "nomarh-supervision-unit-bundle --json",
                dict_get(dict_get(supervision_bundle, "paths", {}), "install", SUPERVISION_BUNDLE_STATUS),
                "Installs only ready-to-spec unit candidates.",
                str(dict_get(dict_get(supervision_bundle, "guards", {}), "install", "")),
            )
        )

    secret_summary = dict_get(secret_rotation, "summary", {})
    secret_findings = int_get(secret_summary, "finding_files") + int_get(secret_summary, "risky_doc_or_source_files")
    if secret_findings:
        external_blockers.append(
            action(
                "secret-rotation",
                "security",
                "Rotate and redact detected secrets",
                "blocked",
                "security-blocker",
                "Rotate exposed values externally, then rerun the secret rotation plan.",
                "nomarh-secret-rotation-plan --json",
                SECRET_ROTATION_STATUS,
                f"Secret finding/risk count is {secret_findings}.",
            )
        )

    audit_summary = dict_get(guarded_audit, "summary", {})
    audit_result = str(dict_get(guarded_audit, "result", "missing"))
    if audit_result != "ready":
        safe_reviews.append(
            action(
                "guarded-action-audit",
                "security",
                "Fix guarded action audit before running guarded scripts",
                audit_result,
                "safe-local-review",
                "Inspect guarded action audit blockers before any hardening apply or systemd install.",
                "nomarh-guarded-action-audit --json",
                GUARDED_ACTION_AUDIT_STATUS,
                f"Audit result is `{audit_result}`; blockers {int_get(audit_summary, 'blocker_count')}.",
            )
        )

    manifest_summary = dict_get(migration_state_manifest, "summary", {})
    manifest_result = str(dict_get(migration_state_manifest, "result", "missing"))
    if manifest_result != "ready":
        safe_reviews.append(
            action(
                "migration-state-manifest",
                "migration",
                "Review migration state manifest before copying state",
                manifest_result,
                "safe-local-review",
                "Use the manifest to decide what is restored, recreated, or excluded before the AWS-to-Hetzner cutover.",
                "nomarh-migration-state-manifest --json",
                MIGRATION_STATE_MANIFEST_STATUS,
                f"{int_get(manifest_summary, 'surface_count')} surfaces, {int_get(manifest_summary, 'secret_bearing_surface_count')} secret-bearing, blockers {int_get(manifest_summary, 'blocker_count')}.",
            )
        )

    state_transfer_summary = dict_get(state_transfer, "summary", {})
    state_transfer_result = str(dict_get(state_transfer, "result", "missing"))
    if state_transfer_result != "ready":
        safe_reviews.append(
            action(
                "state-transfer-plan",
                "migration",
                "Review state transfer plan before copying state",
                state_transfer_result,
                "safe-local-review",
                "Use the restore/recreate/exclude plan before moving vault, source, services, or runtime state to Hetzner.",
                "nomarh-state-transfer-plan --json",
                STATE_TRANSFER_PLAN_STATUS,
                f"{int_get(state_transfer_summary, 'blocked_surface_count')} blocked surface(s), {int_get(state_transfer_summary, 'blocked_service_count')} blocked service(s), {int_get(state_transfer_summary, 'cleanup_handoff_count')} cleanup handoff(s).",
            )
        )

    mail_gate_summary = dict_get(mail_gate, "summary", {})
    mail_gate_result = str(dict_get(mail_gate, "result", "missing"))
    if mail_gate_result != "ready":
        safe_reviews.append(
            action(
                "mail-production-gate",
                "mail",
                "Review mail production cutover gate",
                mail_gate_result,
                "safe-local-review",
                "Keep production MX on the current provider until MX/SPF/DKIM/PTR/TLS checks are aligned for Mailcow.",
                "nomarh-mail-production-gate --json",
                MAIL_PRODUCTION_GATE_STATUS,
                f"{int_get(mail_gate_summary, 'blocker_count')} blocker(s), {int_get(mail_gate_summary, 'warning_count')} warning(s), MX aligned {bool(dict_get(mail_gate_summary, 'mx_points_to_mailhost', False))}, SPF aligned {bool(dict_get(mail_gate_summary, 'spf_authorizes_mailhost', False))}.",
            )
        )

    snapshot_do_not = list_get(dict_get(snapshot, "today", {}), "do_not")
    cutover_do_not = list_get(cutover, "do_not")
    do_not = unique_strings(snapshot_do_not + cutover_do_not)
    hard_stops = [str(item) for item in list_get(cutover, "hard_stops")]
    p0_next = [item for item in list_get(p0, "next_tasks") if isinstance(item, dict)]

    result = "blocked" if external_blockers or hard_stops else "warn" if safe_reviews or guarded_actions else "ready"
    return {
        "schema": "nomarh-action-pack.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "summary": {
            "external_blocker_count": len(external_blockers),
            "safe_review_count": len(safe_reviews),
            "guarded_action_count": len(guarded_actions),
            "r2_secure_input_packet_result": dict_get(secure_packet, "result", "missing"),
            "r2_secure_input_missing_groups": int_get(secure_packet_summary, "missing_required_input_groups"),
            "r2_secure_input_active_r2": bool(dict_get(secure_packet_summary, "active_r2_remote", False)),
            "guarded_audit_result": audit_result,
            "guarded_audit_action_count": int_get(audit_summary, "action_count"),
            "guarded_audit_blockers": int_get(audit_summary, "blocker_count"),
            "migration_state_manifest_result": manifest_result,
            "migration_state_manifest_surfaces": int_get(manifest_summary, "surface_count"),
            "migration_state_manifest_secret_surfaces": int_get(manifest_summary, "secret_bearing_surface_count"),
            "migration_state_manifest_blockers": int_get(manifest_summary, "blocker_count"),
            "state_transfer_result": state_transfer_result,
            "state_transfer_blocked_surfaces": int_get(state_transfer_summary, "blocked_surface_count"),
            "state_transfer_blocked_services": int_get(state_transfer_summary, "blocked_service_count"),
            "state_transfer_pending_items": int_get(state_transfer_summary, "pending_item_count"),
            "state_transfer_cleanup_handoffs": int_get(state_transfer_summary, "cleanup_handoff_count"),
            "mail_production_gate_result": mail_gate_result,
            "mail_production_blockers": int_get(mail_gate_summary, "blocker_count"),
            "mail_production_warnings": int_get(mail_gate_summary, "warning_count"),
            "mail_production_mx_aligned": bool(dict_get(mail_gate_summary, "mx_points_to_mailhost", False)),
            "mail_production_spf_aligned": bool(dict_get(mail_gate_summary, "spf_authorizes_mailhost", False)),
            "mail_production_dkim_selectors": int_get(mail_gate_summary, "dkim_selector_count"),
            "mail_production_cutover_ready": bool(dict_get(mail_gate_summary, "cutover_ready", False)),
            "runtime_stabilization_result": dict_get(runtime_stabilization, "result", "missing"),
            "runtime_stabilization_actions": runtime_action_count,
            "runtime_stabilization_tmux_handoffs": int_get(runtime_summary, "tmux_review_count"),
            "runtime_stabilization_decisions": int_get(runtime_summary, "decision_needed_count"),
            "runtime_stabilization_ready_specs": int_get(runtime_summary, "ready_spec_count"),
            "do_not_count": len(do_not),
            "cutover_hard_stop_count": len(hard_stops),
            "p0_next_task_count": len(p0_next),
        },
        "external_blockers": external_blockers,
        "safe_reviews": safe_reviews,
        "guarded_actions": guarded_actions,
        "do_not": do_not,
        "cutover_hard_stops": hard_stops,
        "p0_next_tasks": p0_next[:8],
        "verify_sequence": [
            "control-plane-r2-secure-input-packet --json",
            "control-plane-r2-restic-intake --json",
            "tmux-cleanup-review --json",
            "hetzner-hardening-command-bundle --json",
            "nomarh-supervision-unit-bundle --json",
            "nomarh-cutover-guard --json",
            "nomarh-migration-state-manifest --json",
            "nomarh-state-transfer-plan --json",
            "nomarh-mail-production-gate --json",
            "nomarh-ops --refresh --json",
        ],
        "paths": {
            "status": str(STATUS_PATH),
            "report": str(REPORT_PATH),
            "snapshot": str(SNAPSHOT_STATUS),
            "p0_board": str(P0_BOARD_STATUS),
            "r2_intake": str(R2_INTAKE_STATUS),
            "r2_secure_input_packet": str(R2_SECURE_INPUT_PACKET_STATUS),
            "tmux_cleanup": str(TMUX_CLEANUP_STATUS),
            "runtime_stabilization": str(RUNTIME_STABILIZATION_STATUS),
            "hardening_bundle": str(HARDENING_BUNDLE_STATUS),
            "supervision_bundle": str(SUPERVISION_BUNDLE_STATUS),
            "cutover_guard": str(CUTOVER_GUARD_STATUS),
            "secret_rotation": str(SECRET_ROTATION_STATUS),
            "guarded_action_audit": str(GUARDED_ACTION_AUDIT_STATUS),
            "migration_state_manifest": str(MIGRATION_STATE_MANIFEST_STATUS),
            "state_transfer_plan": str(STATE_TRANSFER_PLAN_STATUS),
            "mail_production_gate": str(MAIL_PRODUCTION_GATE_STATUS),
        },
    }


def render_action_table(actions: list[dict[str, Any]]) -> list[str]:
    lines = ["| Lane | Title | Status | Kind | Next Action | Verify |", "|---|---|---|---|---|---|"]
    if not actions:
        lines.append("| none | none | none | none | none | none |")
        return lines
    for item in actions:
        lines.append(
            f"| `{safe_md(item['lane'])}` | {safe_md(item['title'])} | `{safe_md(item['status'])}` | `{safe_md(item['kind'])}` | {safe_md(item['next_action'])} | `{safe_md(item['verify'])}` |"
        )
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Nomarh Action Pack",
        "",
        "No secrets, env values, tmux pane output, private keys, or mailbox contents are read. This is an action routing surface, not an executor.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- External blockers: `{summary['external_blocker_count']}`",
        f"- Safe local reviews: `{summary['safe_review_count']}`",
        f"- Guarded actions: `{summary['guarded_action_count']}`",
        f"- R2 secure input packet: `{summary['r2_secure_input_packet_result']}`; missing groups `{summary['r2_secure_input_missing_groups']}`, active r2 `{summary['r2_secure_input_active_r2']}`",
        f"- Guarded action audit: `{summary['guarded_audit_result']}`; actions `{summary['guarded_audit_action_count']}`, blockers `{summary['guarded_audit_blockers']}`",
        f"- Migration state manifest: `{summary['migration_state_manifest_result']}`; surfaces `{summary['migration_state_manifest_surfaces']}`, secret-bearing `{summary['migration_state_manifest_secret_surfaces']}`, blockers `{summary['migration_state_manifest_blockers']}`",
        f"- State transfer plan: `{summary['state_transfer_result']}`; blocked surfaces `{summary['state_transfer_blocked_surfaces']}`, blocked services `{summary['state_transfer_blocked_services']}`, pending `{summary['state_transfer_pending_items']}`",
        f"- Mail production gate: `{summary['mail_production_gate_result']}`; blockers `{summary['mail_production_blockers']}`, warnings `{summary['mail_production_warnings']}`, MX `{summary['mail_production_mx_aligned']}`, SPF `{summary['mail_production_spf_aligned']}`, DKIM selectors `{summary['mail_production_dkim_selectors']}`",
        f"- Cutover hard stops: `{summary['cutover_hard_stop_count']}`",
        "",
        "## External Blockers",
        "",
    ]
    lines.extend(render_action_table(payload["external_blockers"]))
    lines.extend(["", "## Safe Local Reviews", ""])
    lines.extend(render_action_table(payload["safe_reviews"]))
    lines.extend(["", "## Guarded Actions", ""])
    lines.extend(render_action_table(payload["guarded_actions"]))

    lines.extend(["", "## Do Not", ""])
    if payload["do_not"]:
        lines.extend(f"- {safe_md(item)}" for item in payload["do_not"])
    else:
        lines.append("- No do-not rules generated.")

    lines.extend(["", "## Cutover Hard Stops", ""])
    if payload["cutover_hard_stops"]:
        lines.extend(f"- {safe_md(item)}" for item in payload["cutover_hard_stops"])
    else:
        lines.append("- No hard stops generated.")

    lines.extend(["", "## Verify Sequence", ""])
    lines.extend(f"{idx}. `{safe_md(command)}`" for idx, command in enumerate(payload["verify_sequence"], start=1))

    lines.extend(["", "## Source Paths", ""])
    for key, path in payload["paths"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a no-secret daily action pack for Nomarh operations")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_payload()
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Nomarh action pack")
        print(f"Result: {payload['result']}")
        print(f"External blockers: {payload['summary']['external_blocker_count']}")
        print(f"Safe reviews: {payload['summary']['safe_review_count']}")
        print(f"Guarded actions: {payload['summary']['guarded_action_count']}")
        print(f"Report: {REPORT_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

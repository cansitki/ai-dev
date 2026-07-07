#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-state-transfer-plan"
STATUS_PATH = STATE_DIR / "status.json"
PLAN_PATH = STATE_DIR / "plan.md"

MIGRATION_MANIFEST_STATUS = HOME / ".local/state/nomarh-migration-state-manifest/manifest.json"
RESTIC_BACKUP_STATUS = HOME / ".local/state/control-plane-restic-backup/status.json"
RESTORE_DRILL_STATUS = HOME / ".local/state/control-plane-restic-restore-drill/status.json"
SECRET_ROTATION_STATUS = HOME / ".local/state/nomarh-secret-rotation-plan/status.json"
RUNTIME_STABILIZATION_STATUS = HOME / ".local/state/nomarh-runtime-stabilization-board/status.json"
CUTOVER_GUARD_STATUS = HOME / ".local/state/nomarh-cutover-guard/guard.json"


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


def success(payload: Any) -> bool:
    return dict_get(payload, "result") in {"success", "ready", "ok"}


def secret_clean(secret_rotation: Any) -> bool:
    summary = dict_get(secret_rotation, "summary", {})
    return int_get(summary, "finding_files") == 0 and int_get(summary, "risky_doc_or_source_files") == 0


def surface_transfer(surface: dict[str, Any], *, backup_ready: bool, secrets_clean: bool) -> dict[str, Any]:
    decision = str(surface.get("decision") or "")
    path = str(surface.get("path") or "")
    secret_bearing = bool(surface.get("secret_bearing"))

    if decision == "status-only":
        transfer_method = "exclude-status-only"
        status = "excluded"
        gate = "none"
        next_action = "Keep as historical status only; do not use as restore source."
    elif decision == "recreate-or-include":
        transfer_method = "recreate-from-source-preferred"
        status = "pending-review"
        gate = "source-of-truth-review"
        next_action = "Prefer reinstalling operational scripts from source; include local bin only as restore context if needed."
    elif decision == "include-after-r2-ready":
        transfer_method = "encrypted-restic-restore"
        gate = "backup-and-restore-drill"
        if secret_bearing and not secrets_clean:
            status = "blocked"
            next_action = "Rotate/redact secret-bearing state before it can move."
        elif not backup_ready:
            status = "blocked"
            next_action = "Wait for successful real restic backup and restore drill before moving this state."
        else:
            status = "ready-to-restore"
            next_action = "Restore through restic into Hetzner and verify owner/mode before service start."
    else:
        transfer_method = "manual-review"
        status = "pending-review"
        gate = "operator-review"
        next_action = "Review manifest decision before copying or recreating."

    return {
        "path": path,
        "secret_bearing": secret_bearing,
        "manifest_decision": decision,
        "transfer_method": transfer_method,
        "status": status,
        "gate": gate,
        "next_action": next_action,
        "policy": str(surface.get("policy") or ""),
        "reason": str(surface.get("reason") or ""),
    }


def service_transfer(service: dict[str, Any], *, backup_ready: bool, runtime_ready: bool) -> dict[str, Any]:
    decision = str(service.get("decision") or "")
    name = str(service.get("name") or "")
    priority = str(service.get("priority") or "")
    risk = str(service.get("risk") or "")

    if decision == "recreate-as-supervised-service":
        transfer_method = "recreate-as-reviewed-service"
        if name == "vault-backup" and not backup_ready:
            status = "blocked"
            gate = "backup-and-restore-drill"
            next_action = "Keep backup timer blocked until real backup and restore drill pass."
        elif not runtime_ready and priority in {"P0", "P1"}:
            status = "pending-decision"
            gate = "runtime-stabilization-review"
            next_action = "Resolve runtime stabilization decision, then install only reviewed service/timer units."
        else:
            status = "ready-to-spec"
            gate = "reviewed-systemd-spec"
            next_action = "Review generated service/timer spec and install only with the guarded supervision path."
    elif decision == "keep-out-of-core-cutover":
        transfer_method = "defer-until-after-core"
        status = "deferred"
        gate = "post-core-provider-review"
        next_action = "Do not include in core AWS/main cutover; revisit after core services are stable."
    elif decision == "recreate-from-repo-if-needed":
        transfer_method = "optional-recreate-from-repo"
        status = "optional"
        gate = "operator-review"
        next_action = "Recreate from source only if still needed after core migration."
    elif decision == "manual-review-before-copy":
        transfer_method = "manual-review"
        status = "pending-review"
        gate = "operator-review"
        next_action = "Decide archive, retire, or recreate; avoid raw runtime copy."
    elif decision == "do-not-migrate":
        transfer_method = "exclude"
        status = "excluded"
        gate = "none"
        next_action = "Do not move to Hetzner."
    else:
        transfer_method = "manual-review"
        status = "pending-review"
        gate = "operator-review"
        next_action = "Review migration state manifest before moving."

    return {
        "name": name,
        "priority": priority,
        "risk": risk,
        "category": str(service.get("category") or ""),
        "target_model": str(service.get("target_model") or ""),
        "manifest_decision": decision,
        "transfer_method": transfer_method,
        "status": status,
        "gate": gate,
        "next_action": next_action,
        "policy": str(service.get("policy") or ""),
    }


def cleanup_transfer(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(review.get("name") or ""),
        "path": str(review.get("path") or ""),
        "status": "pending-handoff",
        "transfer_method": "do-not-copy-live-session",
        "gate": "manual-handoff",
        "next_action": "Write a handoff, archive, commit/stash, or explicitly retire before stopping or migrating this session.",
        "reason": str(review.get("reason") or ""),
        "verdict": str(review.get("verdict") or ""),
    }


def count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        name = str(item.get(key, "unknown"))
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def build_payload() -> dict[str, Any]:
    manifest = read_json(MIGRATION_MANIFEST_STATUS)
    restic_backup = read_json(RESTIC_BACKUP_STATUS)
    restore_drill = read_json(RESTORE_DRILL_STATUS)
    secret_rotation = read_json(SECRET_ROTATION_STATUS)
    runtime_stabilization = read_json(RUNTIME_STABILIZATION_STATUS)
    cutover_guard = read_json(CUTOVER_GUARD_STATUS)

    blockers: list[str] = []
    warnings: list[str] = []

    if not isinstance(manifest, dict):
        blockers.append(f"migration state manifest missing or invalid: {MIGRATION_MANIFEST_STATUS}")
        manifest = {}

    backup_ready = success(restic_backup) and success(restore_drill)
    secrets_clean = secret_clean(secret_rotation)
    runtime_summary = dict_get(runtime_stabilization, "summary", {})
    runtime_ready = int_get(runtime_summary, "decision_needed_count") == 0 and int_get(runtime_summary, "blocked_by_gate_count") == 0

    if not success(restic_backup):
        blockers.append("real restic backup has not succeeded")
    if not success(restore_drill):
        blockers.append("restore drill has not succeeded")
    if not secrets_clean:
        blockers.append("secret rotation plan is not clean")
    hard_stops = list_get(cutover_guard, "hard_stops")
    if hard_stops:
        warnings.append(f"cutover guard has {len(hard_stops)} hard stop(s)")
    if not runtime_ready:
        warnings.append(
            "runtime stabilization still has "
            f"{int_get(runtime_summary, 'decision_needed_count')} decision(s) and "
            f"{int_get(runtime_summary, 'blocked_by_gate_count')} blocked gate item(s)"
        )

    surface_transfers = [
        surface_transfer(item, backup_ready=backup_ready, secrets_clean=secrets_clean)
        for item in list_get(manifest, "surfaces")
        if isinstance(item, dict)
    ]
    service_transfers = [
        service_transfer(item, backup_ready=backup_ready, runtime_ready=runtime_ready)
        for item in list_get(manifest, "services")
        if isinstance(item, dict)
    ]
    cleanup_transfers = [
        cleanup_transfer(item) for item in list_get(manifest, "cleanup_reviews") if isinstance(item, dict)
    ]

    blocked_surfaces = sum(1 for item in surface_transfers if item["status"] == "blocked")
    blocked_services = sum(1 for item in service_transfers if item["status"] == "blocked")
    pending_items = sum(
        1
        for item in surface_transfers + service_transfers + cleanup_transfers
        if str(item.get("status", "")).startswith("pending")
    )

    result = "blocked" if blockers or blocked_surfaces or blocked_services else "warn" if warnings or pending_items else "ready"
    return {
        "schema": "nomarh-state-transfer-plan.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "summary": {
            "surface_count": len(surface_transfers),
            "service_count": len(service_transfers),
            "cleanup_handoff_count": len(cleanup_transfers),
            "secret_bearing_surface_count": sum(1 for item in surface_transfers if item["secret_bearing"]),
            "surface_status_counts": count_by(surface_transfers, "status"),
            "surface_method_counts": count_by(surface_transfers, "transfer_method"),
            "service_status_counts": count_by(service_transfers, "status"),
            "service_method_counts": count_by(service_transfers, "transfer_method"),
            "blocked_surface_count": blocked_surfaces,
            "blocked_service_count": blocked_services,
            "pending_item_count": pending_items,
            "backup_ready": backup_ready,
            "secrets_clean": secrets_clean,
            "runtime_ready": runtime_ready,
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
        },
        "blockers": blockers,
        "warnings": warnings,
        "surface_transfers": surface_transfers,
        "service_transfers": service_transfers,
        "cleanup_handoffs": cleanup_transfers,
        "do_not": [
            "Do not raw-copy secret-bearing state outside encrypted restic restore.",
            "Do not copy live tmux sessions as the Hetzner operating model.",
            "Do not use the old raw workspace R2 backup as source of truth.",
            "Do not start migrated services before restore verification and owner/mode checks.",
        ],
        "verify_sequence": [
            "nomarh-migration-state-manifest --json",
            "control-plane-restic-backup --json",
            "control-plane-restic-restore-drill --json",
            "nomarh-runtime-stabilization-board --json",
            "nomarh-state-transfer-plan --json",
            "nomarh-cutover-guard --json",
        ],
        "paths": {
            "status": str(STATUS_PATH),
            "plan": str(PLAN_PATH),
            "migration_manifest": str(MIGRATION_MANIFEST_STATUS),
            "restic_backup": str(RESTIC_BACKUP_STATUS),
            "restore_drill": str(RESTORE_DRILL_STATUS),
            "secret_rotation": str(SECRET_ROTATION_STATUS),
            "runtime_stabilization": str(RUNTIME_STABILIZATION_STATUS),
            "cutover_guard": str(CUTOVER_GUARD_STATUS),
        },
    }


def render_transfer_table(items: list[dict[str, Any]], *, name_key: str) -> list[str]:
    lines = ["| Name/Path | Status | Method | Gate | Next Action |", "|---|---|---|---|---|"]
    if not items:
        lines.append("| none | none | none | none | none |")
        return lines
    for item in items:
        name = item.get(name_key, "")
        if name_key == "path":
            name = f"`{safe_md(name)}`"
        else:
            name = f"`{safe_md(name)}`"
        lines.append(
            f"| {name} | `{safe_md(item.get('status'))}` | `{safe_md(item.get('transfer_method'))}` | `{safe_md(item.get('gate'))}` | {safe_md(item.get('next_action'))} |"
        )
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Nomarh State Transfer Plan",
        "",
        "No file contents, env values, tmux pane output, mailbox contents, private keys, or repo contents are read. This plan converts the migration state manifest into restore/recreate/exclude decisions.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Surfaces: `{summary['surface_count']}`; secret-bearing `{summary['secret_bearing_surface_count']}`; blocked `{summary['blocked_surface_count']}`",
        f"- Services: `{summary['service_count']}`; blocked `{summary['blocked_service_count']}`",
        f"- Cleanup handoffs: `{summary['cleanup_handoff_count']}`",
        f"- Pending items: `{summary['pending_item_count']}`",
        f"- Backup ready: `{summary['backup_ready']}`; secrets clean: `{summary['secrets_clean']}`; runtime ready: `{summary['runtime_ready']}`",
        f"- Blockers: `{summary['blocker_count']}`; warnings `{summary['warning_count']}`",
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

    lines.extend(["## Surface Transfers", ""])
    lines.extend(render_transfer_table(payload["surface_transfers"], name_key="path"))
    lines.extend(["", "## Service Transfers", ""])
    lines.extend(render_transfer_table(payload["service_transfers"], name_key="name"))
    lines.extend(["", "## Cleanup Handoffs", ""])
    lines.extend(render_transfer_table(payload["cleanup_handoffs"], name_key="name"))
    lines.extend(["", "## Do Not", ""])
    lines.extend(f"- {safe_md(item)}" for item in payload["do_not"])
    lines.extend(["", "## Verify Sequence", ""])
    lines.extend(f"{idx}. `{safe_md(command)}`" for idx, command in enumerate(payload["verify_sequence"], start=1))
    lines.extend(["", "## Source Paths", ""])
    for key, path in payload["paths"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def render_console(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return "\n".join(
        [
            "Nomarh State Transfer Plan",
            f"Result: {payload['result']}",
            f"Surfaces: {summary['surface_count']} secret={summary['secret_bearing_surface_count']} blocked={summary['blocked_surface_count']}",
            f"Services: {summary['service_count']} blocked={summary['blocked_service_count']}",
            f"Cleanup handoffs: {summary['cleanup_handoff_count']} pending={summary['pending_item_count']}",
            f"Backup ready: {summary['backup_ready']} secrets clean: {summary['secrets_clean']} runtime ready: {summary['runtime_ready']}",
            f"Plan: {PLAN_PATH}",
            f"Status: {STATUS_PATH}",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build no-secret restore/recreate/exclude transfer plan for Nomarh state migration")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_payload()
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(PLAN_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_console(payload))
    return 2 if payload["result"] == "blocked" else 1 if payload["result"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())

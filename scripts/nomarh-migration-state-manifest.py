#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-migration-state-manifest"
STATUS_PATH = STATE_DIR / "manifest.json"
REPORT_PATH = STATE_DIR / "manifest.md"

BACKUP_READINESS_STATUS = HOME / ".local/state/control-plane-backup-readiness/status.json"
R2_INTAKE_STATUS = HOME / ".local/state/control-plane-r2-restic-intake/status.json"
RESTIC_BACKUP_STATUS = HOME / ".local/state/control-plane-restic-backup/status.json"
RESTORE_DRILL_STATUS = HOME / ".local/state/control-plane-restic-restore-drill/status.json"
SERVICE_MAP_STATUS = HOME / ".local/state/nomarh-service-migration-map/map.json"
TMUX_CLEANUP_STATUS = HOME / ".local/state/tmux-cleanup-review/status.json"
SECRET_ROTATION_STATUS = HOME / ".local/state/nomarh-secret-rotation-plan/status.json"
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


def surface_decision(surface: dict[str, Any]) -> dict[str, Any]:
    path = str(surface.get("path") or "")
    secret_bearing = bool(surface.get("secret_bearing"))
    if secret_bearing:
        decision = "include-after-r2-ready"
        policy = "encrypted-restic-only"
        reason = "secret-bearing state must only move through encrypted backup/restore"
    elif path == "/home/coder/Can":
        decision = "include-after-r2-ready"
        policy = "vault-git-plus-restic"
        reason = "vault is source of truth; secret scan must stay clean"
    elif path.endswith("/.local/bin"):
        decision = "recreate-or-include"
        policy = "restore convenience; source scripts should come from repo where possible"
        reason = "local operational CLIs are useful but should not be the only source of truth"
    else:
        decision = "include-after-r2-ready"
        policy = "encrypted-restic"
        reason = "operational status/config surface required for restore context"
    return {
        "path": path,
        "exists": bool(surface.get("exists")),
        "secret_bearing": secret_bearing,
        "decision": decision,
        "policy": policy,
        "reason": reason,
    }


def service_decision(item: dict[str, Any]) -> dict[str, Any]:
    priority = str(item.get("priority") or "")
    category = str(item.get("category") or "")
    target = str(item.get("target_model") or "")
    risk = str(item.get("risk") or "")
    name = str(item.get("name") or "")

    if priority in {"P0", "P1"}:
        decision = "recreate-as-supervised-service"
        policy = "do-not-copy-tmux-session"
    elif priority == "retire" or "retired" in target:
        decision = "do-not-migrate"
        policy = "replace-or-retire"
    elif target in {"review/archive", "review", "review or retire"} or priority == "P3":
        decision = "manual-review-before-copy"
        policy = "archive-or-recreate-from-repo"
    elif category == "provider_worker":
        decision = "keep-out-of-core-cutover"
        policy = "provider supervisor after core migration"
    else:
        decision = "recreate-from-repo-if-needed"
        policy = "not core cutover state"

    return {
        "name": name,
        "priority": priority,
        "risk": risk,
        "category": category,
        "target_model": target,
        "decision": decision,
        "policy": policy,
        "action": str(item.get("action") or ""),
    }


def cleanup_decision(review: dict[str, Any]) -> dict[str, Any]:
    verdict = str(review.get("verdict") or "")
    return {
        "name": str(review.get("name") or ""),
        "path": str(review.get("path") or ""),
        "verdict": verdict,
        "decision": "manual-review-before-stop-or-copy",
        "policy": "do-not-copy-live-session",
        "reason": str(review.get("reason") or ""),
    }


def build_payload() -> dict[str, Any]:
    backup = read_json(BACKUP_READINESS_STATUS)
    intake = read_json(R2_INTAKE_STATUS)
    restic = read_json(RESTIC_BACKUP_STATUS)
    restore = read_json(RESTORE_DRILL_STATUS)
    service_map = read_json(SERVICE_MAP_STATUS)
    cleanup = read_json(TMUX_CLEANUP_STATUS)
    secret_rotation = read_json(SECRET_ROTATION_STATUS)
    cutover = read_json(CUTOVER_GUARD_STATUS)

    surfaces = [surface_decision(item) for item in list_get(backup, "surfaces") if isinstance(item, dict)]
    services = [service_decision(item) for item in list_get(service_map, "items") if isinstance(item, dict)]
    cleanup_items = [cleanup_decision(item) for item in list_get(cleanup, "reviews") if isinstance(item, dict)]

    blockers: list[str] = []
    warnings: list[str] = []

    if dict_get(intake, "result") != "ready":
        blockers.append("R2/restic intake is not ready; migration state cannot be safely backed up/restored.")
    if dict_get(restic, "result") != "success":
        blockers.append("A real restic backup has not succeeded.")
    if dict_get(restore, "result") != "success":
        blockers.append("Restore drill has not succeeded.")
    secret_summary = dict_get(secret_rotation, "summary", {})
    if int_get(secret_summary, "finding_files") or int_get(secret_summary, "risky_doc_or_source_files"):
        blockers.append("Secret rotation plan is not clean.")
    if cleanup_items:
        warnings.append(f"{len(cleanup_items)} tmux cleanup candidate(s) require manual review before copying runtime state.")
    cutover_hard_stops = list_get(cutover, "hard_stops")
    if cutover_hard_stops:
        warnings.append(f"Cutover guard still has {len(cutover_hard_stops)} hard stop(s).")

    surface_counts: dict[str, int] = {}
    for item in surfaces:
        key = str(item["decision"])
        surface_counts[key] = surface_counts.get(key, 0) + 1
    service_counts: dict[str, int] = {}
    for item in services:
        key = str(item["decision"])
        service_counts[key] = service_counts.get(key, 0) + 1

    result = "blocked" if blockers else "warn" if warnings else "ready"
    return {
        "schema": "nomarh-migration-state-manifest.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "summary": {
            "surface_count": len(surfaces),
            "secret_bearing_surface_count": sum(1 for item in surfaces if item["secret_bearing"]),
            "surface_decisions": dict(sorted(surface_counts.items())),
            "service_count": len(services),
            "service_decisions": dict(sorted(service_counts.items())),
            "cleanup_review_count": len(cleanup_items),
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
        },
        "blockers": blockers,
        "warnings": warnings,
        "surfaces": surfaces,
        "services": services,
        "cleanup_reviews": cleanup_items,
        "do_not": [
            "Do not copy raw tmux sessions as the Hetzner operating model.",
            "Do not use the old raw workspace R2 backup as the source of truth.",
            "Do not move secret-bearing state except through encrypted backup/restore.",
            "Do not cut over until real backup and restore drill are successful.",
        ],
        "verify_sequence": [
            "control-plane-r2-restic-intake --json",
            "control-plane-restic-backup --json",
            "control-plane-restic-restore-drill --json",
            "nomarh-migration-state-manifest --json",
            "nomarh-cutover-guard --json",
            "nomarh-ops --refresh --json",
        ],
        "paths": {
            "status": str(STATUS_PATH),
            "report": str(REPORT_PATH),
            "backup_readiness": str(BACKUP_READINESS_STATUS),
            "r2_intake": str(R2_INTAKE_STATUS),
            "restic_backup": str(RESTIC_BACKUP_STATUS),
            "restore_drill": str(RESTORE_DRILL_STATUS),
            "service_map": str(SERVICE_MAP_STATUS),
            "tmux_cleanup": str(TMUX_CLEANUP_STATUS),
            "secret_rotation": str(SECRET_ROTATION_STATUS),
            "cutover_guard": str(CUTOVER_GUARD_STATUS),
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Nomarh Migration State Manifest",
        "",
        "No file contents, env values, tmux pane output, private keys, or mailbox contents are read. This manifest classifies existing status surfaces and service decisions for safe migration.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- State surfaces: `{summary['surface_count']}`",
        f"- Secret-bearing surfaces: `{summary['secret_bearing_surface_count']}`",
        f"- Services/items: `{summary['service_count']}`",
        f"- Cleanup reviews: `{summary['cleanup_review_count']}`",
        f"- Blockers: `{summary['blocker_count']}`",
        f"- Warnings: `{summary['warning_count']}`",
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

    lines.extend(["## State Surfaces", "", "| Decision | Path | Secret-bearing | Policy | Reason |", "|---|---|---|---|---|"])
    for item in payload["surfaces"]:
        lines.append(
            f"| `{safe_md(item['decision'])}` | `{safe_md(item['path'])}` | `{item['secret_bearing']}` | {safe_md(item['policy'])} | {safe_md(item['reason'])} |"
        )

    lines.extend(["", "## Service Decisions", "", "| Decision | Name | Priority | Risk | Target | Policy |", "|---|---|---|---|---|---|"])
    for item in payload["services"]:
        lines.append(
            f"| `{safe_md(item['decision'])}` | `{safe_md(item['name'])}` | `{safe_md(item['priority'])}` | `{safe_md(item['risk'])}` | {safe_md(item['target_model'])} | {safe_md(item['policy'])} |"
        )

    lines.extend(["", "## Cleanup Reviews", "", "| Name | Verdict | Decision | Path | Reason |", "|---|---|---|---|---|"])
    if payload["cleanup_reviews"]:
        for item in payload["cleanup_reviews"]:
            lines.append(
                f"| `{safe_md(item['name'])}` | `{safe_md(item['verdict'])}` | `{safe_md(item['decision'])}` | `{safe_md(item['path'])}` | {safe_md(item['reason'])} |"
            )
    else:
        lines.append("| none | none | none | none | none |")

    lines.extend(["", "## Do Not", ""])
    lines.extend(f"- {safe_md(item)}" for item in payload["do_not"])
    lines.extend(["", "## Verify Sequence", ""])
    lines.extend(f"{idx}. `{safe_md(command)}`" for idx, command in enumerate(payload["verify_sequence"], start=1))
    lines.extend(["", "## Source Paths", ""])
    for key, path in payload["paths"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate no-secret state manifest for Nomarh AWS/main to Hetzner migration")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_payload()
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Nomarh migration state manifest")
        print(f"Result: {payload['result']}")
        print(f"State surfaces: {payload['summary']['surface_count']}")
        print(f"Services/items: {payload['summary']['service_count']}")
        print(f"Report: {REPORT_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

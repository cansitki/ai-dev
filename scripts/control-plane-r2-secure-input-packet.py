#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/control-plane-r2-secure-input-packet"
STATUS_PATH = STATE_DIR / "status.json"
PACKET_PATH = STATE_DIR / "packet.md"

INTAKE_STATUS = HOME / ".local/state/control-plane-r2-restic-intake/status.json"
BOOTSTRAP_STATUS = HOME / ".local/state/control-plane-r2-restic-bootstrap/status.json"
REMOTE_CONFIG_STATUS = HOME / ".local/state/control-plane-r2-remote-config/status.json"
BACKUP_STATUS = HOME / ".local/state/control-plane-restic-backup/status.json"
RESTORE_STATUS = HOME / ".local/state/control-plane-restic-restore-drill/status.json"


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


def status_result(payload: Any) -> str:
    return str(dict_get(payload, "result", "missing"))


def source_summary(path: Path, payload: Any) -> dict[str, Any]:
    summary = dict_get(payload, "summary", {})
    return {
        "path": str(path),
        "present": isinstance(payload, dict),
        "result": status_result(payload),
        "updated_at": dict_get(payload, "updated_at", ""),
        "blocker_count": int_get(summary, "blocker_count") if isinstance(summary, dict) else len(list_get(payload, "blockers")),
        "warning_count": int_get(summary, "warning_count") if isinstance(summary, dict) else len(list_get(payload, "warnings")),
    }


def input_groups(intake: Any, bootstrap: Any) -> list[dict[str, Any]]:
    raw_groups = list_get(intake, "input_groups") or list_get(bootstrap, "env_groups")
    groups: list[dict[str, Any]] = []
    for group in raw_groups:
        if not isinstance(group, dict):
            continue
        groups.append(
            {
                "id": str(group.get("id", "")),
                "label": str(group.get("label", "")),
                "present": bool(group.get("present", False)),
                "accepted_names": [str(name) for name in group.get("names", []) if str(name).strip()],
                "note": str(group.get("note", "")),
                "required": bool(group.get("required", True)),
            }
        )
    return groups


def missing_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [group for group in groups if group["required"] and not group["present"]]


def build_payload() -> dict[str, Any]:
    intake = read_json(INTAKE_STATUS)
    bootstrap = read_json(BOOTSTRAP_STATUS)
    remote_config = read_json(REMOTE_CONFIG_STATUS)
    backup = read_json(BACKUP_STATUS)
    restore = read_json(RESTORE_STATUS)

    groups = input_groups(intake, bootstrap)
    missing = missing_groups(groups)
    intake_paths = dict_get(intake, "paths", {})
    remote_paths = dict_get(remote_config, "paths", {})
    secure_env_file = str(dict_get(intake_paths, "secure_env_file") or dict_get(remote_paths, "env_file") or HOME / ".config/nomarh/control-plane-restic.env")
    password_file = str(dict_get(intake_paths, "default_password_file") or HOME / ".config/nomarh/restic-password")
    env_example = str(dict_get(intake_paths, "env_example") or "")
    setup_commands = str(dict_get(intake_paths, "setup_commands") or "")

    tools = dict_get(intake, "tools", {})
    active_r2 = bool(dict_get(tools, "active_r2_remote", False))
    restic_installed = bool(dict_get(tools, "restic_installed", False))
    rclone_installed = bool(dict_get(tools, "rclone_installed", False))

    blockers: list[str] = []
    warnings: list[str] = []
    if not isinstance(intake, dict):
        blockers.append("R2/restic intake status is missing; run `control-plane-r2-restic-intake --json`.")
    if missing:
        blockers.append(f"{len(missing)} required secure input group(s) are missing.")
    if not active_r2:
        blockers.append("active rclone remote `r2:` is not configured.")
    if not restic_installed:
        blockers.append("restic is not installed.")
    if not rclone_installed:
        blockers.append("rclone is not installed.")
    if status_result(backup) != "success":
        warnings.append("real restic backup has not succeeded yet.")
    if status_result(restore) != "success":
        warnings.append("restore drill has not succeeded yet.")

    result = "blocked" if blockers else "ready"
    return {
        "schema": "control-plane-r2-secure-input-packet.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "summary": {
            "required_input_groups": len([group for group in groups if group["required"]]),
            "present_required_input_groups": len([group for group in groups if group["required"] and group["present"]]),
            "missing_required_input_groups": len(missing),
            "active_r2_remote": active_r2,
            "restic_installed": restic_installed,
            "rclone_installed": rclone_installed,
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
        },
        "secure_paths": {
            "secure_env_file": secure_env_file,
            "restic_password_file": password_file,
            "env_example": env_example,
            "setup_commands": setup_commands,
        },
        "input_groups": groups,
        "missing_input_groups": missing,
        "blockers": blockers,
        "warnings": warnings,
        "operator_packet": {
            "safe_transfer_rule": "Use a secure secret channel or local terminal entry. Do not paste values into chat, vault notes, shell history, Git, Discord, or tmux pane output.",
            "needs": [
                "Cloudflare R2 endpoint or account id",
                "Cloudflare R2 bucket name",
                "Scoped R2 S3 access key id",
                "Scoped R2 S3 secret access key",
                "Restic encryption password stored in a 0600 local password file",
                "Rclone remote named r2:",
            ],
            "after_input_verify": [
                "control-plane-r2-restic-intake --json",
                "control-plane-r2-remote-config --json",
                "NOMARH_R2_REMOTE_CONFIG_APPLY=reviewed control-plane-r2-remote-config --apply --json",
                "control-plane-r2-restic-bootstrap --json",
                "control-plane-restic-backup --init --dry-run",
                "control-plane-restic-backup --json",
                "control-plane-restic-restore-drill --json",
                "nomarh-operator-card --refresh --json",
            ],
        },
        "sources": {
            "intake": source_summary(INTAKE_STATUS, intake),
            "bootstrap": source_summary(BOOTSTRAP_STATUS, bootstrap),
            "remote_config": source_summary(REMOTE_CONFIG_STATUS, remote_config),
            "backup": source_summary(BACKUP_STATUS, backup),
            "restore": source_summary(RESTORE_STATUS, restore),
        },
        "paths": {"status": str(STATUS_PATH), "packet": str(PACKET_PATH)},
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    secure_paths = payload["secure_paths"]
    packet = payload["operator_packet"]
    lines = [
        "# Control Plane R2 Secure Input Packet",
        "",
        "No secret values are read or printed. This packet states what is missing and how to validate it after secure entry.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Required input groups present: `{summary['present_required_input_groups']}/{summary['required_input_groups']}`",
        f"- Missing required input groups: `{summary['missing_required_input_groups']}`",
        f"- Active `r2:` remote: `{summary['active_r2_remote']}`",
        f"- restic installed: `{summary['restic_installed']}`",
        f"- rclone installed: `{summary['rclone_installed']}`",
        "",
        "## Safe Transfer Rule",
        "",
        safe_md(packet["safe_transfer_rule"]),
        "",
        "## Required Inputs",
        "",
        "| Input | Present | Accepted Names | Note |",
        "|---|---:|---|---|",
    ]
    for group in payload["input_groups"]:
        lines.append(
            f"| {safe_md(group['label'])} | `{group['present']}` | `{safe_md(', '.join(group['accepted_names']))}` | {safe_md(group['note'])} |"
        )
    lines.extend(
        [
            "",
            "## Secure Paths",
            "",
            f"- Secure env file: `{safe_md(secure_paths['secure_env_file'])}`",
            f"- Restic password file: `{safe_md(secure_paths['restic_password_file'])}`",
            f"- Env example: `{safe_md(secure_paths['env_example'])}`",
            f"- Setup commands: `{safe_md(secure_paths['setup_commands'])}`",
            "",
            "## Needed From Operator",
            "",
        ]
    )
    lines.extend(f"- {safe_md(item)}" for item in packet["needs"])
    if payload["blockers"]:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["blockers"])
    if payload["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["warnings"])
    lines.extend(["", "## Verify After Secure Input", ""])
    lines.extend(f"{idx}. `{safe_md(command)}`" for idx, command in enumerate(packet["after_input_verify"], start=1))
    lines.extend(["", "## Source Status", "", "| Source | Result | Blockers | Path |", "|---|---|---:|---|"])
    for name, source in payload["sources"].items():
        lines.append(
            f"| `{safe_md(name)}` | `{safe_md(source['result'])}` | `{source['blocker_count']}` | `{safe_md(source['path'])}` |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a no-secret secure input packet for R2/restic backup setup")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_payload()
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(PACKET_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Control-plane R2 secure input packet")
        print(f"Result: {payload['result']}")
        print(
            "Required input groups: "
            f"{payload['summary']['present_required_input_groups']}/{payload['summary']['required_input_groups']}"
        )
        print(f"Packet: {PACKET_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

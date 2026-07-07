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
STATE_DIR = HOME / ".local/state/control-plane-r2-restic-bootstrap"
STATUS_PATH = STATE_DIR / "status.json"
REPORT_PATH = STATE_DIR / "bootstrap.md"
ENV_TEMPLATE_PATH = STATE_DIR / "control-plane-restic.env.example"
DEFAULT_ENV_FILE = HOME / ".config/nomarh/control-plane-restic.env"

BACKUP_READINESS_STATUS = HOME / ".local/state/control-plane-backup-readiness/status.json"
RESTIC_BACKUP_STATUS = HOME / ".local/state/control-plane-restic-backup/status.json"
RESTORE_DRILL_STATUS = HOME / ".local/state/control-plane-restic-restore-drill/status.json"

REQUIRED_GROUPS = [
    {
        "id": "endpoint",
        "label": "Cloudflare R2 endpoint",
        "names": ["R2_ENDPOINT", "R2_ACCOUNT_ID"],
        "required": True,
        "note": "Use R2_ENDPOINT directly, or R2_ACCOUNT_ID so the runner can derive the endpoint.",
    },
    {
        "id": "bucket",
        "label": "Cloudflare R2 bucket",
        "names": ["R2_BUCKET"],
        "required": True,
        "note": "Use a dedicated bucket or prefix for encrypted control-plane backups.",
    },
    {
        "id": "access_key",
        "label": "R2 S3 access key",
        "names": ["R2_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"],
        "required": True,
        "note": "Prefer a scoped R2 token/key with only the required bucket permissions.",
    },
    {
        "id": "secret_key",
        "label": "R2 S3 secret key",
        "names": ["R2_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"],
        "required": True,
        "note": "Do not paste the value into chat, shell history, or vault notes.",
    },
    {
        "id": "restic_password",
        "label": "Restic encryption password",
        "names": ["RESTIC_PASSWORD", "RESTIC_PASSWORD_FILE"],
        "required": True,
        "note": "RESTIC_PASSWORD_FILE is preferred for unattended jobs.",
    },
    {
        "id": "prefix",
        "label": "Restic repository prefix",
        "names": ["R2_RESTIC_PREFIX"],
        "required": False,
        "note": "Optional; defaults to nomarh-control-plane-restic.",
    },
]


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_env_file() -> Path:
    configured = os.environ.get("CONTROL_PLANE_RESTIC_ENV_FILE") or os.environ.get("NOMARH_RESTIC_ENV_FILE")
    return Path(configured).expanduser() if configured else DEFAULT_ENV_FILE


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


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def load_env(env_file: Path, *, explicit: bool) -> tuple[dict[str, str], dict[str, Any], list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    file_values: dict[str, str] = {}
    status = {
        "path": str(env_file),
        "present": env_file.exists(),
        "explicit": explicit,
        "mode": "",
        "mode_secure": None,
        "loaded_names": [],
    }

    if env_file.exists():
        try:
            stat = env_file.stat()
            mode = stat.st_mode & 0o777
            status["mode"] = oct(mode)
            status["mode_secure"] = (mode & 0o077) == 0
            if not status["mode_secure"]:
                warnings.append(f"env file is readable by group/others: {env_file}")
            file_values = parse_env_file(env_file)
            status["loaded_names"] = sorted(file_values)
        except Exception as exc:
            blockers.append(f"could not read env file {env_file}: {exc}")
    elif explicit:
        blockers.append(f"explicit env file does not exist: {env_file}")

    merged = file_values.copy()
    merged.update(os.environ)
    return merged, status, warnings, blockers


def write_env_template() -> None:
    text = """# Copy to ~/.config/nomarh/control-plane-restic.env and chmod 600.
# Do not commit this file and do not paste filled values into chat or vault notes.

# Option A: account id lets the runner derive https://<account>.r2.cloudflarestorage.com
R2_ACCOUNT_ID=
# Option B: set R2_ENDPOINT directly instead of R2_ACCOUNT_ID
# R2_ENDPOINT=

R2_BUCKET=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=

# Prefer RESTIC_PASSWORD_FILE for unattended jobs.
RESTIC_PASSWORD_FILE=/home/coder/.config/nomarh/restic-password
# RESTIC_PASSWORD=

R2_RESTIC_PREFIX=nomarh-control-plane-restic
"""
    write_text_atomic(ENV_TEMPLATE_PATH, text)
    ENV_TEMPLATE_PATH.chmod(0o600)


def run(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except Exception as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


def env_group_status(group: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    present_names = [name for name in group["names"] if bool(env.get(name, "").strip())]
    return {
        "id": group["id"],
        "label": group["label"],
        "names": group["names"],
        "required": group["required"],
        "present": bool(present_names),
        "present_names": present_names,
        "note": group["note"],
    }


def restic_password_file_status(env: dict[str, str]) -> tuple[dict[str, Any], list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    configured = env.get("RESTIC_PASSWORD_FILE", "").strip()
    status: dict[str, Any] = {
        "configured": bool(configured),
        "path": configured,
        "present": None,
        "is_file": None,
        "mode": "",
        "mode_secure": None,
        "size_bytes": None,
        "nonempty": None,
    }
    if not configured:
        return status, warnings, blockers

    path = Path(configured).expanduser()
    status["path"] = str(path)
    try:
        stat = path.stat()
    except FileNotFoundError:
        status["present"] = False
        blockers.append("RESTIC_PASSWORD_FILE is set but the file does not exist")
        return status, warnings, blockers
    except OSError as exc:
        blockers.append(f"could not stat RESTIC_PASSWORD_FILE: {exc}")
        return status, warnings, blockers

    mode = stat.st_mode & 0o777
    status["present"] = True
    status["is_file"] = path.is_file()
    status["mode"] = oct(mode)
    status["mode_secure"] = (mode & 0o077) == 0
    status["size_bytes"] = stat.st_size
    status["nonempty"] = stat.st_size > 0

    if not status["is_file"]:
        blockers.append("RESTIC_PASSWORD_FILE is not a regular file")
    if not status["nonempty"]:
        blockers.append("RESTIC_PASSWORD_FILE is empty")
    if not status["mode_secure"]:
        blockers.append("RESTIC_PASSWORD_FILE is readable by group/others; chmod 600 before using it")
    return status, warnings, blockers


def tool_status() -> dict[str, Any]:
    rclone_remotes: list[str] = []
    rclone = shutil.which("rclone")
    if rclone:
        proc = run(["rclone", "listremotes"], timeout=10)
        if proc.returncode == 0:
            rclone_remotes = [line.strip() for line in proc.stdout.splitlines() if line.strip()]

    return {
        "restic_installed": shutil.which("restic") is not None,
        "rclone_installed": rclone is not None,
        "rclone_remotes": rclone_remotes,
        "active_r2_remote": "r2:" in rclone_remotes,
    }


def status_summary(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        return {"path": str(path), "present": False, "result": "missing", "blocker_count": "?"}
    blockers = payload.get("blockers") if isinstance(payload.get("blockers"), list) else []
    return {
        "path": str(path),
        "present": True,
        "updated_at": payload.get("updated_at", ""),
        "result": payload.get("result", "unknown"),
        "blocker_count": len(blockers),
    }


def build_payload(env_file: Path, *, explicit_env_file: bool) -> dict[str, Any]:
    env, env_file_status, env_warnings, env_blockers = load_env(env_file, explicit=explicit_env_file)
    tools = tool_status()
    env_groups = [env_group_status(group, env) for group in REQUIRED_GROUPS]
    password_file_status, password_file_warnings, password_file_blockers = restic_password_file_status(env)
    blockers: list[str] = env_blockers[:]
    warnings: list[str] = env_warnings[:]
    blockers.extend(password_file_blockers)
    warnings.extend(password_file_warnings)

    if not tools["restic_installed"]:
        blockers.append("restic is not installed")
    if not tools["rclone_installed"]:
        blockers.append("rclone is not installed")
    if not tools["active_r2_remote"]:
        blockers.append("active rclone remote r2: is not configured")

    for group in env_groups:
        if group["required"] and not group["present"]:
            blockers.append(f"missing secure input group: {group['label']} ({' or '.join(group['names'])})")

    if not any(group["id"] == "prefix" and group["present"] for group in env_groups):
        warnings.append("R2_RESTIC_PREFIX is not set; the restic runner will use nomarh-control-plane-restic.")

    gates = {
        "backup_readiness": status_summary(BACKUP_READINESS_STATUS),
        "restic_backup": status_summary(RESTIC_BACKUP_STATUS),
        "restore_drill": status_summary(RESTORE_DRILL_STATUS),
    }

    result = "blocked" if blockers else "ready-to-dry-run"
    if blockers:
        next_action = "Provide the missing R2/restic inputs through the secure path, configure `r2:`, then run `control-plane-r2-restic-bootstrap --json` again."
    else:
        next_action = "Run `control-plane-restic-backup --init --dry-run`, then a real backup and `control-plane-restic-restore-drill --json`."

    return {
        "schema": "control-plane-r2-restic-bootstrap.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "summary": {
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
            "required_input_groups": sum(1 for group in env_groups if group["required"]),
            "present_required_input_groups": sum(1 for group in env_groups if group["required"] and group["present"]),
        },
        "tools": tools,
        "env_file": env_file_status,
        "password_file": password_file_status,
        "env_template": str(ENV_TEMPLATE_PATH),
        "env_groups": env_groups,
        "gates": gates,
        "blockers": blockers,
        "warnings": warnings,
        "next_action": next_action,
        "verify_sequence": [
            "control-plane-r2-restic-bootstrap --json",
            "control-plane-backup-readiness",
            "control-plane-restic-backup --init --dry-run",
            "control-plane-restic-backup --json",
            "control-plane-restic-restore-drill --json",
            "can-ops-refresh --json",
        ],
        "paths": {"status": str(STATUS_PATH), "report": str(REPORT_PATH)},
    }


def safe_md(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Control Plane R2 Restic Bootstrap",
        "",
        "No secret values are read or printed. This checker only reports whether required variable groups and local tools are present.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Required input groups present: {payload['summary']['present_required_input_groups']}/{payload['summary']['required_input_groups']}",
        f"- Blockers: {payload['summary']['blocker_count']}",
        f"- Warnings: {payload['summary']['warning_count']}",
        f"- Env file: `{safe_md(payload['env_file']['path'])}`",
        f"- Env file present: `{payload['env_file']['present']}`",
            f"- Env file mode secure: `{payload['env_file']['mode_secure']}`",
            f"- Restic password file configured: `{payload['password_file']['configured']}`",
            f"- Restic password file present: `{payload['password_file']['present']}`",
            f"- Restic password file nonempty: `{payload['password_file']['nonempty']}`",
            f"- Restic password file mode secure: `{payload['password_file']['mode_secure']}`",
            f"- Env template: `{safe_md(payload['env_template'])}`",
        "",
        "## Inputs",
        "",
        "| Input | Required | Present | Accepted names | Note |",
        "|---|---|---|---|---|",
    ]
    for group in payload["env_groups"]:
        lines.append(
            f"| {safe_md(group['label'])} | `{group['required']}` | `{group['present']}` | `{safe_md(', '.join(group['names']))}` | {safe_md(group['note'])} |"
        )

    lines.extend(
        [
            "",
            "## Secure Env File",
            "",
            f"- Path: `{safe_md(payload['env_file']['path'])}`",
            f"- Present: `{payload['env_file']['present']}`",
            f"- Mode: `{safe_md(payload['env_file']['mode']) or 'missing'}`",
            f"- Mode secure: `{payload['env_file']['mode_secure']}`",
            f"- Loaded names: `{safe_md(', '.join(payload['env_file']['loaded_names']) or 'none')}`",
            f"- Template: `{safe_md(payload['env_template'])}`",
            "",
            "## Tools",
            "",
            f"- restic installed: `{payload['tools']['restic_installed']}`",
            f"- rclone installed: `{payload['tools']['rclone_installed']}`",
            f"- active `r2:` remote: `{payload['tools']['active_r2_remote']}`",
            f"- configured remotes: `{safe_md(', '.join(payload['tools']['rclone_remotes']) or 'none')}`",
            "",
        ]
    )

    if payload["blockers"]:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["blockers"])
        lines.append("")

    if payload["warnings"]:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["warnings"])
        lines.append("")

    lines.extend(["## Current Gates", "", "| Gate | Result | Blockers | Status path |", "|---|---|---:|---|"])
    for label, gate in payload["gates"].items():
        lines.append(
            f"| `{safe_md(label)}` | `{safe_md(gate['result'])}` | {safe_md(gate['blocker_count'])} | `{safe_md(gate['path'])}` |"
        )

    lines.extend(["", "## Verify Sequence", ""])
    lines.extend(f"{idx}. `{safe_md(command)}`" for idx, command in enumerate(payload["verify_sequence"], start=1))
    lines.extend(["", "## Next Action", "", safe_md(payload["next_action"]), ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the no-secret bootstrap state for R2-backed restic control-plane backups")
    parser.add_argument("--env-file", help="optional secure env file; defaults to ~/.config/nomarh/control-plane-restic.env")
    parser.add_argument("--json", action="store_true", help="print JSON status")
    args = parser.parse_args()

    write_env_template()
    env_file = Path(args.env_file).expanduser() if args.env_file else default_env_file()
    payload = build_payload(env_file, explicit_env_file=args.env_file is not None)
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Control-plane R2/restic bootstrap")
        print(f"Result: {payload['result']}")
        print(f"Required input groups: {payload['summary']['present_required_input_groups']}/{payload['summary']['required_input_groups']}")
        print(f"Status: {STATUS_PATH}")
        print(f"Report: {REPORT_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

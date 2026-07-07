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
STATE_DIR = HOME / ".local/state/control-plane-r2-restic-intake"
STATUS_PATH = STATE_DIR / "status.json"
REPORT_PATH = STATE_DIR / "intake.md"
ENV_EXAMPLE_PATH = STATE_DIR / "control-plane-restic.env.example"
COMMANDS_PATH = STATE_DIR / "setup-commands.md"
DEFAULT_ENV_FILE = HOME / ".config/nomarh/control-plane-restic.env"
DEFAULT_PASSWORD_FILE = HOME / ".config/nomarh/restic-password"

REQUIRED_GROUPS = [
    {
        "id": "endpoint",
        "label": "Cloudflare R2 endpoint",
        "names": ["R2_ENDPOINT", "R2_ACCOUNT_ID"],
        "note": "Use R2_ACCOUNT_ID or the full S3 endpoint for the account.",
    },
    {
        "id": "bucket",
        "label": "Cloudflare R2 bucket",
        "names": ["R2_BUCKET"],
        "note": "Use a dedicated bucket or prefix for encrypted control-plane backups.",
    },
    {
        "id": "access_key",
        "label": "R2 S3 access key",
        "names": ["R2_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"],
        "note": "Prefer a scoped R2 key limited to the backup bucket.",
    },
    {
        "id": "secret_key",
        "label": "R2 S3 secret key",
        "names": ["R2_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"],
        "note": "Never paste the value into chat, shell history, or vault notes.",
    },
    {
        "id": "restic_password",
        "label": "Restic encryption password",
        "names": ["RESTIC_PASSWORD_FILE", "RESTIC_PASSWORD"],
        "note": "RESTIC_PASSWORD_FILE is preferred for unattended jobs.",
    },
]


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_env_file() -> Path:
    configured = os.environ.get("CONTROL_PLANE_RESTIC_ENV_FILE") or os.environ.get("NOMARH_RESTIC_ENV_FILE")
    return Path(configured).expanduser() if configured else DEFAULT_ENV_FILE


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text_atomic(path: Path, text: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if not text.endswith("\n"):
        text += "\n"
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(mode)
    tmp.replace(path)
    path.chmod(mode)


def safe_md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ").strip()


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
    status: dict[str, Any] = {
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
                blockers.append("secure env file is readable by group/others; chmod 600 before using it")
            file_values = parse_env_file(env_file)
            status["loaded_names"] = sorted(file_values)
        except Exception as exc:
            blockers.append(f"could not read secure env file: {exc}")
    elif explicit:
        blockers.append(f"explicit secure env file does not exist: {env_file}")
    else:
        blockers.append(f"secure env file is missing: {env_file}")

    merged = file_values.copy()
    merged.update(os.environ)
    return merged, status, warnings, blockers


def env_group_status(group: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    present_names = [name for name in group["names"] if bool(str(env.get(name, "")).strip())]
    return {
        "id": group["id"],
        "label": group["label"],
        "names": group["names"],
        "present": bool(present_names),
        "present_names": present_names,
        "note": group["note"],
    }


def password_file_status(env: dict[str, str]) -> tuple[dict[str, Any], list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    configured = str(env.get("RESTIC_PASSWORD_FILE", "")).strip()
    status: dict[str, Any] = {
        "configured": bool(configured),
        "path": configured or str(DEFAULT_PASSWORD_FILE),
        "present": None,
        "is_file": None,
        "mode": "",
        "mode_secure": None,
        "size_bytes": None,
        "nonempty": None,
    }
    if not configured:
        if env.get("RESTIC_PASSWORD"):
            warnings.append("RESTIC_PASSWORD is present; RESTIC_PASSWORD_FILE is safer for unattended jobs")
        return status, warnings, blockers

    path = Path(configured).expanduser()
    status["path"] = str(path)
    try:
        stat = path.stat()
    except FileNotFoundError:
        status["present"] = False
        blockers.append("RESTIC_PASSWORD_FILE is set but missing")
        return status, warnings, blockers
    except OSError as exc:
        blockers.append(f"could not stat RESTIC_PASSWORD_FILE: {exc}")
        return status, warnings, blockers

    mode = stat.st_mode & 0o777
    status.update(
        {
            "present": True,
            "is_file": path.is_file(),
            "mode": oct(mode),
            "mode_secure": (mode & 0o077) == 0,
            "size_bytes": stat.st_size,
            "nonempty": stat.st_size > 0,
        }
    )
    if not status["is_file"]:
        blockers.append("RESTIC_PASSWORD_FILE is not a regular file")
    if not status["nonempty"]:
        blockers.append("RESTIC_PASSWORD_FILE is empty")
    if not status["mode_secure"]:
        blockers.append("RESTIC_PASSWORD_FILE is readable by group/others; chmod 600 before using it")
    return status, warnings, blockers


def run(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except Exception as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


def tool_status() -> dict[str, Any]:
    rclone_remotes: list[str] = []
    rclone = shutil.which("rclone")
    if rclone:
        proc = run(["rclone", "listremotes"])
        if proc.returncode == 0:
            rclone_remotes = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return {
        "restic_installed": shutil.which("restic") is not None,
        "rclone_installed": rclone is not None,
        "rclone_remotes": rclone_remotes,
        "active_r2_remote": "r2:" in rclone_remotes,
    }


def render_env_example() -> str:
    return f"""# Copy to {DEFAULT_ENV_FILE} and chmod 600.
# Do not commit filled values and do not paste them into chat or vault notes.

# Option A: account id lets the runner derive https://<account>.r2.cloudflarestorage.com
R2_ACCOUNT_ID=
# Option B: set the endpoint directly instead of R2_ACCOUNT_ID
# R2_ENDPOINT=

R2_BUCKET=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=

# Preferred for unattended jobs.
RESTIC_PASSWORD_FILE={DEFAULT_PASSWORD_FILE}
# RESTIC_PASSWORD=

R2_RESTIC_PREFIX=nomarh-control-plane-restic
"""


def render_setup_commands(env_file: Path) -> str:
    return f"""# R2/restic secure setup commands

These commands intentionally contain placeholders. Fill values locally only.

```bash
install -d -m 700 {env_file.parent}
install -m 600 {ENV_EXAMPLE_PATH} {env_file}
${{EDITOR:-nano}} {env_file}
```

Create the restic password file without leaving the password in shell history:

```bash
install -d -m 700 {DEFAULT_PASSWORD_FILE.parent}
read -rsp 'Restic repository password: ' RESTIC_PASSWORD_VALUE; printf '\\n'
umask 077
printf '%s\\n' \"$RESTIC_PASSWORD_VALUE\" > {DEFAULT_PASSWORD_FILE}
unset RESTIC_PASSWORD_VALUE
chmod 600 {DEFAULT_PASSWORD_FILE}
```

Configure the rclone remote named `r2:` using the same scoped R2 key:

```bash
rclone config
rclone listremotes
```

Then verify:

```bash
control-plane-r2-restic-intake --json
control-plane-r2-restic-bootstrap --json
control-plane-restic-backup --init --dry-run
```
"""


def build_payload(env_file: Path, *, explicit_env_file: bool) -> dict[str, Any]:
    env, env_file_status, env_warnings, env_blockers = load_env(env_file, explicit=explicit_env_file)
    groups = [env_group_status(group, env) for group in REQUIRED_GROUPS]
    password_status, password_warnings, password_blockers = password_file_status(env)
    tools = tool_status()

    blockers = env_blockers[:]
    warnings = env_warnings[:]
    blockers.extend(password_blockers)
    warnings.extend(password_warnings)

    for group in groups:
        if not group["present"]:
            blockers.append(f"missing secure input group: {group['label']} ({' or '.join(group['names'])})")
    if not tools["restic_installed"]:
        blockers.append("restic is not installed")
    if not tools["rclone_installed"]:
        blockers.append("rclone is not installed")
    if not tools["active_r2_remote"]:
        blockers.append("active rclone remote r2: is not configured")

    if not env.get("R2_RESTIC_PREFIX"):
        warnings.append("R2_RESTIC_PREFIX is not set; backup runner defaults to nomarh-control-plane-restic")

    result = "blocked" if blockers else "ready"
    next_action = (
        "Fill the secure env file, create the restic password file, and configure rclone remote `r2:`."
        if blockers
        else "Run `control-plane-r2-restic-bootstrap --json`, then `control-plane-restic-backup --init --dry-run`."
    )
    return {
        "schema": "control-plane-r2-restic-intake.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "summary": {
            "required_input_groups": len(REQUIRED_GROUPS),
            "present_required_input_groups": sum(1 for group in groups if group["present"]),
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
        },
        "env_file": env_file_status,
        "password_file": password_status,
        "input_groups": groups,
        "tools": tools,
        "blockers": blockers,
        "warnings": warnings,
        "next_action": next_action,
        "verify_sequence": [
            "control-plane-r2-restic-intake --json",
            "control-plane-r2-restic-bootstrap --json",
            "control-plane-restic-backup --init --dry-run",
            "control-plane-restic-backup --json",
            "control-plane-restic-restore-drill --json",
        ],
        "paths": {
            "status": str(STATUS_PATH),
            "report": str(REPORT_PATH),
            "env_example": str(ENV_EXAMPLE_PATH),
            "setup_commands": str(COMMANDS_PATH),
            "secure_env_file": str(env_file),
            "default_password_file": str(DEFAULT_PASSWORD_FILE),
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Control Plane R2/restic Intake",
        "",
        "No secret values are printed. This status only reports whether local secure input groups exist.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Required input groups present: {payload['summary']['present_required_input_groups']}/{payload['summary']['required_input_groups']}",
        f"- Blockers: {payload['summary']['blocker_count']}",
        f"- Warnings: {payload['summary']['warning_count']}",
        f"- Secure env file: `{safe_md(payload['env_file']['path'])}`",
        f"- Env file present: `{payload['env_file']['present']}`",
        f"- Env file mode secure: `{payload['env_file']['mode_secure']}`",
        f"- Password file configured: `{payload['password_file']['configured']}`",
        f"- Password file present: `{payload['password_file']['present']}`",
        f"- Password file nonempty: `{payload['password_file']['nonempty']}`",
        f"- Password file mode secure: `{payload['password_file']['mode_secure']}`",
        "",
        "## Inputs",
        "",
        "| Input | Present | Accepted names | Note |",
        "|---|---|---|---|",
    ]
    for group in payload["input_groups"]:
        lines.append(
            f"| {safe_md(group['label'])} | `{group['present']}` | `{safe_md(', '.join(group['names']))}` | {safe_md(group['note'])} |"
        )
    lines.extend(
        [
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
    lines.extend(["## Verify Sequence", ""])
    lines.extend(f"{idx}. `{safe_md(command)}`" for idx, command in enumerate(payload["verify_sequence"], start=1))
    lines.extend(["", "## Next Action", "", safe_md(payload["next_action"]), ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="No-secret R2/restic secure input intake checker")
    parser.add_argument("--env-file", help="optional secure env file; defaults to ~/.config/nomarh/control-plane-restic.env")
    parser.add_argument("--json", action="store_true", help="print JSON status")
    args = parser.parse_args()

    env_file = Path(args.env_file).expanduser() if args.env_file else default_env_file()
    write_text_atomic(ENV_EXAMPLE_PATH, render_env_example(), mode=0o600)
    write_text_atomic(COMMANDS_PATH, render_setup_commands(env_file), mode=0o600)
    payload = build_payload(env_file, explicit_env_file=args.env_file is not None)
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload), mode=0o600)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Control-plane R2/restic intake")
        print(f"Result: {payload['result']}")
        print(
            f"Required input groups: {payload['summary']['present_required_input_groups']}/{payload['summary']['required_input_groups']}"
        )
        print(f"Status: {STATUS_PATH}")
        print(f"Report: {REPORT_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import json
import os
import shutil
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

HOME = Path.home()
STATE_DIR = HOME / ".local/state/control-plane-r2-remote-config"
STATUS_PATH = STATE_DIR / "status.json"
REPORT_PATH = STATE_DIR / "remote-config.md"
DEFAULT_ENV_FILE = HOME / ".config/nomarh/control-plane-restic.env"
DEFAULT_RCLONE_CONFIG = HOME / ".config/rclone/rclone.conf"
APPLY_GUARD = "NOMARH_R2_REMOTE_CONFIG_APPLY"


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


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if not text.endswith("\n"):
        text += "\n"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


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


def run(args: list[str], *, input_text: str | None = None, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except Exception as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


def rclone_config_path() -> Path:
    if not shutil.which("rclone"):
        return DEFAULT_RCLONE_CONFIG
    proc = run(["rclone", "config", "file"], timeout=10)
    for line in proc.stdout.splitlines():
        text = line.strip()
        if text.startswith("/"):
            return Path(text).expanduser()
    return DEFAULT_RCLONE_CONFIG


def list_rclone_remotes() -> list[str]:
    if not shutil.which("rclone"):
        return []
    proc = run(["rclone", "listremotes"], timeout=10)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def derive_endpoint(env: dict[str, str]) -> str:
    endpoint = str(env.get("R2_ENDPOINT", "")).strip()
    account = str(env.get("R2_ACCOUNT_ID", "")).strip()
    if not endpoint and account:
        endpoint = f"https://{account}.r2.cloudflarestorage.com"
    return endpoint.rstrip("/")


def masked_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        return "invalid-endpoint"
    parts = parsed.netloc.split(".")
    if len(parts) >= 4 and parts[1:4] == ["r2", "cloudflarestorage", "com"]:
        return f"{parsed.scheme}://<account>.r2.cloudflarestorage.com"
    return f"{parsed.scheme}://{parsed.netloc}"


def endpoint_is_valid(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def obscure_secret(secret: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if not shutil.which("rclone"):
        return "", ["rclone is not installed; cannot obscure secret"]
    proc = run(["rclone", "obscure", "-"], input_text=secret + "\n", timeout=10)
    if proc.returncode != 0:
        warnings.append("rclone obscure failed")
        return "", warnings
    value = proc.stdout.strip().splitlines()[-1].strip() if proc.stdout.strip() else ""
    if not value:
        warnings.append("rclone obscure returned no value")
    return value, warnings


def read_config(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    if path.exists():
        parser.read(path)
    return parser


def write_remote_config(path: Path, env: dict[str, str], endpoint: str, *, force: bool) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    path.parent.mkdir(parents=True, exist_ok=True)
    config = read_config(path)
    if config.has_section("r2") and not force:
        return False, ["r2 section already exists; no change without --force"]

    secret_key = str(env.get("R2_SECRET_ACCESS_KEY") or env.get("AWS_SECRET_ACCESS_KEY") or "").strip()
    obscured_secret, obscure_warnings = obscure_secret(secret_key)
    warnings.extend(obscure_warnings)
    if not obscured_secret:
        return False, warnings

    if not config.has_section("r2"):
        config.add_section("r2")
    config.set("r2", "type", "s3")
    config.set("r2", "provider", "Cloudflare")
    config.set("r2", "access_key_id", str(env.get("R2_ACCESS_KEY_ID") or env.get("AWS_ACCESS_KEY_ID") or "").strip())
    config.set("r2", "secret_access_key", obscured_secret)
    config.set("r2", "endpoint", endpoint)
    config.set("r2", "acl", "private")

    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        config.write(handle)
    tmp.chmod(0o600)
    tmp.replace(path)
    path.chmod(0o600)
    return True, warnings


def build_payload(env_file: Path, *, explicit_env_file: bool, apply: bool, force: bool) -> dict[str, Any]:
    env, env_status, env_warnings, env_blockers = load_env(env_file, explicit=explicit_env_file)
    blockers: list[str] = env_blockers[:]
    warnings: list[str] = env_warnings[:]
    actions: list[str] = []
    command_results: list[dict[str, Any]] = []

    endpoint = derive_endpoint(env)
    access_key_present = bool(str(env.get("R2_ACCESS_KEY_ID") or env.get("AWS_ACCESS_KEY_ID") or "").strip())
    secret_key_present = bool(str(env.get("R2_SECRET_ACCESS_KEY") or env.get("AWS_SECRET_ACCESS_KEY") or "").strip())
    bucket_present = bool(str(env.get("R2_BUCKET", "")).strip())
    password_present = bool(str(env.get("RESTIC_PASSWORD") or env.get("RESTIC_PASSWORD_FILE") or "").strip())
    if not shutil.which("rclone"):
        blockers.append("rclone is not installed")
    if not endpoint:
        blockers.append("missing R2 endpoint: set R2_ENDPOINT or R2_ACCOUNT_ID")
    elif not endpoint_is_valid(endpoint):
        blockers.append("R2 endpoint is not a valid http/https URL")
    if not access_key_present:
        blockers.append("missing R2 access key: set R2_ACCESS_KEY_ID or AWS_ACCESS_KEY_ID")
    if not secret_key_present:
        blockers.append("missing R2 secret key: set R2_SECRET_ACCESS_KEY or AWS_SECRET_ACCESS_KEY")
    if not bucket_present:
        warnings.append("R2_BUCKET is missing; remote config can be prepared, but backup will still be blocked")
    if not password_present:
        warnings.append("RESTIC_PASSWORD_FILE or RESTIC_PASSWORD is missing; remote config can be prepared, but backup will still be blocked")

    config_path = rclone_config_path()
    remotes_before = list_rclone_remotes()
    active_before = "r2:" in remotes_before
    planned_change = "none" if active_before else "create-r2-remote"
    applied = False

    if apply and blockers:
        actions.append("apply skipped because blockers are present")
    elif apply and os.environ.get(APPLY_GUARD) != "reviewed":
        blockers.append(f"apply guard missing: set {APPLY_GUARD}=reviewed")
        actions.append("apply skipped because guard is missing")
    elif apply and active_before and not force:
        actions.append("r2 remote already exists; no change")
    elif apply:
        changed, apply_warnings = write_remote_config(config_path, env, endpoint, force=force)
        warnings.extend(apply_warnings)
        applied = changed
        actions.append("r2 remote config written" if changed else "r2 remote config not changed")

    remotes_after = list_rclone_remotes()
    active_after = "r2:" in remotes_after
    if apply:
        command_results.append(
            {
                "command": "write rclone config section [r2]",
                "changed": applied,
                "active_r2_after": active_after,
            }
        )
        if not active_after and not blockers:
            blockers.append("r2 remote was not visible after apply")

    if blockers:
        result = "blocked"
        next_action = "Fill the secure env file, then rerun `control-plane-r2-remote-config --json`."
    elif active_after:
        result = "ready"
        next_action = "Run `control-plane-r2-restic-intake --json`, then backup dry-run."
    else:
        result = "ready-to-apply"
        next_action = f"Run `{APPLY_GUARD}=reviewed control-plane-r2-remote-config --apply --json` after reviewing the plan."

    return {
        "schema": "control-plane-r2-remote-config.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "mode": "apply" if apply else "dry-run",
        "summary": {
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
            "rclone_installed": shutil.which("rclone") is not None,
            "active_r2_before": active_before,
            "active_r2_after": active_after,
            "access_key_present": access_key_present,
            "secret_key_present": secret_key_present,
            "bucket_present": bucket_present,
            "password_present": password_present,
            "applied": applied,
        },
        "env_file": env_status,
        "rclone": {
            "config_path": str(config_path),
            "config_present": config_path.exists(),
            "remotes_before": remotes_before,
            "remotes_after": remotes_after,
            "planned_change": planned_change,
        },
        "inputs": {
            "endpoint_present": bool(endpoint),
            "endpoint_label": masked_endpoint(endpoint) if endpoint else "",
            "access_key_present": access_key_present,
            "secret_key_present": secret_key_present,
            "bucket_present": bucket_present,
            "password_present": password_present,
        },
        "blockers": blockers,
        "warnings": warnings,
        "actions": actions,
        "command_results": command_results,
        "next_action": next_action,
        "verify_sequence": [
            "control-plane-r2-remote-config --json",
            f"{APPLY_GUARD}=reviewed control-plane-r2-remote-config --apply --json",
            "control-plane-r2-restic-intake --json",
            "control-plane-r2-restic-bootstrap --json",
            "control-plane-restic-backup --init --dry-run",
        ],
        "paths": {
            "status": str(STATUS_PATH),
            "report": str(REPORT_PATH),
            "env_file": str(env_file),
            "rclone_config": str(config_path),
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    rclone = payload["rclone"]
    lines = [
        "# Control Plane R2 Remote Config",
        "",
        "No secret values are printed. Dry-run mode validates whether a real `r2:` remote can be configured from the secure env file. Apply mode requires an explicit guard.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Mode: `{payload['mode']}`",
        f"- Blockers: `{summary['blocker_count']}`",
        f"- Warnings: `{summary['warning_count']}`",
        f"- rclone installed: `{summary['rclone_installed']}`",
        f"- active `r2:` before: `{summary['active_r2_before']}`",
        f"- active `r2:` after: `{summary['active_r2_after']}`",
        f"- planned change: `{safe_md(rclone['planned_change'])}`",
        f"- env file: `{safe_md(payload['env_file']['path'])}`",
        f"- rclone config: `{safe_md(rclone['config_path'])}`",
        "",
        "## Inputs",
        "",
        f"- Endpoint present: `{payload['inputs']['endpoint_present']}` (`{safe_md(payload['inputs']['endpoint_label'])}`)",
        f"- Access key present: `{payload['inputs']['access_key_present']}`",
        f"- Secret key present: `{payload['inputs']['secret_key_present']}`",
        f"- Bucket present: `{payload['inputs']['bucket_present']}`",
        f"- Restic password present: `{payload['inputs']['password_present']}`",
        "",
        "## Remotes",
        "",
        f"- Before: `{safe_md(', '.join(rclone['remotes_before']) or 'none')}`",
        f"- After: `{safe_md(', '.join(rclone['remotes_after']) or 'none')}`",
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
    if payload["actions"]:
        lines.extend(["## Actions", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["actions"])
        lines.append("")
    lines.extend(["## Verify Sequence", ""])
    lines.extend(f"{idx}. `{safe_md(command)}`" for idx, command in enumerate(payload["verify_sequence"], start=1))
    lines.extend(["", "## Next Action", "", safe_md(payload["next_action"]), "", "## Source Paths", ""])
    for key, path in payload["paths"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate or configure the rclone remote named r2 from the secure R2/restic env file")
    parser.add_argument("--env-file", help="optional secure env file; defaults to ~/.config/nomarh/control-plane-restic.env")
    parser.add_argument("--apply", action="store_true", help="write the r2 remote after validation and guard confirmation")
    parser.add_argument("--force", action="store_true", help="overwrite existing [r2] config section when applying")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    env_file = Path(args.env_file).expanduser() if args.env_file else default_env_file()
    payload = build_payload(env_file, explicit_env_file=args.env_file is not None, apply=args.apply, force=args.force)
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Control-plane R2 remote config")
        print(f"Result: {payload['result']}")
        print(f"Mode: {payload['mode']}")
        print(f"Status: {STATUS_PATH}")
        print(f"Report: {REPORT_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

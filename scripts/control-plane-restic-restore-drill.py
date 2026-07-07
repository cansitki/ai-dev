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
from urllib.parse import urlparse

HOME = Path.home()
STATE_DIR = HOME / ".local/state/control-plane-restic-restore-drill"
STATUS_PATH = STATE_DIR / "status.json"
REPORT_PATH = STATE_DIR / "report.md"
DEFAULT_ENV_FILE = HOME / ".config/nomarh/control-plane-restic.env"
DEFAULT_TARGET = STATE_DIR / "last-restore"
DEFAULT_INCLUDES = [
    "/home/coder/.local/state/can-doctor/status.json",
    "/home/coder/.local/state/nomarh-migration-readiness/readiness.json",
    "/home/coder/Can/Vault Index.md",
]


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_env_file() -> Path:
    configured = os.environ.get("CONTROL_PLANE_RESTIC_ENV_FILE") or os.environ.get("NOMARH_RESTIC_ENV_FILE")
    return Path(configured).expanduser() if configured else DEFAULT_ENV_FILE


def masked_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if not parsed.netloc:
        return "invalid-endpoint"
    parts = parsed.netloc.split(".")
    if len(parts) >= 4 and parts[1:4] == ["r2", "cloudflarestorage", "com"]:
        return f"{parsed.scheme}://<account>.r2.cloudflarestorage.com"
    return f"{parsed.scheme}://{parsed.netloc}"


def build_repo_label(endpoint: str, bucket: str, prefix: str) -> str:
    return f"s3:{masked_endpoint(endpoint)}/{bucket}/{prefix}".rstrip("/")


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


def build_env(base_env: dict[str, str]) -> tuple[dict[str, str], list[str], dict[str, str], list[str]]:
    env = base_env.copy()
    missing: list[str] = []
    redactions: list[str] = []

    endpoint = env.get("R2_ENDPOINT", "").strip()
    account_id = env.get("R2_ACCOUNT_ID", "").strip()
    if not endpoint and account_id:
        endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    if not endpoint:
        missing.append("R2_ENDPOINT or R2_ACCOUNT_ID")
    else:
        redactions.append(endpoint)
    if account_id:
        redactions.append(account_id)

    bucket = env.get("R2_BUCKET", "").strip()
    if not bucket:
        missing.append("R2_BUCKET")

    prefix = env.get("R2_RESTIC_PREFIX", "nomarh-control-plane-restic").strip().strip("/")
    if not prefix:
        missing.append("R2_RESTIC_PREFIX")

    access_key = env.get("AWS_ACCESS_KEY_ID") or env.get("R2_ACCESS_KEY_ID")
    secret_key = env.get("AWS_SECRET_ACCESS_KEY") or env.get("R2_SECRET_ACCESS_KEY")
    if not access_key:
        missing.append("R2_ACCESS_KEY_ID or AWS_ACCESS_KEY_ID")
    else:
        env["AWS_ACCESS_KEY_ID"] = access_key
        redactions.append(access_key)
    if not secret_key:
        missing.append("R2_SECRET_ACCESS_KEY or AWS_SECRET_ACCESS_KEY")
    else:
        env["AWS_SECRET_ACCESS_KEY"] = secret_key
        redactions.append(secret_key)

    password = env.get("RESTIC_PASSWORD")
    password_file = env.get("RESTIC_PASSWORD_FILE")
    if not password and not password_file:
        missing.append("RESTIC_PASSWORD or RESTIC_PASSWORD_FILE")
    if password:
        redactions.append(password)

    if endpoint and bucket and prefix:
        env["RESTIC_REPOSITORY"] = f"s3:{endpoint.rstrip('/')}/{bucket.strip('/')}/{prefix}"
        redactions.append(env["RESTIC_REPOSITORY"])

    public_config = {
        "endpoint": masked_endpoint(endpoint) if endpoint else "",
        "bucket": bucket,
        "prefix": prefix,
        "repository_label": build_repo_label(endpoint, bucket, prefix) if endpoint and bucket and prefix else "",
    }
    return env, missing, public_config, [item for item in redactions if item]


def validate_restic_password_file(env: dict[str, str]) -> tuple[dict[str, Any], list[str], list[str]]:
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


def sanitize(text: str, redactions: list[str]) -> str:
    result = text
    for item in redactions:
        if item:
            result = result.replace(item, "<redacted>")
    return result


def run(args: list[str], *, env: dict[str, str], timeout: int, redactions: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=timeout)
        return subprocess.CompletedProcess(proc.args, proc.returncode, sanitize(proc.stdout, redactions), sanitize(proc.stderr, redactions))
    except Exception as exc:
        return subprocess.CompletedProcess(args, 1, "", sanitize(str(exc), redactions))


def safe_restore_target(target: Path) -> Path:
    resolved = target.expanduser().resolve()
    state = STATE_DIR.resolve()
    if resolved == state or state not in resolved.parents:
        raise ValueError(f"restore target must be inside {STATE_DIR}")
    return resolved


def clean_target(target: Path) -> Path:
    resolved = safe_restore_target(target)
    tmp = resolved.with_name(resolved.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, mode=0o700)
    return tmp


def restored_path(target: Path, include: str) -> Path:
    return target / include.lstrip("/")


def snapshots_summary(stdout: str) -> dict[str, Any]:
    try:
        snapshots = json.loads(stdout)
    except Exception:
        return {"valid": False, "count": 0}
    if not isinstance(snapshots, list):
        return {"valid": False, "count": 0}
    latest = snapshots[-1] if snapshots else {}
    return {
        "valid": True,
        "count": len(snapshots),
        "latest_id": latest.get("short_id") or latest.get("id", "")[:12] if isinstance(latest, dict) else "",
        "latest_time": latest.get("time", "") if isinstance(latest, dict) else "",
        "latest_tags": latest.get("tags", []) if isinstance(latest, dict) else [],
    }


def build_status(
    *,
    result: str,
    blockers: list[str],
    warnings: list[str],
    repository: dict[str, str],
    env_file_status: dict[str, Any],
    password_file_status: dict[str, Any],
    target: Path,
    includes: list[str],
    command_results: list[dict[str, Any]],
    restored_markers: list[str],
) -> dict[str, Any]:
    return {
        "schema": "control-plane-restic-restore-drill.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "blockers": blockers,
        "warnings": warnings,
        "repository": repository,
        "env_file": env_file_status,
        "password_file": password_file_status,
        "target": str(target),
        "includes": includes,
        "restored_markers": restored_markers,
        "command_results": command_results,
        "paths": {"status": str(STATUS_PATH), "report": str(REPORT_PATH)},
    }


def safe_md(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(status: dict[str, Any]) -> str:
    lines = [
        "# Control Plane Restic Restore Drill",
        "",
        "No secrets, env files, private keys, tmux pane output, or mailbox contents are printed. Restored files stay under the local state directory.",
        "",
        f"- Updated: `{status['updated_at']}`",
        f"- Host: `{status['host']}`",
        f"- Result: `{status['result']}`",
        f"- Repository: `{safe_md(status['repository'].get('repository_label', ''))}`",
        f"- Env file: `{safe_md(status.get('env_file', {}).get('path', ''))}`",
        f"- Restic password file configured: `{status.get('password_file', {}).get('configured')}`",
        f"- Restic password file present: `{status.get('password_file', {}).get('present')}`",
        f"- Restic password file nonempty: `{status.get('password_file', {}).get('nonempty')}`",
        f"- Restic password file mode secure: `{status.get('password_file', {}).get('mode_secure')}`",
        f"- Target: `{safe_md(status['target'])}`",
        f"- Restored markers: {len(status['restored_markers'])}",
        "",
    ]
    if status["blockers"]:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {safe_md(item)}" for item in status["blockers"])
        lines.append("")
    if status["warnings"]:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {safe_md(item)}" for item in status["warnings"])
        lines.append("")
    lines.extend(["## Includes", ""])
    lines.extend(f"- `{safe_md(item)}`" for item in status["includes"])
    lines.extend(["", "## Commands", "", "| Command | Return Code | Detail |", "|---|---:|---|"])
    for item in status["command_results"]:
        detail = item.get("stderr_tail") or item.get("summary") or item.get("stdout_bytes", "")
        lines.append(f"| `{safe_md(item.get('command'))}` | {item.get('returncode')} | {safe_md(detail)} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a scoped control-plane restic restore drill")
    parser.add_argument("--env-file", help="optional secure env file; defaults to ~/.config/nomarh/control-plane-restic.env")
    parser.add_argument("--target", default=str(DEFAULT_TARGET), help="restore target inside ~/.local/state/control-plane-restic-restore-drill")
    parser.add_argument("--include", action="append", dest="includes", help="path include to restore; repeatable")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()

    blockers: list[str] = []
    warnings: list[str] = []
    command_results: list[dict[str, Any]] = []
    password_file_status: dict[str, Any] = {}
    includes = args.includes or DEFAULT_INCLUDES
    env_file = Path(args.env_file).expanduser() if args.env_file else default_env_file()
    base_env, env_file_status, env_warnings, env_blockers = load_env(env_file, explicit=args.env_file is not None)
    warnings.extend(env_warnings)
    blockers.extend(env_blockers)

    if shutil.which("restic") is None:
        blockers.append("restic is not installed")

    env, missing, repository, redactions = build_env(base_env)
    blockers.extend(f"missing env: {name}" for name in missing)
    password_file_status, password_file_warnings, password_file_blockers = validate_restic_password_file(env)
    warnings.extend(password_file_warnings)
    blockers.extend(password_file_blockers)

    try:
        target = safe_restore_target(Path(args.target))
    except ValueError as exc:
        target = DEFAULT_TARGET
        blockers.append(str(exc))

    if not blockers:
        snapshots = run(["restic", "snapshots", "--json"], env=env, timeout=args.timeout, redactions=redactions)
        command_results.append(
            {
                "command": "restic snapshots --json",
                "returncode": snapshots.returncode,
                "summary": snapshots_summary(snapshots.stdout),
                "stdout_bytes": len(snapshots.stdout),
                "stderr_tail": snapshots.stderr[-500:],
            }
        )
        if snapshots.returncode != 0:
            blockers.append("restic snapshots failed; repository is not reachable or credentials are invalid")
        elif snapshots_summary(snapshots.stdout).get("count", 0) == 0:
            blockers.append("restic repository has no snapshots to restore")

    restored_markers: list[str] = []
    if not blockers:
        tmp = clean_target(target)
        restore_cmd = ["restic", "restore", "latest", "--target", str(tmp)]
        for include in includes:
            restore_cmd.extend(["--include", include])
        restore = run(restore_cmd, env=env, timeout=args.timeout, redactions=redactions)
        command_results.append(
            {
                "command": "restic restore latest --target <state-dir> --include <markers>",
                "returncode": restore.returncode,
                "stdout_bytes": len(restore.stdout),
                "stderr_tail": restore.stderr[-500:],
            }
        )
        if restore.returncode != 0:
            blockers.append("restic restore failed")
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            for include in includes:
                marker = restored_path(tmp, include)
                if marker.exists():
                    restored_markers.append(include)
            if not restored_markers:
                blockers.append("restore completed but none of the expected marker paths were found")
                shutil.rmtree(tmp, ignore_errors=True)
            else:
                if target.exists():
                    shutil.rmtree(target)
                tmp.replace(target)
                target.chmod(0o700)

    result = "blocked" if blockers else "success"
    status = build_status(
        result=result,
        blockers=blockers,
        warnings=warnings,
        repository=repository,
        env_file_status=env_file_status,
        password_file_status=password_file_status,
        target=target,
        includes=includes,
        command_results=command_results,
        restored_markers=restored_markers,
    )
    write_json_atomic(STATUS_PATH, status)
    write_text_atomic(REPORT_PATH, render_markdown(status))

    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print("Control-plane restic restore drill")
        print(f"Result: {result}")
        print(f"Blockers: {len(blockers)}")
        print(f"Status: {STATUS_PATH}")
        print(f"Report: {REPORT_PATH}")
    return 2 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())

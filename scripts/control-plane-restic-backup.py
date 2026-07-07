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
READINESS_STATUS = HOME / ".local/state/control-plane-backup-readiness/status.json"
STATE_DIR = HOME / ".local/state/control-plane-restic-backup"
STATUS_PATH = STATE_DIR / "status.json"
DEFAULT_ENV_FILE = HOME / ".config/nomarh/control-plane-restic.env"


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


def default_env_file() -> Path:
    configured = os.environ.get("CONTROL_PLANE_RESTIC_ENV_FILE") or os.environ.get("NOMARH_RESTIC_ENV_FILE")
    return Path(configured).expanduser() if configured else DEFAULT_ENV_FILE


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


def run(args: list[str], *, env: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=timeout,
        )
    except Exception as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


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


def build_env(base_env: dict[str, str]) -> tuple[dict[str, str], list[str], dict[str, str]]:
    env = base_env.copy()
    missing: list[str] = []

    endpoint = env.get("R2_ENDPOINT", "").strip()
    account_id = env.get("R2_ACCOUNT_ID", "").strip()
    if not endpoint and account_id:
        endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    if not endpoint:
        missing.append("R2_ENDPOINT or R2_ACCOUNT_ID")

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
    if not secret_key:
        missing.append("R2_SECRET_ACCESS_KEY or AWS_SECRET_ACCESS_KEY")

    password = env.get("RESTIC_PASSWORD")
    password_file = env.get("RESTIC_PASSWORD_FILE")
    if not password and not password_file:
        missing.append("RESTIC_PASSWORD or RESTIC_PASSWORD_FILE")

    if access_key:
        env["AWS_ACCESS_KEY_ID"] = access_key
    if secret_key:
        env["AWS_SECRET_ACCESS_KEY"] = secret_key
    if endpoint and bucket and prefix:
        env["RESTIC_REPOSITORY"] = f"s3:{endpoint.rstrip('/')}/{bucket.strip('/')}/{prefix}"

    public_config = {
        "endpoint": masked_endpoint(endpoint) if endpoint else "",
        "bucket": bucket,
        "prefix": prefix,
        "repository_label": build_repo_label(endpoint, bucket, prefix) if endpoint and bucket and prefix else "",
    }
    return env, missing, public_config


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


def readiness_surfaces() -> tuple[list[str], list[str]]:
    status = read_json(READINESS_STATUS)
    if not isinstance(status, dict):
        return [], [f"readiness status missing or invalid: {READINESS_STATUS}"]

    surfaces = []
    warnings = []
    for surface in status.get("surfaces", []):
        if not isinstance(surface, dict) or not surface.get("exists"):
            continue
        path = surface.get("path")
        if not path:
            continue
        surfaces.append(path)
        if surface.get("secret_bearing"):
            warnings.append(f"secret-bearing surface included only inside encrypted restic backup: {path}")
    return surfaces, warnings


def restic_json_tail(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            return item
    return None


def build_status(
    *,
    result: str,
    public_config: dict[str, str],
    env_file_status: dict[str, Any],
    password_file_status: dict[str, Any],
    blockers: list[str],
    warnings: list[str],
    dry_run: bool,
    command_results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": "control-plane-restic-backup.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "dry_run": dry_run,
        "repository": public_config,
        "env_file": env_file_status,
        "password_file": password_file_status,
        "blockers": blockers,
        "warnings": warnings,
        "command_results": command_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run scoped encrypted control-plane restic backup to Cloudflare R2")
    parser.add_argument("--env-file", help="optional secure env file; defaults to ~/.config/nomarh/control-plane-restic.env")
    parser.add_argument("--init", action="store_true", help="initialize the restic repository if snapshots fails")
    parser.add_argument("--dry-run", action="store_true", help="ask restic to simulate the backup without uploading data")
    parser.add_argument("--json", action="store_true", help="print JSON status")
    parser.add_argument("--timeout", type=int, default=3600, help="timeout in seconds for restic commands")
    args = parser.parse_args()

    blockers: list[str] = []
    warnings: list[str] = []
    command_results: list[dict[str, Any]] = []
    public_config: dict[str, str] = {}
    password_file_status: dict[str, Any] = {}
    env_file = Path(args.env_file).expanduser() if args.env_file else default_env_file()
    base_env, env_file_status, env_warnings, env_blockers = load_env(env_file, explicit=args.env_file is not None)
    warnings.extend(env_warnings)
    blockers.extend(env_blockers)

    if shutil.which("restic") is None:
        blockers.append("restic is not installed")

    env, missing, public_config = build_env(base_env)
    blockers.extend(f"missing env: {name}" for name in missing)
    password_file_status, password_file_warnings, password_file_blockers = validate_restic_password_file(env)
    warnings.extend(password_file_warnings)
    blockers.extend(password_file_blockers)

    surfaces, surface_warnings = readiness_surfaces()
    warnings.extend(surface_warnings)
    if not surfaces:
        blockers.append("no backup surfaces found; run control-plane-backup-readiness first")

    if blockers:
        status = build_status(
            result="blocked",
            public_config=public_config,
            env_file_status=env_file_status,
            password_file_status=password_file_status,
            blockers=blockers,
            warnings=warnings,
            dry_run=args.dry_run,
            command_results=command_results,
        )
        write_json_atomic(STATUS_PATH, status)
        if args.json:
            print(json.dumps(status, indent=2, sort_keys=True))
        else:
            print("Control-plane restic backup")
            print("Result: blocked")
            print(f"Blockers: {len(blockers)}")
            print(f"Status: {STATUS_PATH}")
        return 2

    snapshots = run(["restic", "snapshots", "--json"], env=env, timeout=args.timeout)
    command_results.append(
        {
            "command": "restic snapshots --json",
            "returncode": snapshots.returncode,
            "stdout_bytes": len(snapshots.stdout),
            "stderr_tail": snapshots.stderr[-500:],
        }
    )

    if snapshots.returncode != 0:
        if not args.init:
            blockers.append("restic repository is not initialized or not reachable; rerun with --init after verifying credentials")
        else:
            init = run(["restic", "init"], env=env, timeout=args.timeout)
            command_results.append(
                {
                    "command": "restic init",
                    "returncode": init.returncode,
                    "stdout_bytes": len(init.stdout),
                    "stderr_tail": init.stderr[-500:],
                }
            )
            if init.returncode != 0:
                blockers.append("restic init failed")

    if not blockers:
        backup_cmd = [
            "restic",
            "backup",
            "--host",
            socket.gethostname(),
            "--tag",
            "nomarh-control-plane",
            "--tag",
            "migration-gate",
            "--json",
        ]
        if args.dry_run:
            backup_cmd.append("--dry-run")
        backup_cmd.extend(surfaces)
        backup = run(backup_cmd, env=env, timeout=args.timeout)
        command_results.append(
            {
                "command": f"restic backup {'--dry-run ' if args.dry_run else ''}<surfaces>",
                "returncode": backup.returncode,
                "summary": restic_json_tail(backup.stdout),
                "stdout_bytes": len(backup.stdout),
                "stderr_tail": backup.stderr[-500:],
                "surface_count": len(surfaces),
            }
        )
        if backup.returncode != 0:
            blockers.append("restic backup failed")

    result = "blocked" if blockers else "dry-run-ok" if args.dry_run else "success"
    status = build_status(
        result=result,
        public_config=public_config,
        env_file_status=env_file_status,
        password_file_status=password_file_status,
        blockers=blockers,
        warnings=warnings,
        dry_run=args.dry_run,
        command_results=command_results,
    )
    write_json_atomic(STATUS_PATH, status)

    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print("Control-plane restic backup")
        print(f"Result: {result}")
        print(f"Blockers: {len(blockers)}")
        print(f"Warnings: {len(warnings)}")
        print(f"Status: {STATUS_PATH}")

    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())

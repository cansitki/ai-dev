#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/hetzner-access-preflight"
STATUS_PATH = STATE_DIR / "status.json"
REPORT_PATH = STATE_DIR / "report.md"
DEFAULT_TARGET = os.environ.get("HETZNER_SSH_TARGET", "root@195.201.194.181")
DEFAULT_KEY = Path(os.environ.get("HETZNER_SSH_KEY") or HOME / ".ssh/nomarh_hetzner")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def run(args: list[str], timeout: int = 8) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except Exception as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


def split_target(target: str) -> tuple[str, str]:
    if "@" in target:
        user, host = target.rsplit("@", 1)
    else:
        user, host = "", target
    return user, host


def tcp_check(host: str, port: int = 22, timeout: float = 5.0) -> dict[str, Any]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"reachable": True, "error": ""}
    except Exception as exc:
        return {"reachable": False, "error": str(exc)}


def key_info(key_path: Path) -> dict[str, Any]:
    pub_path = Path(str(key_path) + ".pub")
    info: dict[str, Any] = {
        "private_key_path": str(key_path),
        "private_key_exists": key_path.exists(),
        "private_key_mode": "",
        "public_key_path": str(pub_path),
        "public_key_exists": pub_path.exists(),
        "public_key_fingerprint": "",
        "public_key_type": "",
    }
    if key_path.exists():
        info["private_key_mode"] = oct(key_path.stat().st_mode & 0o777)
    if pub_path.exists():
        fp = run(["ssh-keygen", "-lf", str(pub_path)], timeout=5)
        if fp.returncode == 0 and fp.stdout.strip():
            parts = fp.stdout.strip().split()
            if len(parts) >= 2:
                info["public_key_fingerprint"] = parts[1]
            if len(parts) >= 4:
                info["public_key_type"] = parts[3].strip("()")
    return info


def auth_check(target: str, key_path: Path | None) -> dict[str, Any]:
    args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=6",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if key_path is not None:
        args.extend(["-i", str(key_path)])
    args.extend([target, "true"])
    proc = run(args, timeout=12)
    text = f"{proc.stdout}\n{proc.stderr}".strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    reason = lines[-1] if lines else ""
    return {
        "returncode": proc.returncode,
        "ok": proc.returncode == 0,
        "reason": reason[-300:],
    }


def agent_fingerprints() -> list[str]:
    proc = run(["ssh-add", "-l"], timeout=5)
    if proc.returncode != 0:
        return []
    fingerprints = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            fingerprints.append(parts[1])
    return fingerprints


def build_payload(target: str, key_path: Path) -> dict[str, Any]:
    user, host = split_target(target)
    blockers: list[str] = []
    warnings: list[str] = []
    key = key_info(key_path)
    tcp = tcp_check(host)
    explicit_auth = auth_check(target, key_path if key_path.exists() else None)
    default_auth = auth_check(target, None)
    agent = agent_fingerprints()

    if not user:
        blockers.append("target has no SSH user")
    if not tcp["reachable"]:
        blockers.append(f"tcp/22 not reachable: {tcp['error']}")
    if not key["private_key_exists"]:
        blockers.append(f"private key missing: {key_path}")
    if not key["public_key_exists"]:
        warnings.append(f"public key missing: {key_path}.pub")
    if key["private_key_mode"] and key["private_key_mode"] != "0o600":
        warnings.append(f"private key mode is {key['private_key_mode']}; expected 0o600")
    if tcp["reachable"] and key["private_key_exists"] and not explicit_auth["ok"]:
        blockers.append("key-based SSH denied by server")

    result = "ready" if explicit_auth["ok"] else "blocked" if blockers else "warn"
    next_action = (
        "SSH login works; continue Hetzner hardening."
        if explicit_auth["ok"]
        else "Authorize the local public key on Hetzner for the intended user, then rerun this preflight."
    )

    return {
        "schema": "hetzner-access-preflight.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "target": {
            "raw": target,
            "user": user,
            "host": host,
            "port": 22,
        },
        "blockers": blockers,
        "warnings": warnings,
        "tcp": tcp,
        "key": key,
        "ssh_agent": {
            "loaded_fingerprints": agent,
            "local_key_loaded": bool(key.get("public_key_fingerprint") and key["public_key_fingerprint"] in agent),
        },
        "auth": {
            "explicit_key": explicit_auth,
            "default_identities": default_auth,
        },
        "next_action": next_action,
        "paths": {
            "status": str(STATUS_PATH),
            "report": str(REPORT_PATH),
        },
    }


def safe_md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(payload: dict[str, Any]) -> str:
    key = payload["key"]
    explicit = payload["auth"]["explicit_key"]
    lines = [
        "# Hetzner Access Preflight",
        "",
        "No private keys, token values, passwords, or public key bodies are printed.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Local host: `{payload['host']}`",
        f"- Target: `{payload['target']['raw']}`",
        f"- Result: `{payload['result']}`",
        f"- TCP/22 reachable: `{payload['tcp']['reachable']}`",
        f"- Explicit-key SSH ok: `{explicit['ok']}`",
        f"- Explicit-key reason: {safe_md(explicit['reason'])}",
        f"- Public key fingerprint: `{safe_md(key['public_key_fingerprint'])}`",
        f"- Public key type: `{safe_md(key['public_key_type'])}`",
        f"- Private key path: `{safe_md(key['private_key_path'])}`",
        f"- Public key path: `{safe_md(key['public_key_path'])}`",
        f"- Private key mode: `{safe_md(key['private_key_mode'])}`",
        f"- Local key loaded in ssh-agent: `{payload['ssh_agent']['local_key_loaded']}`",
        "",
    ]
    if payload["blockers"]:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {item}" for item in payload["blockers"])
        lines.append("")
    if payload["warnings"]:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {item}" for item in payload["warnings"])
        lines.append("")
    lines.extend(["## Next Action", "", payload["next_action"], ""])
    lines.extend(
        [
            "## Safe Commands",
            "",
            "Show the public key body locally when ready to paste into Hetzner console or `authorized_keys`:",
            "",
            f"```bash\ncat {key['public_key_path']}\n```",
            "",
            "Retest:",
            "",
            "```bash\nhetzner-access-preflight\n```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="No-secret SSH access preflight for Hetzner migration target")
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--key", default=str(DEFAULT_KEY))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_payload(args.target, Path(args.key).expanduser())
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Hetzner access preflight")
        print(f"Result: {payload['result']}")
        print(f"Target: {payload['target']['raw']}")
        print(f"TCP/22 reachable: {payload['tcp']['reachable']}")
        print(f"SSH ok: {payload['auth']['explicit_key']['ok']}")
        print(f"Status: {STATUS_PATH}")
        print(f"Report: {REPORT_PATH}")
    return 0 if payload["result"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/hetzner-hardening-preflight"
STATUS_PATH = STATE_DIR / "status.json"
REPORT_PATH = STATE_DIR / "report.md"
DEFAULT_TARGET = os.environ.get("HETZNER_SSH_TARGET", "root@195.201.194.181")
DEFAULT_KEY = Path(os.environ.get("HETZNER_SSH_KEY") or HOME / ".ssh/nomarh_hetzner")

EXPECTED_PUBLIC_PORTS = {22, 25, 80, 443, 465, 587, 993}
REVIEW_PORTS = {110, 143, 995}


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


def run(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except Exception as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


def ssh(target: str, key_path: Path, command: str, timeout: int = 25) -> subprocess.CompletedProcess[str]:
    args = [
        "ssh",
        "-i",
        str(key_path),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        target,
        "bash",
        "-lc",
        command,
    ]
    return run(args, timeout=timeout)


def remote_json(target: str, key_path: Path) -> tuple[dict[str, Any] | None, str]:
    remote_script = r'''
set +e
json_escape() { python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'; }
kv() { printf '"%s":%s' "$1" "$(printf '%s' "$2" | json_escape)"; }
hostname_v="$(hostname 2>/dev/null)"
date_v="$(date -Is 2>/dev/null)"
kernel_v="$(uname -srmo 2>/dev/null)"
os_v="$(. /etc/os-release 2>/dev/null; printf '%s' "${PRETTY_NAME:-unknown}")"
uptime_v="$(uptime -p 2>/dev/null)"
who_v="$(id -un 2>/dev/null)"
disk_v="$(df -P / 2>/dev/null | awk 'NR==2{print $2" "$3" "$4" "$5}')"
mem_v="$(free -m 2>/dev/null | awk '/^Mem:/{print $2" "$7}')"
sshd_v="$(sshd -T 2>/dev/null | awk '/^(port|permitrootlogin|passwordauthentication|pubkeyauthentication|kbdinteractiveauthentication|challengeresponseauthentication|authenticationmethods|allowusers|denyusers|x11forwarding|allowtcpforwarding|permituserenvironment) /{print}' | sort)"
ufw_v="$(if command -v ufw >/dev/null 2>&1; then ufw status verbose 2>/dev/null; else echo 'ufw: missing'; fi)"
services_v="$(for s in docker ufw unattended-upgrades fail2ban crowdsec; do printf '%s ' "$s"; systemctl is-active "$s" 2>/dev/null; done)"
enabled_v="$(for s in docker ufw unattended-upgrades fail2ban crowdsec; do printf '%s ' "$s"; systemctl is-enabled "$s" 2>/dev/null; done)"
packages_v="$(dpkg-query -W -f='${binary:Package} ${Status} ${Version}\n' ufw unattended-upgrades fail2ban crowdsec docker.io docker-ce 2>/dev/null)"
ports_v="$(ss -tulnH 2>/dev/null | awk '{print $1" "$5}' | sort -u)"
docker_v="$(if command -v docker >/dev/null 2>&1; then docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null; else echo 'docker: missing'; fi)"
mailcow_v="$(if [ -d /opt/mailcow-dockerized ]; then echo yes; else echo no; fi)"
users_v="$(getent passwd | awk -F: '$3>=1000 && $3<65534 {print $1":"$3":"$7}' | sort)"
sudo_v="$(getent group sudo 2>/dev/null)"
root_pass_v="$(passwd -S root 2>/dev/null | awk '{print $2}')"
root_auth_count_v="$(if [ -f /root/.ssh/authorized_keys ]; then wc -l < /root/.ssh/authorized_keys; else echo 0; fi)"
updates_v="$(if command -v apt-get >/dev/null 2>&1; then apt-get -s upgrade 2>/dev/null | awk '/^Inst /{c++} END{print c+0}'; else echo unknown; fi)"
printf '{'
kv hostname "$hostname_v"; printf ','
kv date "$date_v"; printf ','
kv kernel "$kernel_v"; printf ','
kv os "$os_v"; printf ','
kv uptime "$uptime_v"; printf ','
kv user "$who_v"; printf ','
kv disk_root "$disk_v"; printf ','
kv memory "$mem_v"; printf ','
kv sshd "$sshd_v"; printf ','
kv ufw "$ufw_v"; printf ','
kv services "$services_v"; printf ','
kv enabled "$enabled_v"; printf ','
kv packages "$packages_v"; printf ','
kv listening_ports "$ports_v"; printf ','
kv docker_ps "$docker_v"; printf ','
kv mailcow_dir "$mailcow_v"; printf ','
kv login_users "$users_v"; printf ','
kv sudo_group "$sudo_v"; printf ','
kv root_password_state "$root_pass_v"; printf ','
kv root_authorized_keys_count "$root_auth_count_v"; printf ','
kv apt_upgrade_count "$updates_v"
printf '}'
'''
    proc = ssh(target, key_path, remote_script, timeout=40)
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout or "ssh command failed")[-1000:]
    try:
        return json.loads(proc.stdout), ""
    except Exception as exc:
        return None, f"remote JSON parse failed: {exc}; stdout tail={proc.stdout[-500:]}"


def parse_key_values(lines: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in lines.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            result[parts[0]] = parts[1]
    return result


def parse_services(lines: str) -> dict[str, str]:
    return parse_key_values(lines)


def parse_ports(lines: str) -> list[dict[str, Any]]:
    ports = []
    seen: set[tuple[str, str, int]] = set()
    for line in lines.splitlines():
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        proto, address = parts
        match = re.search(r":(\d+)$", address)
        if not match:
            continue
        port = int(match.group(1))
        key = (proto, address, port)
        if key not in seen:
            seen.add(key)
            ports.append({"proto": proto, "address": address, "port": port})
    return sorted(ports, key=lambda item: (item["port"], item["proto"], item["address"]))


def is_loopback_address(address: str) -> bool:
    lowered = address.lower()
    host = lowered.rsplit(":", 1)[0]
    return (
        host.startswith("127.")
        or host.startswith("[::1]")
        or host in {"::1", "localhost"}
        or "%lo" in host
    )


def public_ports(ports: list[dict[str, Any]]) -> set[int]:
    return {item["port"] for item in ports if not is_loopback_address(str(item.get("address", "")))}


def docker_summary(text: str) -> dict[str, Any]:
    if "docker: missing" in text:
        return {"available": False, "container_count": 0, "containers": []}
    containers = []
    for line in text.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0].strip():
            continue
        containers.append(
            {
                "name": parts[0],
                "status": parts[1] if len(parts) > 1 else "",
                "ports": parts[2] if len(parts) > 2 else "",
            }
        )
    return {"available": True, "container_count": len(containers), "containers": containers[:80]}


def disk_summary(text: str) -> dict[str, Any]:
    parts = text.split()
    if len(parts) != 4:
        return {"valid": False}
    pct = int(parts[3].rstrip("%")) if parts[3].rstrip("%").isdigit() else None
    return {"valid": True, "total_kb": parts[0], "used_kb": parts[1], "available_kb": parts[2], "used_percent": pct}


def memory_summary(text: str) -> dict[str, Any]:
    parts = text.split()
    if len(parts) != 2:
        return {"valid": False}
    return {"valid": True, "total_mb": parts[0], "available_mb": parts[1]}


def build_payload(target: str, key_path: Path) -> dict[str, Any]:
    remote, error = remote_json(target, key_path)
    blockers: list[str] = []
    warnings: list[str] = []
    if remote is None:
        blockers.append(f"remote hardening probe failed: {error}")
        remote = {}

    sshd = parse_key_values(str(remote.get("sshd", "")))
    services = parse_services(str(remote.get("services", "")))
    enabled = parse_services(str(remote.get("enabled", "")))
    ports = parse_ports(str(remote.get("listening_ports", "")))
    docker = docker_summary(str(remote.get("docker_ps", "")))
    disk = disk_summary(str(remote.get("disk_root", "")))
    memory = memory_summary(str(remote.get("memory", "")))
    users = [line for line in str(remote.get("login_users", "")).splitlines() if line.strip()]
    sudo_group = str(remote.get("sudo_group", ""))
    apt_upgrade_count = str(remote.get("apt_upgrade_count", "unknown"))

    if remote:
        if sshd.get("passwordauthentication", "").lower() == "yes":
            warnings.append("SSH password authentication is enabled")
        if sshd.get("permitrootlogin", "").lower() not in {"prohibit-password", "without-password", "no"}:
            warnings.append(f"direct root SSH policy is {sshd.get('permitrootlogin', 'unknown')}")
        if not users:
            warnings.append("no non-root login users found")
        if "sudo:" not in sudo_group or sudo_group.rstrip().endswith(":"):
            warnings.append("sudo group has no listed non-root members")
        if "Status: active" not in str(remote.get("ufw", "")):
            warnings.append("UFW is not active")
        if services.get("docker") != "active":
            warnings.append("Docker service is not active")
        if services.get("unattended-upgrades") != "active":
            warnings.append("unattended-upgrades service is not active")
        if services.get("fail2ban") != "active" and services.get("crowdsec") != "active":
            warnings.append("no active fail2ban or crowdsec service detected")
        if disk.get("used_percent") is not None and int(disk["used_percent"]) >= 85:
            warnings.append(f"root disk usage is high: {disk['used_percent']}%")
        open_ports = public_ports(ports)
        review_ports = sorted(open_ports & REVIEW_PORTS)
        if review_ports:
            warnings.append(f"public legacy/plain mail ports need review: {review_ports}")
        unexpected = sorted(port for port in open_ports if port < 10000 and port not in EXPECTED_PUBLIC_PORTS and port not in REVIEW_PORTS)
        if unexpected:
            warnings.append(f"unexpected public low listening ports need review: {unexpected}")
        if str(remote.get("mailcow_dir", "")) == "yes" and docker["container_count"] == 0:
            warnings.append("mailcow directory exists but no Docker containers were listed")

    result = "blocked" if blockers else "warn" if warnings else "ready"
    next_action = (
        "Resolve blockers before migration."
        if blockers
        else "Create non-root admin, activate firewall policy, and add auth-abuse protection before moving the control plane."
        if warnings
        else "Hardening preflight is clean; proceed to backup/restore gate."
    )

    return {
        "schema": "hetzner-hardening-preflight.v1",
        "updated_at": iso_now(),
        "local_host": socket.gethostname(),
        "target": target,
        "key_path": str(key_path),
        "result": result,
        "blockers": blockers,
        "warnings": warnings,
        "remote": {
            "hostname": remote.get("hostname", ""),
            "date": remote.get("date", ""),
            "os": remote.get("os", ""),
            "kernel": remote.get("kernel", ""),
            "uptime": remote.get("uptime", ""),
            "user": remote.get("user", ""),
            "disk": disk,
            "memory": memory,
            "sshd": sshd,
            "ufw": str(remote.get("ufw", ""))[:2000],
            "services": services,
            "enabled": enabled,
            "packages": str(remote.get("packages", ""))[:2000],
            "ports": ports,
            "docker": docker,
            "mailcow_dir": remote.get("mailcow_dir", ""),
            "login_users": users,
            "sudo_group": sudo_group,
            "root_password_state": remote.get("root_password_state", ""),
            "root_authorized_keys_count": remote.get("root_authorized_keys_count", ""),
            "apt_upgrade_count": apt_upgrade_count,
        },
        "next_action": next_action,
        "paths": {"status": str(STATUS_PATH), "report": str(REPORT_PATH)},
    }


def safe_md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(payload: dict[str, Any]) -> str:
    remote = payload["remote"]
    lines = [
        "# Hetzner Hardening Preflight",
        "",
        "Read-only hardening check. No secrets, env files, private keys, or mail contents are read.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Target: `{payload['target']}`",
        f"- Result: `{payload['result']}`",
        f"- Remote host: `{safe_md(remote['hostname'])}`",
        f"- OS: `{safe_md(remote['os'])}`",
        f"- Kernel: `{safe_md(remote['kernel'])}`",
        f"- Uptime: `{safe_md(remote['uptime'])}`",
        f"- Docker containers: {remote['docker']['container_count']}",
        f"- Mailcow directory: `{safe_md(remote['mailcow_dir'])}`",
        f"- APT upgrades pending: `{safe_md(remote['apt_upgrade_count'])}`",
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

    lines.extend(["## SSH", "", "| Setting | Value |", "|---|---|"])
    for key in sorted(remote["sshd"]):
        lines.append(f"| `{safe_md(key)}` | `{safe_md(remote['sshd'][key])}` |")

    lines.extend(["", "## Services", "", "| Service | Active | Enabled |", "|---|---|---|"])
    for service in sorted(set(remote["services"]) | set(remote["enabled"])):
        lines.append(f"| `{safe_md(service)}` | `{safe_md(remote['services'].get(service, ''))}` | `{safe_md(remote['enabled'].get(service, ''))}` |")

    lines.extend(["", "## Listening Ports", "", "| Proto | Address | Port |", "|---|---|---:|"])
    for item in remote["ports"]:
        lines.append(f"| `{safe_md(item['proto'])}` | `{safe_md(item['address'])}` | {item['port']} |")

    lines.extend(["", "## Docker Containers", "", "| Name | Status | Ports |", "|---|---|---|"])
    for item in remote["docker"]["containers"][:40]:
        lines.append(f"| `{safe_md(item['name'])}` | `{safe_md(item['status'])}` | {safe_md(item['ports'])} |")
    if not remote["docker"]["containers"]:
        lines.append("| none |  |  |")

    lines.extend(["", "## Users", ""])
    lines.append(f"- Non-root login users: `{safe_md(', '.join(remote['login_users']) or 'none')}`")
    lines.append(f"- Sudo group: `{safe_md(remote['sudo_group'])}`")
    lines.append(f"- Root password state: `{safe_md(remote['root_password_state'])}`")
    lines.append(f"- Root authorized_keys line count: `{safe_md(remote['root_authorized_keys_count'])}`")

    lines.extend(["", "## Next Action", "", payload["next_action"], ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Hetzner hardening preflight")
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
        print("Hetzner hardening preflight")
        print(f"Result: {payload['result']}")
        print(f"Warnings: {len(payload['warnings'])}")
        print(f"Status: {STATUS_PATH}")
        print(f"Report: {REPORT_PATH}")
    return 0 if payload["result"] == "ready" else 2 if payload["result"] == "warn" else 1


if __name__ == "__main__":
    raise SystemExit(main())

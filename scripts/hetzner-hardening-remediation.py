#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/hetzner-hardening-remediation"
STATUS_PATH = STATE_DIR / "status.json"
REPORT_PATH = STATE_DIR / "report.md"
PREFLIGHT_STATUS = HOME / ".local/state/hetzner-hardening-preflight/status.json"


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
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def has_text(items: list[Any], *needles: str) -> bool:
    text = "\n".join(str(item).lower() for item in items)
    return any(needle.lower() in text for needle in needles)


def action(
    action_id: str,
    title: str,
    status: str,
    why: str,
    commands: list[str],
    verify: list[str],
    caution: str = "",
) -> dict[str, Any]:
    return {
        "id": action_id,
        "title": title,
        "status": status,
        "why": why,
        "commands": commands,
        "verify": verify,
        "caution": caution,
    }


def admin_commands(admin_user: str) -> list[str]:
    return [
        f"id -u {admin_user} >/dev/null 2>&1 || adduser --disabled-password --gecos '' {admin_user}",
        f"usermod -aG sudo {admin_user}",
        f"install -d -m 700 -o {admin_user} -g {admin_user} /home/{admin_user}/.ssh",
        f"install -m 600 -o {admin_user} -g {admin_user} /root/.ssh/authorized_keys /home/{admin_user}/.ssh/authorized_keys",
        f"printf '%s ALL=(ALL) NOPASSWD:ALL\\n' {admin_user} > /etc/sudoers.d/90-nomarh-{admin_user}",
        f"chmod 0440 /etc/sudoers.d/90-nomarh-{admin_user}",
        f"visudo -cf /etc/sudoers.d/90-nomarh-{admin_user}",
        f"sudo -l -U {admin_user}",
    ]


def firewall_commands(*, include_pop3: bool, include_imap_plain: bool, include_pop3s: bool, include_sieve: bool) -> list[str]:
    commands = [
        "ufw default deny incoming",
        "ufw default allow outgoing",
        "ufw allow 22/tcp comment 'SSH'",
        "ufw allow 25/tcp comment 'SMTP inbound'",
        "ufw allow 80/tcp comment 'HTTP ACME/webmail redirect'",
        "ufw allow 443/tcp comment 'HTTPS webmail/admin'",
        "ufw allow 465/tcp comment 'SMTPS submission'",
        "ufw allow 587/tcp comment 'SMTP submission'",
        "ufw allow 993/tcp comment 'IMAPS'",
    ]
    if include_pop3:
        commands.append("ufw allow 110/tcp comment 'POP3 compatibility; prefer disabled'")
    if include_imap_plain:
        commands.append("ufw allow 143/tcp comment 'IMAP STARTTLS compatibility; prefer IMAPS 993 only'")
    if include_pop3s:
        commands.append("ufw allow 995/tcp comment 'POP3S compatibility; optional'")
    if include_sieve:
        commands.append("ufw allow 4190/tcp comment 'Sieve managesieve; optional'")
    commands.extend(["ufw --force enable", "ufw status verbose"])
    return commands


def port_review_commands() -> list[str]:
    return [
        "ss -tulpen",
        "docker ps --format 'table {{.Names}}\\t{{.Ports}}'",
        "cd /opt/mailcow-dockerized && grep -nE 'HTTP_BIND|HTTPS_BIND|IMAP_PORT|POP_PORT|SIEVE_PORT' mailcow.conf || true",
    ]


def build_payload(admin_user: str, include_sieve: bool, keep_pop3: bool, keep_plain_imap: bool, keep_pop3s: bool) -> dict[str, Any]:
    preflight = read_json(PREFLIGHT_STATUS)
    warnings = preflight.get("warnings") if isinstance(preflight, dict) and isinstance(preflight.get("warnings"), list) else []
    blockers = preflight.get("blockers") if isinstance(preflight, dict) and isinstance(preflight.get("blockers"), list) else []
    remote = preflight.get("remote") if isinstance(preflight, dict) and isinstance(preflight.get("remote"), dict) else {}
    target = preflight.get("target", "") if isinstance(preflight, dict) else ""
    key_path = preflight.get("key_path", "") if isinstance(preflight, dict) else ""
    result = preflight.get("result", "missing") if isinstance(preflight, dict) else "missing"

    remediation_blockers: list[str] = []
    if not isinstance(preflight, dict):
        remediation_blockers.append("hetzner hardening preflight status is missing; run `hetzner-hardening-preflight --json` first")
    remediation_blockers.extend(str(item) for item in blockers)

    actions: list[dict[str, Any]] = []
    if has_text(warnings, "non-root", "sudo group"):
        actions.append(
            action(
                "non-root-admin",
                "Create and verify non-root sudo admin",
                "pending",
                "Routine root login should not be the normal operating path.",
                admin_commands(admin_user),
                [
                    f"ssh -i {key_path} -o BatchMode=yes -o IdentitiesOnly=yes {admin_user}@{target.split('@')[-1]} 'id && sudo -n true'",
                    "hetzner-hardening-preflight --json",
                ],
                "Keep the root session open until the non-root SSH test and passwordless sudo test pass. Revisit NOPASSWD after access policy is settled.",
            )
        )

    if has_text(warnings, "ufw", "firewall"):
        actions.append(
            action(
                "firewall-policy",
                "Activate explicit host firewall policy",
                "pending",
                "The host currently reports UFW inactive.",
                firewall_commands(
                    include_pop3=keep_pop3,
                    include_imap_plain=keep_plain_imap,
                    include_pop3s=keep_pop3s,
                    include_sieve=include_sieve,
                ),
                ["ufw status verbose", "hetzner-hardening-preflight --json"],
                "Docker-published ports can bypass naive UFW policy. Confirm Mailcow/Docker behavior and prefer provider/firewall or DOCKER-USER controls where applicable.",
            )
        )

    if has_text(warnings, "legacy/plain mail ports", "public low listening ports", "mail ports", "listening ports"):
        actions.append(
            action(
                "port-review",
                "Review public mail and low ports",
                "pending",
                "Mailcow is running and public protocol exposure must be intentional.",
                port_review_commands(),
                ["hetzner-hardening-preflight --json"],
                "For normal Gmail/phone clients, prefer IMAPS 993 plus SMTP submission 465/587. POP3/110, IMAP/143, POP3S/995, and Sieve/4190 should stay public only if explicitly needed.",
            )
        )

    if not actions and not remediation_blockers:
        actions.append(
            action(
                "verify-clean",
                "Verify hardening remains clean",
                "ready",
                "No remediation action was generated from the current preflight warnings.",
                ["hetzner-hardening-preflight --json", "nomarh-ops --refresh --json"],
                ["hetzner-hardening-preflight --json", "nomarh-ops --refresh --json"],
            )
        )

    return {
        "schema": "hetzner-hardening-remediation.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": "blocked" if remediation_blockers else "pending" if any(item["status"] == "pending" for item in actions) else "ready",
        "target": target,
        "admin_user": admin_user,
        "source": {
            "status": str(PREFLIGHT_STATUS),
            "result": result,
            "warnings": warnings,
            "blockers": blockers,
            "remote_hostname": remote.get("hostname", ""),
            "remote_os": remote.get("os", ""),
            "key_path": key_path,
        },
        "blockers": remediation_blockers,
        "actions": actions,
        "paths": {"status": str(STATUS_PATH), "report": str(REPORT_PATH)},
    }


def safe_md(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Hetzner Hardening Remediation",
        "",
        "No remote changes are applied by this tool. It converts the read-only preflight result into ordered manual remediation actions.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Target: `{safe_md(payload['target'])}`",
        f"- Result: `{payload['result']}`",
        f"- Admin user target: `{safe_md(payload['admin_user'])}`",
        f"- Source preflight: `{safe_md(payload['source']['result'])}`",
        f"- Remote host: `{safe_md(payload['source']['remote_hostname'])}`",
        f"- Remote OS: `{safe_md(payload['source']['remote_os'])}`",
        "",
    ]
    if payload["blockers"]:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["blockers"])
        lines.append("")

    lines.extend(["## Actions", ""])
    for item in payload["actions"]:
        lines.extend(
            [
                f"### {safe_md(item['title'])}",
                "",
                f"- ID: `{safe_md(item['id'])}`",
                f"- Status: `{safe_md(item['status'])}`",
                f"- Why: {safe_md(item['why'])}",
            ]
        )
        if item.get("caution"):
            lines.append(f"- Caution: {safe_md(item['caution'])}")
        lines.extend(["", "Commands:", "", "```bash"])
        lines.extend(str(command) for command in item["commands"])
        lines.extend(["```", "", "Verify:", "", "```bash"])
        lines.extend(str(command) for command in item["verify"])
        lines.extend(["```", ""])

    lines.extend(["## Source Warnings", ""])
    if payload["source"]["warnings"]:
        lines.extend(f"- {safe_md(item)}" for item in payload["source"]["warnings"])
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate no-secret manual remediation plan for Hetzner hardening warnings")
    parser.add_argument("--admin-user", default="can", help="non-root sudo user name to use in generated commands")
    parser.add_argument("--include-sieve", action="store_true", help="include public Sieve/4190 in generated firewall commands")
    parser.add_argument("--keep-pop3", action="store_true", help="include public POP3/110 in generated firewall commands")
    parser.add_argument("--keep-plain-imap", action="store_true", help="include public IMAP/143 in generated firewall commands")
    parser.add_argument("--keep-pop3s", action="store_true", help="include public POP3S/995 in generated firewall commands")
    parser.add_argument("--json", action="store_true", help="print JSON payload")
    args = parser.parse_args()

    payload = build_payload(
        admin_user=args.admin_user,
        include_sieve=args.include_sieve,
        keep_pop3=args.keep_pop3,
        keep_plain_imap=args.keep_plain_imap,
        keep_pop3s=args.keep_pop3s,
    )
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Hetzner hardening remediation")
        print(f"Result: {payload['result']}")
        print(f"Actions: {len(payload['actions'])}")
        print(f"Report: {REPORT_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-mail-production-gate"
STATUS_PATH = STATE_DIR / "status.json"
REPORT_PATH = STATE_DIR / "gate.md"

HARDENING_STATUS = HOME / ".local/state/hetzner-hardening-preflight/status.json"
MIGRATION_READINESS_STATUS = HOME / ".local/state/nomarh-migration-readiness/readiness.json"

DEFAULT_DOMAIN = "nomarh.com"
DEFAULT_MAIL_HOST = "mail.nomarh.com"
DEFAULT_SMTP_IPV4 = "195.201.194.181"
DKIM_SELECTORS = ["dkim", "default", "mail", "selector1", "selector2"]
EXPECTED_PORTS = [25, 465, 587, 993, 80, 443]
REVIEW_PORTS = [110, 143, 995, 4190]
TLS_PORTS = [465, 993, 443]

CLOUDFLARE_CIDRS = [
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
]
CLOUDFLARE_NETWORKS = [ipaddress.ip_network(item) for item in CLOUDFLARE_CIDRS]


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


def safe_md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def dns_query(name: str, record_type: str) -> dict[str, Any]:
    try:
        import dns.resolver  # type: ignore

        resolver = dns.resolver.Resolver()
        resolver.timeout = 2.0
        resolver.lifetime = 4.0
        answers = resolver.resolve(name, record_type)
        values = [answer.to_text() for answer in answers]
        return {"ok": True, "name": name, "type": record_type, "values": values, "error": ""}
    except Exception as exc:
        return {
            "ok": False,
            "name": name,
            "type": record_type,
            "values": [],
            "error": f"{type(exc).__name__}: {str(exc)[:180]}",
        }


def ptr_query(ip_value: str) -> dict[str, Any]:
    try:
        import dns.resolver  # type: ignore
        import dns.reversename  # type: ignore

        resolver = dns.resolver.Resolver()
        resolver.timeout = 2.0
        resolver.lifetime = 4.0
        reverse_name = dns.reversename.from_address(ip_value)
        answers = resolver.resolve(reverse_name, "PTR")
        values = [answer.to_text().rstrip(".") for answer in answers]
        return {"ok": True, "ip": ip_value, "values": values, "error": ""}
    except Exception as exc:
        return {"ok": False, "ip": ip_value, "values": [], "error": f"{type(exc).__name__}: {str(exc)[:180]}"}


def normalize_host(value: str) -> str:
    return value.strip().strip(".").lower()


def txt_unquote(value: str) -> str:
    return value.replace('" "', "").strip('"')


def txt_values(record: dict[str, Any]) -> list[str]:
    return [txt_unquote(str(item)) for item in record.get("values", []) if str(item).strip()]


def parse_mx_hosts(record: dict[str, Any]) -> list[str]:
    hosts: list[str] = []
    for value in record.get("values", []):
        parts = str(value).split()
        if not parts:
            continue
        host = parts[-1]
        hosts.append(normalize_host(host))
    return hosts


def cloudflare_ip(ip_value: str) -> bool:
    try:
        address = ipaddress.ip_address(ip_value)
    except ValueError:
        return False
    return any(address in network for network in CLOUDFLARE_NETWORKS)


def socket_status(ip_value: str, port: int, timeout: float) -> dict[str, Any]:
    try:
        with socket.create_connection((ip_value, port), timeout=timeout):
            return {"status": "open", "error": ""}
    except Exception as exc:
        return {"status": "closed", "error": f"{type(exc).__name__}: {str(exc)[:140]}"}


def check_ports(ips: list[str], ports: list[int], timeout: float) -> dict[str, Any]:
    by_port: dict[str, Any] = {}
    for port in ports:
        checks = []
        for ip_value in ips:
            result = socket_status(ip_value, port, timeout)
            checks.append({"ip": ip_value, **result})
        status = "open" if any(item["status"] == "open" for item in checks) else "unverified"
        if checks and all("Network is unreachable" in item.get("error", "") for item in checks):
            status = "unreachable-from-probe"
        by_port[str(port)] = {"status": status, "checks": checks}
    return by_port


def tls_check(host: str, port: int, ips: list[str], timeout: float) -> dict[str, Any]:
    context = ssl.create_default_context()
    errors: list[str] = []
    for ip_value in ips:
        try:
            raw = socket.create_connection((ip_value, port), timeout=timeout)
            with raw:
                with context.wrap_socket(raw, server_hostname=host) as sock:
                    cert = sock.getpeercert()
                    not_after = str(cert.get("notAfter", ""))
                    expires_at = ""
                    days_remaining = None
                    if not_after:
                        expires = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                        expires_at = expires.isoformat().replace("+00:00", "Z")
                        days_remaining = max(0, int((expires - datetime.now(timezone.utc)).total_seconds() // 86400))
                    subject_parts: list[str] = []
                    for group in cert.get("subject", []):
                        for key, value in group:
                            if key in {"commonName", "organizationName"}:
                                subject_parts.append(f"{key}={value}")
                    return {
                        "ok": True,
                        "ip": ip_value,
                        "port": port,
                        "subject": ", ".join(subject_parts),
                        "expires_at": expires_at,
                        "days_remaining": days_remaining,
                        "error": "",
                    }
        except Exception as exc:
            errors.append(f"{ip_value}: {type(exc).__name__}: {str(exc)[:120]}")
    return {"ok": False, "ip": "", "port": port, "subject": "", "expires_at": "", "days_remaining": None, "error": " | ".join(errors[:4])}


def spf_authorizes_mailhost(spf_records: list[str], mail_host: str, mx_points_to_mailhost: bool, ips: list[str]) -> bool:
    normalized = " ".join(spf_records).lower()
    mail_host = normalize_host(mail_host)
    if not normalized:
        return False
    for ip_value in ips:
        if f"ip4:{ip_value}" in normalized or f"ip6:{ip_value}" in normalized:
            return True
    return (
        f"a:{mail_host}" in normalized
        or " a " in f" {normalized} "
        or (mx_points_to_mailhost and " mx " in f" {normalized} ")
    )


def dmarc_policy(dmarc_records: list[str]) -> str:
    text = " ".join(dmarc_records).lower()
    for part in text.split(";"):
        part = part.strip()
        if part.startswith("p="):
            return part.split("=", 1)[1].strip()
    return ""


def compact_txt(values: list[str]) -> list[str]:
    result = []
    for value in values:
        text = txt_unquote(value)
        result.append(text[:180] + ("..." if len(text) > 180 else ""))
    return result


def extract_mailcow(hardening: Any) -> dict[str, Any]:
    if not isinstance(hardening, dict):
        return {
            "present": False,
            "result": "missing",
            "mailcow_dir": "",
            "container_count": 0,
            "warnings": ["Hetzner hardening preflight status is missing."],
        }
    remote = hardening.get("remote") if isinstance(hardening.get("remote"), dict) else {}
    docker = remote.get("docker") if isinstance(remote.get("docker"), dict) else {}
    warnings = [str(item) for item in hardening.get("warnings", []) if isinstance(item, str)]
    return {
        "present": True,
        "result": str(hardening.get("result", "missing")),
        "mailcow_dir": str(remote.get("mailcow_dir", "")),
        "container_count": int(docker.get("container_count") or 0),
        "services": remote.get("services", {}),
        "ports": remote.get("ports", []),
        "warnings": warnings,
    }


def build_payload(domain: str, mail_host: str, expected_ipv4: str, timeout: float) -> dict[str, Any]:
    hardening = read_json(HARDENING_STATUS)
    migration_readiness = read_json(MIGRATION_READINESS_STATUS)
    mailcow = extract_mailcow(hardening)

    records = {
        "mail_a": dns_query(mail_host, "A"),
        "mail_aaaa": dns_query(mail_host, "AAAA"),
        "domain_mx": dns_query(domain, "MX"),
        "domain_txt": dns_query(domain, "TXT"),
        "dmarc_txt": dns_query(f"_dmarc.{domain}", "TXT"),
    }
    dkim: dict[str, Any] = {}
    for selector in DKIM_SELECTORS:
        name = f"{selector}._domainkey.{domain}"
        dkim[selector] = dns_query(name, "TXT")

    ips = [str(item) for item in records["mail_a"]["values"] + records["mail_aaaa"]["values"]]
    ips = [item for item in ips if item]
    mx_hosts = parse_mx_hosts(records["domain_mx"])
    mx_points_to_mailhost = normalize_host(mail_host) in mx_hosts
    spf_records = [item for item in txt_values(records["domain_txt"]) if item.lower().startswith("v=spf1")]
    dmarc_records = [item for item in txt_values(records["dmarc_txt"]) if item.lower().startswith("v=dmarc1")]
    found_dkim_selectors = [selector for selector, record in dkim.items() if record.get("ok") and record.get("values")]
    ptr = ptr_query(expected_ipv4)
    ptr_points_to_mailhost = normalize_host(mail_host) in [normalize_host(item) for item in ptr.get("values", [])]
    cf_addresses = [ip_value for ip_value in ips if cloudflare_ip(ip_value)]

    all_ports = EXPECTED_PORTS + REVIEW_PORTS
    ports = check_ports(ips or [expected_ipv4], all_ports, timeout)
    tls = {str(port): tls_check(mail_host, port, ips or [expected_ipv4], timeout) for port in TLS_PORTS}

    spf_ok = spf_authorizes_mailhost(spf_records, mail_host, mx_points_to_mailhost, [expected_ipv4, *ips])
    dmarc_p = dmarc_policy(dmarc_records)

    blockers: list[str] = []
    warnings: list[str] = []
    actions: list[str] = []

    if not records["mail_a"].get("ok") and not records["mail_aaaa"].get("ok"):
        blockers.append(f"{mail_host} has no usable A/AAAA DNS record.")
    if cf_addresses:
        blockers.append(f"{mail_host} resolves to Cloudflare proxy ranges: {', '.join(cf_addresses)}. Mail protocol hostnames must be DNS-only.")
    if expected_ipv4 and expected_ipv4 not in ips:
        warnings.append(f"{mail_host} does not include expected IPv4 {expected_ipv4}; resolved addresses are {', '.join(ips) or 'none'}.")
    if not mx_hosts:
        blockers.append(f"{domain} has no MX record.")
    elif not mx_points_to_mailhost:
        blockers.append(f"{domain} MX does not point to {mail_host}; current MX hosts: {', '.join(mx_hosts)}.")
    if not spf_records:
        blockers.append(f"{domain} has no SPF TXT record.")
    elif not spf_ok:
        blockers.append(f"{domain} SPF does not authorize {mail_host}/{expected_ipv4} for direct Mailcow outbound.")
    if not dmarc_records:
        blockers.append(f"_dmarc.{domain} has no DMARC record.")
    elif dmarc_p == "none":
        warnings.append("DMARC exists but policy is p=none; move toward quarantine/reject after warmup and alignment checks.")
    if not found_dkim_selectors:
        warnings.append("No DKIM record found on common Mailcow selectors; confirm the actual selector before production outbound.")
    if not ptr.get("ok") or not ptr_points_to_mailhost:
        blockers.append(f"PTR for {expected_ipv4} does not point back to {mail_host}.")

    if mailcow["mailcow_dir"] != "yes" or mailcow["container_count"] <= 0:
        blockers.append("Mailcow is not verified as running from Hetzner hardening preflight.")

    for port in [465, 587, 993]:
        if ports[str(port)]["status"] != "open":
            blockers.append(f"Client mail port {port} is not reachable from this probe.")
    if ports["25"]["status"] != "open":
        warnings.append("SMTP port 25 was not reachable from this workspace probe; verify from an external network and with the provider unblock.")
    for port in REVIEW_PORTS:
        if ports[str(port)]["status"] == "open":
            warnings.append(f"Port {port} is publicly reachable; close or document it if it is intentionally needed.")

    for port, result in tls.items():
        if not result.get("ok"):
            warnings.append(f"TLS check failed for port {port}: {result.get('error', '')}")
        elif isinstance(result.get("days_remaining"), int) and result["days_remaining"] < 30:
            warnings.append(f"TLS certificate on port {port} expires in {result['days_remaining']} day(s).")

    hardening_warnings = " | ".join(mailcow.get("warnings", []))
    if "UFW is not active" in hardening_warnings:
        warnings.append("UFW is inactive on the Hetzner host; apply a reviewed firewall policy before cutover.")
    if "no non-root login users found" in hardening_warnings or "sudo group" in hardening_warnings:
        warnings.append("Host still relies on root operational access; create a non-root sudo admin before decommissioning AWS.")

    if blockers:
        actions.extend(
            [
                "Keep Google Workspace MX active until Mailcow DNS alignment is complete.",
                "Publish Mailcow SPF/DKIM/DMARC records and rerun `nomarh-mail-production-gate --json`.",
                "Verify inbound SMTP/25 externally after Hetzner port unblock.",
            ]
        )
    if warnings:
        actions.extend(
            [
                "Review public POP3/IMAP/Sieve ports and close unused legacy protocols.",
                "Warm up outbound mail reputation slowly after SPF/DKIM/PTR alignment passes.",
            ]
        )

    result = "blocked" if blockers else "warn" if warnings else "ready"
    return {
        "schema": "nomarh-mail-production-gate.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "domain": domain,
        "mail_host": mail_host,
        "expected_ipv4": expected_ipv4,
        "summary": {
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
            "resolved_address_count": len(ips),
            "cloudflare_proxied_address_count": len(cf_addresses),
            "mx_points_to_mailhost": mx_points_to_mailhost,
            "spf_authorizes_mailhost": spf_ok,
            "dmarc_policy": dmarc_p or "missing",
            "dkim_selector_count": len(found_dkim_selectors),
            "ptr_points_to_mailhost": ptr_points_to_mailhost,
            "mailcow_container_count": mailcow["container_count"],
            "port25_status": ports["25"]["status"],
            "client_ports_open": all(ports[str(port)]["status"] == "open" for port in [465, 587, 993]),
            "cutover_ready": result == "ready",
        },
        "blockers": blockers,
        "warnings": warnings,
        "actions": list(dict.fromkeys(actions))[:10],
        "dns": {
            "mail_a": records["mail_a"],
            "mail_aaaa": records["mail_aaaa"],
            "mx_hosts": mx_hosts,
            "spf_records": compact_txt(spf_records),
            "dmarc_records": compact_txt(dmarc_records),
            "dkim_selectors_found": found_dkim_selectors,
            "dkim_checked": {selector: {"ok": bool(record.get("ok")), "error": record.get("error", "")} for selector, record in dkim.items()},
            "ptr": ptr,
        },
        "ports": ports,
        "tls": tls,
        "mailcow": mailcow,
        "migration_readiness_mail_gate": next(
            (
                gate
                for gate in migration_readiness.get("gates", [])
                if isinstance(migration_readiness, dict)
                and isinstance(gate, dict)
                and gate.get("id") == "mail"
            ),
            None,
        )
        if isinstance(migration_readiness, dict)
        else None,
        "paths": {
            "status": str(STATUS_PATH),
            "report": str(REPORT_PATH),
            "hardening": str(HARDENING_STATUS),
            "migration_readiness": str(MIGRATION_READINESS_STATUS),
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Nomarh Mail Production Gate",
        "",
        "No secrets, mailbox contents, env values, or private keys are read. This gate uses public DNS, socket/TLS probes, and existing no-secret status JSON.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Domain: `{payload['domain']}`",
        f"- Mail host: `{payload['mail_host']}`",
        f"- Result: `{payload['result']}`",
        f"- Cutover ready: `{summary['cutover_ready']}`",
        f"- Blockers: `{summary['blocker_count']}`; warnings: `{summary['warning_count']}`",
        f"- MX to mail host: `{summary['mx_points_to_mailhost']}`; SPF authorizes mail host: `{summary['spf_authorizes_mailhost']}`",
        f"- DMARC policy: `{summary['dmarc_policy']}`; DKIM common selectors found: `{summary['dkim_selector_count']}`; PTR aligned: `{summary['ptr_points_to_mailhost']}`",
        f"- Mailcow containers: `{summary['mailcow_container_count']}`; port 25: `{summary['port25_status']}`; client ports open: `{summary['client_ports_open']}`",
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

    lines.extend(["## DNS", "", "| Check | Value |", "|---|---|"])
    dns = payload["dns"]
    lines.append(f"| A | `{safe_md(', '.join(dns['mail_a'].get('values', [])) or dns['mail_a'].get('error'))}` |")
    lines.append(f"| AAAA | `{safe_md(', '.join(dns['mail_aaaa'].get('values', [])) or dns['mail_aaaa'].get('error'))}` |")
    lines.append(f"| MX | `{safe_md(', '.join(dns['mx_hosts']) or 'none')}` |")
    lines.append(f"| SPF | `{safe_md(' ; '.join(dns['spf_records']) or 'none')}` |")
    lines.append(f"| DMARC | `{safe_md(' ; '.join(dns['dmarc_records']) or 'none')}` |")
    lines.append(f"| DKIM selectors found | `{safe_md(', '.join(dns['dkim_selectors_found']) or 'none')}` |")
    lines.append(f"| PTR | `{safe_md(', '.join(dns['ptr'].get('values', [])) or dns['ptr'].get('error'))}` |")

    lines.extend(["", "## Ports", "", "| Port | Status | Details |", "|---:|---|---|"])
    for port in EXPECTED_PORTS + REVIEW_PORTS:
        item = payload["ports"][str(port)]
        detail = "; ".join(f"{check['ip']}={check['status']}" for check in item["checks"])
        lines.append(f"| {port} | `{safe_md(item['status'])}` | {safe_md(detail)} |")

    lines.extend(["", "## TLS", "", "| Port | OK | Expires | Days | Detail |", "|---:|---:|---|---:|---|"])
    for port in TLS_PORTS:
        item = payload["tls"][str(port)]
        lines.append(
            f"| {port} | `{safe_md(item.get('ok'))}` | `{safe_md(item.get('expires_at'))}` | `{safe_md(item.get('days_remaining'))}` | {safe_md(item.get('subject') or item.get('error'))} |"
        )

    lines.extend(["", "## Next Actions", ""])
    if payload["actions"]:
        lines.extend(f"{idx}. {safe_md(action)}" for idx, action in enumerate(payload["actions"], start=1))
    else:
        lines.append("- No action generated.")

    lines.extend(["", "## Source Paths", ""])
    for key, path in payload["paths"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether Nomarh Mailcow can safely become production mail")
    parser.add_argument("--domain", default=DEFAULT_DOMAIN)
    parser.add_argument("--mail-host", default=DEFAULT_MAIL_HOST)
    parser.add_argument("--expected-ipv4", default=DEFAULT_SMTP_IPV4)
    parser.add_argument("--timeout", type=float, default=4.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_payload(args.domain, args.mail_host, args.expected_ipv4, args.timeout)
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Nomarh Mail Production Gate")
        print(f"Result: {payload['result']}")
        print(f"Blockers: {payload['summary']['blocker_count']}")
        print(f"Warnings: {payload['summary']['warning_count']}")
        print(f"Report: {REPORT_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

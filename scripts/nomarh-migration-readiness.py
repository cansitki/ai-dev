#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-migration-readiness"
STATUS_PATH = STATE_DIR / "readiness.json"
REPORT_PATH = STATE_DIR / "readiness.md"

CAN_DOCTOR_STATUS = HOME / ".local/state/can-doctor/status.json"
RUNTIME_DASHBOARD_STATUS = HOME / ".local/state/control-plane-runtime-dashboard/status.json"
BACKUP_READINESS_STATUS = HOME / ".local/state/control-plane-backup-readiness/status.json"
RESTIC_BACKUP_STATUS = HOME / ".local/state/control-plane-restic-backup/status.json"
HETZNER_ACCESS_STATUS = HOME / ".local/state/hetzner-access-preflight/status.json"
HETZNER_HARDENING_STATUS = HOME / ".local/state/hetzner-hardening-preflight/status.json"
MAIL_PRODUCTION_GATE_STATUS = HOME / ".local/state/nomarh-mail-production-gate/status.json"
TMUX_CLEANUP_STATUS = HOME / ".local/state/tmux-cleanup-review/status.json"
CAN_OPS_REFRESH_STATUS = HOME / ".local/state/can-ops-refresh/status.json"
CAN_OPS_SCHEDULER_STATUS = HOME / ".local/state/can-ops-scheduler/status.json"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def age_hours(value: Any) -> float | None:
    parsed = parse_time(value)
    if parsed is None:
        return None
    return max(0.0, (utc_now() - parsed).total_seconds() / 3600)


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


def run_quiet(args: list[str], timeout: int = 120) -> dict[str, Any]:
    started = time.time()
    if not shutil.which(args[0]):
        return {
            "command": " ".join(args),
            "returncode": 127,
            "duration_seconds": 0,
            "note": "command not found",
        }
    try:
        proc = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        return {
            "command": " ".join(args),
            "returncode": proc.returncode,
            "duration_seconds": round(time.time() - started, 3),
        }
    except subprocess.TimeoutExpired:
        return {
            "command": " ".join(args),
            "returncode": 124,
            "duration_seconds": round(time.time() - started, 3),
            "note": f"timed out after {timeout}s",
        }
    except Exception as exc:
        return {
            "command": " ".join(args),
            "returncode": 1,
            "duration_seconds": round(time.time() - started, 3),
            "note": str(exc),
        }


def freshness(path: Path, status: Any, *, max_age_hours: float) -> dict[str, Any]:
    if not isinstance(status, dict):
        return {"path": str(path), "present": False, "fresh": False, "age_hours": None}
    age = age_hours(status.get("updated_at"))
    fresh = age is not None and age <= max_age_hours
    return {
        "path": str(path),
        "present": True,
        "fresh": fresh,
        "age_hours": round(age, 2) if age is not None else None,
        "updated_at": status.get("updated_at", ""),
    }


def doctor_checks(can_doctor: Any, *, category: str | None = None, status_set: set[str] | None = None) -> list[dict[str, str]]:
    if not isinstance(can_doctor, dict):
        return []
    checks = can_doctor.get("checks") if isinstance(can_doctor.get("checks"), list) else []
    result = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        if category and check.get("category") != category:
            continue
        if status_set and check.get("status") not in status_set:
            continue
        result.append(
            {
                "category": str(check.get("category", "")),
                "label": str(check.get("label", "")),
                "status": str(check.get("status", "")),
                "detail": str(check.get("detail", "")),
            }
        )
    return result


def make_gate(
    gate_id: str,
    title: str,
    status: str,
    evidence: list[str],
    actions: list[str],
    sources: list[str],
) -> dict[str, Any]:
    return {
        "id": gate_id,
        "title": title,
        "status": status,
        "evidence": [item for item in evidence if item],
        "actions": [item for item in actions if item],
        "sources": sources,
    }


def gate_backup(readiness: Any, restic: Any) -> dict[str, Any]:
    evidence: list[str] = []
    actions: list[str] = []
    status = "ready"

    if not isinstance(readiness, dict):
        return make_gate(
            "backup",
            "Backup and restore gate",
            "blocked",
            ["Control-plane backup readiness status is missing."],
            ["Run `control-plane-backup-readiness` and resolve missing backup surfaces."],
            [str(BACKUP_READINESS_STATUS), str(RESTIC_BACKUP_STATUS)],
        )

    readiness_result = str(readiness.get("result", "unknown"))
    readiness_blockers = readiness.get("blockers") if isinstance(readiness.get("blockers"), list) else []
    summary = readiness.get("summary") if isinstance(readiness.get("summary"), dict) else {}
    evidence.append(
        f"Backup readiness `{readiness_result}`: {summary.get('existing_surfaces', '?')}/{summary.get('surface_count', '?')} surfaces present, blockers={len(readiness_blockers)}."
    )
    if readiness_blockers:
        status = "blocked"
        actions.append("Configure the active `r2:` remote or update the backup readiness policy.")

    if not isinstance(restic, dict):
        status = "blocked"
        evidence.append("Control-plane restic backup status is missing.")
        actions.append("Run `control-plane-restic-backup --init --dry-run` after scoped R2 credentials are available.")
    else:
        restic_result = str(restic.get("result", "unknown"))
        restic_blockers = restic.get("blockers") if isinstance(restic.get("blockers"), list) else []
        repo = restic.get("repository") if isinstance(restic.get("repository"), dict) else {}
        evidence.append(
            f"Restic backup `{restic_result}`: blockers={len(restic_blockers)}, repo={repo.get('bucket') or 'no-bucket'}/{repo.get('prefix') or 'no-prefix'}."
        )
        if restic_blockers:
            status = "blocked"
            actions.append("Provide R2 endpoint, bucket, access key, secret key, and restic password through the secure vault/env path.")
        elif restic_result != "success":
            status = "warn" if status == "ready" else status
            actions.append("Run a real restic backup and a restore drill before DNS or AWS cutover.")

    return make_gate(
        "backup",
        "Backup and restore gate",
        status,
        evidence,
        actions,
        [str(BACKUP_READINESS_STATUS), str(RESTIC_BACKUP_STATUS)],
    )


def gate_access(access: Any, can_doctor: Any) -> dict[str, Any]:
    evidence: list[str] = []
    actions: list[str] = []
    status = "ready"

    if not isinstance(access, dict):
        status = "blocked"
        evidence.append("Hetzner access preflight status is missing.")
        actions.append("Run `hetzner-access-preflight --json`.")
    else:
        result = str(access.get("result", "unknown"))
        target = access.get("target") if isinstance(access.get("target"), dict) else {}
        evidence.append(f"Hetzner access preflight `{result}` for {target.get('raw', 'unknown target')}.")
        if result != "ready":
            status = "blocked"
            actions.append("Fix SSH/TCP/key access before moving any daily control-plane service.")

    ssh_checks = [check for check in doctor_checks(can_doctor, category="migration") if check["label"] == "Hetzner SSH"]
    if ssh_checks:
        check = ssh_checks[0]
        evidence.append(f"can-doctor Hetzner SSH: `{check['status']}`.")
        if check["status"] != "ok":
            status = "blocked"
            actions.append("Fix can-doctor Hetzner SSH warning before migration.")

    return make_gate(
        "access",
        "Hetzner access gate",
        status,
        evidence,
        actions,
        [str(HETZNER_ACCESS_STATUS), str(CAN_DOCTOR_STATUS)],
    )


def gate_hardening(hardening: Any) -> dict[str, Any]:
    evidence: list[str] = []
    actions: list[str] = []
    status = "ready"

    if not isinstance(hardening, dict):
        return make_gate(
            "hardening",
            "Hetzner hardening gate",
            "blocked",
            ["Hetzner hardening status is missing."],
            ["Run `hetzner-hardening-preflight --json`."],
            [str(HETZNER_HARDENING_STATUS)],
        )

    result = str(hardening.get("result", "unknown"))
    blockers = hardening.get("blockers") if isinstance(hardening.get("blockers"), list) else []
    warnings = hardening.get("warnings") if isinstance(hardening.get("warnings"), list) else []
    remote = hardening.get("remote") if isinstance(hardening.get("remote"), dict) else {}
    services = remote.get("services") if isinstance(remote.get("services"), dict) else {}
    docker = remote.get("docker") if isinstance(remote.get("docker"), dict) else {}
    disk = remote.get("disk") if isinstance(remote.get("disk"), dict) else {}
    evidence.append(
        f"Hardening `{result}`: blockers={len(blockers)}, warnings={len(warnings)}, host={remote.get('hostname', 'unknown')}, docker={services.get('docker', 'unknown')}, containers={docker.get('container_count', '?')}, disk={disk.get('used_percent', '?')}%."
    )

    if blockers:
        status = "blocked"
    elif warnings:
        status = "warn"

    warning_text = " | ".join(str(item) for item in warnings)
    if "non-root" in warning_text or "sudo" in warning_text:
        actions.append("Create a non-root sudo admin and confirm SSH login before disabling direct root operational use.")
    if "UFW" in warning_text or "firewall" in warning_text:
        actions.append("Activate an explicit firewall policy for SSH, HTTP/HTTPS, SMTP/submission, and IMAPS.")
    if "ports" in warning_text:
        actions.append("Review or close plain POP3/IMAP and mailcow service ports that do not need public exposure.")
    if not actions and status != "ready":
        actions.append(str(hardening.get("next_action", "Resolve hardening warnings.")))

    return make_gate(
        "hardening",
        "Hetzner hardening gate",
        status,
        evidence,
        actions,
        [str(HETZNER_HARDENING_STATUS)],
    )


def gate_runtime(runtime: Any, cleanup: Any, can_doctor: Any) -> dict[str, Any]:
    evidence: list[str] = []
    actions: list[str] = []
    status = "ready"

    if not isinstance(runtime, dict):
        status = "blocked"
        evidence.append("Control-plane runtime dashboard is missing.")
        actions.append("Run `control-plane-runtime-dashboard`.")
    else:
        tmux = runtime.get("tmux") if isinstance(runtime.get("tmux"), dict) else {}
        provider_count = tmux.get("provider_worker_count", "?")
        cleanup_count = tmux.get("cleanup_candidate_count", "?")
        total = tmux.get("total", "?")
        evidence.append(f"Runtime dashboard `{runtime.get('result', 'unknown')}`: tmux={total}, providers={provider_count}, cleanup={cleanup_count}.")
        cleanup_int = int(cleanup_count) if str(cleanup_count).isdigit() else 0
        if cleanup_int:
            status = "warn"
            actions.append("Review tmux cleanup candidates before copying runtime state to Hetzner.")

    if isinstance(cleanup, dict):
        summary = cleanup.get("summary") if isinstance(cleanup.get("summary"), dict) else {}
        evidence.append(
            f"Tmux cleanup review `{cleanup.get('result', 'unknown')}`: candidates={summary.get('candidate_count', '?')}, high={summary.get('review_high_count', '?')}, medium={summary.get('review_medium_count', '?')}."
        )

    tmux_sprawl = [check for check in doctor_checks(can_doctor, category="runtime") if check["label"] == "tmux sprawl"]
    if tmux_sprawl:
        status = "warn" if status == "ready" else status
        actions.append("Convert durable tmux loops into supervised services/timers on Hetzner.")

    return make_gate(
        "runtime",
        "Runtime cleanup gate",
        status,
        evidence,
        actions,
        [str(RUNTIME_DASHBOARD_STATUS), str(TMUX_CLEANUP_STATUS), str(CAN_DOCTOR_STATUS)],
    )


def gate_daily_ops(refresh: Any, scheduler: Any, can_doctor: Any) -> dict[str, Any]:
    evidence: list[str] = []
    actions: list[str] = []
    status = "ready"

    if isinstance(refresh, dict):
        evidence.append(f"Can ops refresh `{refresh.get('result', 'unknown')}`.")
        if refresh.get("result") not in {"success", "warn", "skipped"}:
            status = "warn"
            actions.append("Fix `can-ops-refresh` before relying on automatic daily status.")
    else:
        status = "warn"
        evidence.append("Can ops refresh status is missing.")
        actions.append("Run `can-ops-refresh --json`.")

    if isinstance(scheduler, dict):
        evidence.append(f"Can ops scheduler `{scheduler.get('result', 'unknown')}`, mode={scheduler.get('mode', 'unknown')}.")
        if scheduler.get("result") != "success":
            status = "warn"
            actions.append("Start the ops scheduler or install the systemd timer on the target host.")
    else:
        status = "warn"
        evidence.append("Can ops scheduler status is missing.")
        actions.append("Run `can-ops-scheduler start`.")

    ops_checks = [
        check
        for check in doctor_checks(can_doctor, category="operations", status_set={"warn", "fail"})
        if check["label"] in {"Can ops brief", "Can ops refresh", "Can ops scheduler"}
    ]
    if ops_checks:
        status = "warn"
        actions.append("Resolve can-doctor operations warnings before AWS decommission.")

    return make_gate(
        "daily_ops",
        "Daily operations gate",
        status,
        evidence,
        actions,
        [str(CAN_OPS_REFRESH_STATUS), str(CAN_OPS_SCHEDULER_STATUS), str(CAN_DOCTOR_STATUS)],
    )


def gate_mail(hardening: Any, mail_gate: Any) -> dict[str, Any]:
    evidence: list[str] = []
    actions: list[str] = []
    status = "ready"

    if isinstance(mail_gate, dict):
        summary = mail_gate.get("summary") if isinstance(mail_gate.get("summary"), dict) else {}
        gate_result = str(mail_gate.get("result", "unknown"))
        status = gate_result if gate_result in {"ready", "warn", "blocked"} else "warn"
        evidence.append(
            "Detailed mail gate "
            f"`{gate_result}`: blockers={summary.get('blocker_count', '?')}, warnings={summary.get('warning_count', '?')}, "
            f"MX={summary.get('mx_points_to_mailhost', '?')}, SPF={summary.get('spf_authorizes_mailhost', '?')}, "
            f"DKIM selectors={summary.get('dkim_selector_count', '?')}, PTR={summary.get('ptr_points_to_mailhost', '?')}."
        )
        actions.extend(str(item) for item in mail_gate.get("actions", [])[:4] if str(item).strip())
        return make_gate(
            "mail",
            "Mail production gate",
            status,
            evidence,
            actions or ["Run `nomarh-mail-production-gate --json` and resolve mail DNS/protocol warnings."],
            [str(MAIL_PRODUCTION_GATE_STATUS), str(HETZNER_HARDENING_STATUS)],
        )

    if not isinstance(hardening, dict):
        return make_gate(
            "mail",
            "Mail production gate",
            "blocked",
            ["Hetzner hardening status is missing, so mailcow state cannot be summarized."],
            ["Run `hetzner-hardening-preflight --json`."],
            [str(HETZNER_HARDENING_STATUS)],
        )

    remote = hardening.get("remote") if isinstance(hardening.get("remote"), dict) else {}
    docker = remote.get("docker") if isinstance(remote.get("docker"), dict) else {}
    container_count = int(docker.get("container_count") or 0)
    mailcow_dir = str(remote.get("mailcow_dir", ""))
    warnings = hardening.get("warnings") if isinstance(hardening.get("warnings"), list) else []
    evidence.append(f"Mailcow directory={mailcow_dir}, containers={container_count}.")

    if mailcow_dir != "yes" or container_count == 0:
        status = "blocked"
        actions.append("Install or repair mailcow before moving production MX/IMAP users.")
    else:
        port_warnings = [str(item) for item in warnings if "mail ports" in str(item) or "listening ports" in str(item)]
        if port_warnings:
            status = "warn"
            actions.append("Review mail ports and confirm which protocols are intentionally public.")
        actions.append("Before production mail cutover: confirm PTR/rDNS, SPF, DKIM, DMARC, TLS certs, and outbound reputation warmup.")

    return make_gate(
        "mail",
        "Mail production gate",
        status,
        evidence,
        actions,
        [str(HETZNER_HARDENING_STATUS)],
    )


def build_payload(refresh_results: list[dict[str, Any]]) -> dict[str, Any]:
    can_doctor = read_json(CAN_DOCTOR_STATUS)
    runtime = read_json(RUNTIME_DASHBOARD_STATUS)
    readiness = read_json(BACKUP_READINESS_STATUS)
    restic = read_json(RESTIC_BACKUP_STATUS)
    access = read_json(HETZNER_ACCESS_STATUS)
    hardening = read_json(HETZNER_HARDENING_STATUS)
    mail_gate = read_json(MAIL_PRODUCTION_GATE_STATUS)
    cleanup = read_json(TMUX_CLEANUP_STATUS)
    refresh = read_json(CAN_OPS_REFRESH_STATUS)
    scheduler = read_json(CAN_OPS_SCHEDULER_STATUS)

    gates = [
        gate_access(access, can_doctor),
        gate_backup(readiness, restic),
        gate_hardening(hardening),
        gate_runtime(runtime, cleanup, can_doctor),
        gate_daily_ops(refresh, scheduler, can_doctor),
        gate_mail(hardening, mail_gate),
    ]

    blocked = [gate for gate in gates if gate["status"] == "blocked"]
    warned = [gate for gate in gates if gate["status"] == "warn"]
    result = "blocked" if blocked else "warn" if warned else "ready"

    next_actions: list[str] = []
    for gate in gates:
        if gate["status"] == "ready":
            continue
        for action in gate["actions"]:
            if action not in next_actions:
                next_actions.append(action)

    status_sources = {
        "can_doctor": freshness(CAN_DOCTOR_STATUS, can_doctor, max_age_hours=2),
        "runtime_dashboard": freshness(RUNTIME_DASHBOARD_STATUS, runtime, max_age_hours=2),
        "backup_readiness": freshness(BACKUP_READINESS_STATUS, readiness, max_age_hours=24),
        "restic_backup": freshness(RESTIC_BACKUP_STATUS, restic, max_age_hours=24),
        "hetzner_access": freshness(HETZNER_ACCESS_STATUS, access, max_age_hours=24),
        "hetzner_hardening": freshness(HETZNER_HARDENING_STATUS, hardening, max_age_hours=24),
        "mail_production_gate": freshness(MAIL_PRODUCTION_GATE_STATUS, mail_gate, max_age_hours=24),
        "tmux_cleanup": freshness(TMUX_CLEANUP_STATUS, cleanup, max_age_hours=24),
        "can_ops_refresh": freshness(CAN_OPS_REFRESH_STATUS, refresh, max_age_hours=12),
        "can_ops_scheduler": freshness(CAN_OPS_SCHEDULER_STATUS, scheduler, max_age_hours=12),
    }

    stale = [name for name, source in status_sources.items() if not source["fresh"]]
    if stale and result == "ready":
        result = "warn"
    if stale:
        next_actions.append(f"Refresh stale or missing status sources: {', '.join(stale)}.")

    return {
        "schema": "nomarh-migration-readiness.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "summary": {
            "gate_count": len(gates),
            "ready": sum(1 for gate in gates if gate["status"] == "ready"),
            "warn": len(warned),
            "blocked": len(blocked),
            "stale_sources": stale,
        },
        "gates": gates,
        "next_actions": next_actions[:12],
        "refresh_results": refresh_results,
        "sources": status_sources,
        "paths": {
            "status": str(STATUS_PATH),
            "report": str(REPORT_PATH),
        },
    }


def safe_md(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Nomarh Migration Readiness",
        "",
        "No secret values are read or printed. This is an aggregate of existing local status JSON files.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Gates: {payload['summary']['ready']} ready, {payload['summary']['warn']} warn, {payload['summary']['blocked']} blocked",
        "",
        "## Gate Matrix",
        "",
        "| Gate | Status | Evidence |",
        "|---|---|---|",
    ]
    for gate in payload["gates"]:
        evidence = "<br>".join(safe_md(item) for item in gate["evidence"])
        lines.append(f"| {safe_md(gate['title'])} | `{safe_md(gate['status'])}` | {evidence} |")

    lines.extend(["", "## Next Actions", ""])
    if payload["next_actions"]:
        lines.extend(f"{idx}. {safe_md(action)}" for idx, action in enumerate(payload["next_actions"], start=1))
    else:
        lines.append("- No blocking action generated.")

    lines.extend(["", "## Status Sources", "", "| Source | Fresh | Age Hours | Path |", "|---|---:|---:|---|"])
    for name, source in payload["sources"].items():
        lines.append(
            f"| `{safe_md(name)}` | `{source['fresh']}` | `{safe_md(source.get('age_hours'))}` | `{safe_md(source['path'])}` |"
        )

    lines.append("")
    return "\n".join(lines)


def refresh_sources() -> list[dict[str, Any]]:
    commands = [
        ["control-plane-backup-readiness"],
        ["control-plane-restic-backup", "--json"],
        ["hetzner-access-preflight", "--json"],
        ["hetzner-hardening-preflight", "--json"],
        ["can-doctor", "--json"],
        ["control-plane-runtime-dashboard"],
        ["tmux-cleanup-review"],
        ["can-doctor", "--json"],
    ]
    return [run_quiet(command) for command in commands]


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate Nomarh AWS-to-Hetzner migration readiness")
    parser.add_argument("--refresh", action="store_true", help="refresh source status commands before building readiness")
    parser.add_argument("--json", action="store_true", help="print JSON payload")
    args = parser.parse_args()

    refresh_results = refresh_sources() if args.refresh else []
    payload = build_payload(refresh_results)
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        summary = payload["summary"]
        print("Nomarh migration readiness")
        print(f"Result: {payload['result']}")
        print(f"Gates: {summary['ready']} ready, {summary['warn']} warn, {summary['blocked']} blocked")
        print(f"Status: {STATUS_PATH}")
        print(f"Report: {REPORT_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

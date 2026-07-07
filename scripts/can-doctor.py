#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
VAULT = Path(os.environ.get("VAULT_DIR") or os.environ.get("OBSIDIAN_VAULT_DIR") or HOME / "Can")
STATE_DIR = HOME / ".local/state/can-doctor"
STATUS_PATH = STATE_DIR / "status.json"
HISTORY_PATH = STATE_DIR / "history.jsonl"
TMUX_INVENTORY_PATH = STATE_DIR / "tmux-inventory.json"
CONTROL_PLANE_BACKUP_STATUS = HOME / ".local/state/control-plane-backup-readiness/status.json"
CONTROL_PLANE_RESTIC_BACKUP_STATUS = HOME / ".local/state/control-plane-restic-backup/status.json"
CONTROL_PLANE_RUNTIME_DASHBOARD_STATUS = HOME / ".local/state/control-plane-runtime-dashboard/status.json"
CAN_OPS_BRIEF_STATUS = HOME / ".local/state/can-ops-brief/status.json"
CAN_OPS_REFRESH_STATUS = HOME / ".local/state/can-ops-refresh/status.json"
CAN_OPS_SCHEDULER_STATUS = HOME / ".local/state/can-ops-scheduler/status.json"
TMUX_CLEANUP_REVIEW_STATUS = HOME / ".local/state/tmux-cleanup-review/status.json"
HETZNER_ACCESS_PREFLIGHT_STATUS = HOME / ".local/state/hetzner-access-preflight/status.json"
HETZNER_HARDENING_PREFLIGHT_STATUS = HOME / ".local/state/hetzner-hardening-preflight/status.json"
HETZNER_TARGET = os.environ.get("CAN_DOCTOR_HETZNER_SSH_TARGET", "root@195.201.194.181")
HETZNER_KEY = Path(os.environ.get("CAN_DOCTOR_HETZNER_SSH_KEY", str(HOME / ".ssh/nomarh_hetzner")))
EXPECTED_SYNC = os.environ.get("CAN_DOCTOR_EXPECT_SYNC", "official").strip().lower()
THEME_SYNC_DISABLED_FILE = HOME / ".config/tmux-theme-sync/disabled"

CRITICAL_TMUX_SESSIONS = {
    "can-ops-refresh-loop",
    "github-repo-sweep",
    "novnc",
    "obsidian-headless",
    "tmux-theme-sync",
    "ttyd",
    "vault-backup",
}
EXPECTED_TMUX_SESSIONS = [
    "obsidian-headless",
    "novnc",
    "vault-backup",
    "github-repo-sweep",
    "can-ops-refresh-loop",
]
PROVIDER_TMUX_PREFIXES = (
    "clore-",
    "prlcompute",
    "provider-",
    "salad-",
)
PROVIDER_TMUX_EXACT = {
    "modelos-wallet",
}
PROJECT_TMUX_PREFIXES = (
    "antelok",
    "avocat-",
    "bmu-",
    "can-workbench",
    "jelly-",
    "main-",
    "nomarh",
    "openai-",
    "redm-",
)
SENSITIVE_TMUX_MARKERS = ("secret", "wallet")


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
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def age_hours(value: Any) -> float | None:
    parsed = parse_time(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (utc_now() - parsed.astimezone(timezone.utc)).total_seconds() / 3600)


def run(args: list[str], timeout: int = 8) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except Exception as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def falseish(value: str) -> bool:
    return value.strip().lower() in {"0", "false", "no", "off"}


def theme_sync_expected() -> bool:
    explicit = os.environ.get("CAN_DOCTOR_EXPECT_THEME_SYNC")
    if explicit is not None:
        return not falseish(explicit)
    if THEME_SYNC_DISABLED_FILE.exists():
        return False

    merged: dict[str, str] = {}
    for path in (HOME / ".config/tmux-theme-sync/env", HOME / "main.env"):
        merged.update(read_env_file(path))
    merged.update({key: value for key, value in os.environ.items() if key.startswith("TMUX_THEME_SYNC_")})

    enabled = merged.get("TMUX_THEME_SYNC_ENABLED")
    if enabled is not None and falseish(enabled):
        return False
    return bool(merged.get("TMUX_THEME_SYNC_TOKEN"))


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def directory_size(path: Path) -> str:
    proc = run(["du", "-sh", str(path)], timeout=20)
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.split()[0]
    return "unknown"


def count_files(path: Path) -> int:
    total = 0
    for _, _, files in os.walk(path):
        total += len(files)
    return total


def tmux_sessions() -> list[str]:
    proc = run(["tmux", "ls"], timeout=5)
    if proc.returncode != 0:
        return []
    sessions: list[str] = []
    for line in proc.stdout.splitlines():
        name = line.split(":", 1)[0].strip()
        if name:
            sessions.append(name)
    return sessions


def tmux_has(session: str) -> bool:
    return run(["tmux", "has-session", "-t", session], timeout=3).returncode == 0


def tmux_session_records() -> list[dict[str, Any]]:
    sessions_proc = run(
        [
            "tmux",
            "list-sessions",
            "-F",
            "#{session_name}\t#{session_created}\t#{session_windows}\t#{session_attached}",
        ],
        timeout=5,
    )
    if sessions_proc.returncode != 0:
        return []

    panes_proc = run(
        [
            "tmux",
            "list-panes",
            "-a",
            "-F",
            "#{session_name}\t#{pane_pid}\t#{pane_current_command}\t#{pane_current_path}",
        ],
        timeout=5,
    )
    pane_by_session: dict[str, dict[str, Any]] = {}
    if panes_proc.returncode == 0:
        for line in panes_proc.stdout.splitlines():
            parts = line.split("\t", 3)
            if len(parts) != 4:
                continue
            session, pane_pid, command, path = parts
            pane_by_session.setdefault(
                session,
                {
                    "pane_pid": pane_pid,
                    "command": command,
                    "path": path,
                },
            )

    records: list[dict[str, Any]] = []
    now_epoch = utc_now().timestamp()
    for line in sessions_proc.stdout.splitlines():
        parts = line.split("\t", 3)
        if len(parts) != 4:
            continue
        name, created_raw, windows_raw, attached_raw = parts
        try:
            created_epoch = int(created_raw)
        except ValueError:
            created_epoch = 0
        try:
            windows = int(windows_raw)
        except ValueError:
            windows = 0
        try:
            attached = int(attached_raw)
        except ValueError:
            attached = 0

        age_days = None
        created_iso = ""
        if created_epoch > 0:
            created_dt = datetime.fromtimestamp(created_epoch, tz=timezone.utc)
            created_iso = created_dt.isoformat().replace("+00:00", "Z")
            age_days = max(0.0, (now_epoch - created_epoch) / 86400)

        pane = pane_by_session.get(name, {})
        record = {
            "name": name,
            "category": classify_tmux_session(name),
            "created_at": created_iso,
            "age_days": round(age_days, 1) if age_days is not None else None,
            "windows": windows,
            "attached": attached,
            "pane_pid": pane.get("pane_pid", ""),
            "command": pane.get("command", ""),
            "path": pane.get("path", ""),
        }
        records.append(record)
    return sorted(records, key=lambda item: str(item["name"]))


def classify_tmux_session(name: str) -> str:
    lowered = name.lower()
    if name in CRITICAL_TMUX_SESSIONS:
        return "critical"
    if name in EXPECTED_TMUX_SESSIONS:
        return "expected_missing_or_disabled"
    if name in PROVIDER_TMUX_EXACT or lowered.startswith(PROVIDER_TMUX_PREFIXES):
        return "provider_worker"
    if any(marker in lowered for marker in SENSITIVE_TMUX_MARKERS):
        return "sensitive"
    if lowered.startswith(PROJECT_TMUX_PREFIXES):
        return "project_work"
    return "other"


def tmux_inventory_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for record in records:
        category = str(record["category"])
        counts[category] = counts.get(category, 0) + 1

    missing_expected = [
        session
        for session in EXPECTED_TMUX_SESSIONS
        if not any(record["name"] == session for record in records)
    ]

    cleanup_candidates = [
        record
        for record in records
        if record["category"] in {"project_work", "other"}
        and int(record.get("attached") or 0) == 0
        and (record.get("age_days") is not None and float(record["age_days"]) >= 14)
    ]

    return {
        "updated_at": iso_now(),
        "total": len(records),
        "counts": counts,
        "missing_expected": missing_expected,
        "cleanup_candidates": cleanup_candidates[:25],
        "sessions": records,
    }


def runtime_dashboard_status() -> tuple[dict[str, Any] | None, float | None]:
    status = read_json(CONTROL_PLANE_RUNTIME_DASHBOARD_STATUS)
    if not isinstance(status, dict):
        return None, None
    return status, age_hours(status.get("updated_at"))


def runtime_dashboard_is_fresh() -> bool:
    status, age = runtime_dashboard_status()
    if not isinstance(status, dict) or age is None or age > 2:
        return False
    return str(status.get("result", "")) != "blocked"


def disk_usage(path: Path) -> tuple[int, int, int, float] | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    used_pct = (usage.used / usage.total) * 100 if usage.total else 0.0
    return usage.total, usage.used, usage.free, used_pct


def bytes_to_gib(value: int) -> str:
    return f"{value / (1024 ** 3):.1f}GiB"


class Doctor:
    def __init__(self, *, json_mode: bool = False) -> None:
        self.failures = 0
        self.warnings = 0
        self.checks: list[dict[str, str]] = []
        self.json_mode = json_mode

    def line(self, status: str, label: str, detail: str = "", category: str = "general") -> None:
        if status == "fail":
            self.failures += 1
        elif status == "warn":
            self.warnings += 1
        check = {
            "status": status,
            "category": category,
            "label": label,
            "detail": detail,
        }
        self.checks.append(check)
        if not self.json_mode:
            suffix = f" - {detail}" if detail else ""
            print(f"[{status}] {label}{suffix}")

    def ok(self, label: str, detail: str = "", category: str = "general") -> None:
        self.line("ok", label, detail, category)

    def warn(self, label: str, detail: str = "", category: str = "general") -> None:
        self.line("warn", label, detail, category)

    def fail(self, label: str, detail: str = "", category: str = "general") -> None:
        self.line("fail", label, detail, category)

    def result(self) -> str:
        if self.failures:
            return "fail"
        if self.warnings:
            return "warn"
        return "ok"

    def payload(self) -> dict[str, Any]:
        return {
            "updated_at": iso_now(),
            "host": socket.gethostname(),
            "result": self.result(),
            "failures": self.failures,
            "warnings": self.warnings,
            "ok": sum(1 for check in self.checks if check["status"] == "ok"),
            "checks": self.checks,
        }


def check_system(doctor: Doctor) -> None:
    doctor.ok("Host", socket.gethostname(), "system")
    usage = disk_usage(Path.home())
    if usage is None:
        doctor.warn("Disk", "could not read home filesystem usage", "system")
    else:
        total, used, free, used_pct = usage
        detail = f"{bytes_to_gib(used)} used / {bytes_to_gib(total)} total ({used_pct:.0f}% used, {bytes_to_gib(free)} free)"
        if used_pct >= 95:
            doctor.fail("Disk", detail, "system")
        elif used_pct >= 85:
            doctor.warn("Disk", detail, "system")
        else:
            doctor.ok("Disk", detail, "system")

    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        values: dict[str, int] = {}
        for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                values[parts[0].rstrip(":")] = int(parts[1]) * 1024
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", 0)
        if total and available:
            available_pct = (available / total) * 100
            detail = f"{bytes_to_gib(available)} available / {bytes_to_gib(total)} total ({available_pct:.0f}% available)"
            if available_pct < 5:
                doctor.fail("Memory", detail, "system")
            elif available_pct < 15:
                doctor.warn("Memory", detail, "system")
            else:
                doctor.ok("Memory", detail, "system")


def check_vault(doctor: Doctor) -> None:
    if not VAULT.exists():
        doctor.fail("Vault", f"missing at {VAULT}", "vault")
        return

    doctor.ok("Vault", f"{VAULT} ({count_files(VAULT)} files, {directory_size(VAULT)})", "vault")

    core_plugins = read_json(VAULT / ".obsidian/core-plugins.json")
    if isinstance(core_plugins, dict):
        sync_enabled = bool(core_plugins.get("sync"))
    elif isinstance(core_plugins, list):
        sync_enabled = "sync" in core_plugins
    else:
        sync_enabled = False

    if sync_enabled and EXPECTED_SYNC == "remotely-save":
        doctor.fail("Official Obsidian Sync", "enabled but CAN_DOCTOR_EXPECT_SYNC=remotely-save", "vault")
    elif sync_enabled:
        doctor.ok("Official Obsidian Sync", "enabled", "vault")
    else:
        detail = "disabled"
        if EXPECTED_SYNC == "official":
            doctor.warn("Official Obsidian Sync", f"{detail}; expected by current policy", "vault")
        else:
            doctor.ok("Official Obsidian Sync", detail, "vault")

    community = read_json(VAULT / ".obsidian/community-plugins.json")
    remotely_enabled = isinstance(community, list) and "remotely-save" in community
    remotely_path = VAULT / ".obsidian/plugins/remotely-save/data.json"
    remotely_data = read_json(remotely_path)
    service = remotely_data.get("serviceType") if isinstance(remotely_data, dict) else None

    if remotely_enabled and service:
        doctor.ok("Remotely Save", f"enabled, service={service}", "vault")
    elif remotely_enabled and remotely_path.exists() and remotely_path.stat().st_size > 0:
        doctor.ok("Remotely Save", "enabled, config file present", "vault")
    elif EXPECTED_SYNC == "remotely-save":
        doctor.fail("Remotely Save", "plugin not enabled or config missing", "vault")
    else:
        doctor.ok("Remotely Save", "not used by current sync policy", "vault")


def check_migration_docs(doctor: Doctor) -> None:
    docs = [
        VAULT / "infrastructure/Nomarh Main Server Migration and Daily Operations Plan 2026-07-04.md",
        VAULT / "infrastructure/Nomarh Control Plane Service Inventory 2026-07-04.md",
    ]
    missing = [path.name for path in docs if not path.exists()]
    if missing:
        doctor.warn("Nomarh migration docs", f"missing: {', '.join(missing)}", "migration")
    else:
        doctor.ok("Nomarh migration docs", "plan and service inventory present", "migration")


def check_vault_guard(doctor: Doctor) -> None:
    if shutil.which("vault-guard"):
        run(["vault-guard", "scan", "--limit", "0"], timeout=60)

    status = read_json(HOME / ".local/state/vault-guard/status.json")
    if not isinstance(status, dict):
        doctor.warn("Vault guard", "no status yet", "vault")
        return

    count = int(status.get("suspicious_count") or 0)
    updated = status.get("updated_at", "")
    age = age_hours(updated)
    age_note = f", updated {age:.1f}h ago" if age is not None else ""
    if count:
        doctor.warn("Vault guard", f"{count} suspicious paths{age_note}; see ~/.local/state/vault-guard/last-report.md", "vault")
    elif age is not None and age > 48:
        doctor.warn("Vault guard", f"clean but stale ({age:.1f}h old)", "vault")
    else:
        doctor.ok("Vault guard", f"no suspicious paths{age_note}", "vault")


def check_tmux(doctor: Doctor) -> None:
    records = tmux_session_records()
    sessions = [str(record["name"]) for record in records]
    if not sessions:
        doctor.warn("tmux", "no sessions found or tmux unavailable", "runtime")
        return

    inventory = tmux_inventory_payload(records)
    write_json_atomic(TMUX_INVENTORY_PATH, inventory)

    doctor.ok("tmux sessions", f"{len(sessions)} sessions visible", "runtime")
    doctor.ok("Tmux inventory", f"written to {TMUX_INVENTORY_PATH}", "runtime")
    if len(sessions) > 40:
        doctor.warn("tmux sprawl", f"{len(sessions)} sessions; group into critical/workers/work sessions before migration", "runtime")

    expected = [
        ("obsidian-headless", "Obsidian headless"),
        ("novnc", "noVNC"),
        ("vault-backup", "Vault GitHub backup"),
        ("can-ops-refresh-loop", "Can ops refresh loop"),
    ]
    if theme_sync_expected():
        expected.append(("tmux-theme-sync", "Tmux theme sync"))
    else:
        doctor.ok("Tmux theme sync", "disabled or not configured", "runtime")
    session_set = set(sessions)
    for session, label in expected:
        if session in session_set:
            doctor.ok(label, f"tmux:{session} running", "runtime")
        else:
            doctor.warn(label, f"tmux:{session} not running", "runtime")

    counts = inventory.get("counts", {})
    provider_count = int(counts.get("provider_worker") or 0)
    if provider_count:
        if runtime_dashboard_is_fresh():
            doctor.ok(
                "Provider/worker dashboard",
                f"{provider_count} provider sessions summarized in {CONTROL_PLANE_RUNTIME_DASHBOARD_STATUS}",
                "runtime",
            )
        else:
            doctor.warn("Provider/worker tmux", f"{provider_count} provider sessions should report through one dashboard", "runtime")

    cleanup_count = len(inventory.get("cleanup_candidates") or [])
    if cleanup_count:
        doctor.warn("Tmux cleanup candidates", f"{cleanup_count} old detached project/other sessions in inventory", "runtime")


def backup_status_detail(status: dict[str, Any]) -> tuple[str, str]:
    state = str(status.get("state", "unknown"))
    message = str(status.get("message", ""))
    updated = str(status.get("updated_at", ""))
    age = age_hours(updated)
    age_note = f", {age:.1f}h old" if age is not None else ""
    detail = f"{state}: {message} ({updated}{age_note})"
    return state, detail


def check_backup_status(doctor: Doctor) -> None:
    checks = [
        ("Vault backup status", HOME / ".local/state/vault-backup/status.json", 24),
    ]
    for label, path, stale_hours in checks:
        status = read_json(path)
        if not isinstance(status, dict):
            doctor.warn(label, "no status file", "backup")
            continue
        state, detail = backup_status_detail(status)
        updated_age = age_hours(status.get("updated_at", ""))
        if state == "disabled":
            doctor.warn(label, f"{detail}; scoped restic replacement required before Hetzner migration", "backup")
        elif updated_age is not None and updated_age > stale_hours:
            doctor.warn(label, f"{detail}; stale", "backup")
        elif state in {"success", "sleeping", "running"}:
            doctor.ok(label, detail, "backup")
        else:
            doctor.warn(label, detail, "backup")

    sweep = read_json(HOME / ".local/state/github-repo-sweep/state.json")
    if isinstance(sweep, dict):
        age = age_hours(sweep.get("last_checked_at"))
        repo_count = sweep.get("repo_count", "unknown")
        if age is not None and age > 48:
            doctor.warn("GitHub repo sweep", f"stale: {repo_count} repos, last check {age:.1f}h ago", "backup")
        else:
            doctor.ok("GitHub repo sweep", f"{repo_count} repos checked", "backup")
    else:
        doctor.warn("GitHub repo sweep", "no state file", "backup")


def check_control_plane_backup_readiness(doctor: Doctor) -> None:
    status = read_json(CONTROL_PLANE_BACKUP_STATUS)
    if not isinstance(status, dict):
        doctor.warn(
            "Control-plane backup readiness",
            "missing; run control-plane-backup-readiness",
            "backup",
        )
        return

    age = age_hours(status.get("updated_at"))
    age_note = f", {age:.1f}h old" if age is not None else ""
    if age is not None and age > 24:
        doctor.warn("Control-plane backup readiness", f"stale{age_note}; rerun manifest", "backup")
        return

    summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
    result = str(status.get("result", "unknown"))
    present = summary.get("existing_surfaces", "?")
    total = summary.get("surface_count", "?")
    blockers = summary.get("blocker_count", "?")
    secret_surfaces = summary.get("secret_bearing_existing_surfaces", "?")
    detail = f"{result}: {present}/{total} surfaces present, {secret_surfaces} secret-bearing, blockers={blockers}{age_note}"
    doctor.ok("Control-plane backup readiness", detail, "backup")


def check_control_plane_restic_backup(doctor: Doctor) -> None:
    status = read_json(CONTROL_PLANE_RESTIC_BACKUP_STATUS)
    if not isinstance(status, dict):
        doctor.warn(
            "Control-plane restic backup",
            "not run yet; use control-plane-restic-backup after R2 credentials are available",
            "backup",
        )
        return

    age = age_hours(status.get("updated_at"))
    age_note = f", {age:.1f}h old" if age is not None else ""
    result = str(status.get("result", "unknown"))
    blockers = status.get("blockers") if isinstance(status.get("blockers"), list) else []
    repo = status.get("repository") if isinstance(status.get("repository"), dict) else {}
    bucket = repo.get("bucket") or "no-bucket"
    prefix = repo.get("prefix") or "no-prefix"
    detail = f"{result}: blockers={len(blockers)}, repo={bucket}/{prefix}{age_note}"

    if result == "success":
        if age is not None and age > 24:
            doctor.warn("Control-plane restic backup", f"{detail}; stale", "backup")
        else:
            doctor.ok("Control-plane restic backup", detail, "backup")
    elif result == "dry-run-ok":
        doctor.warn("Control-plane restic backup", f"{detail}; dry-run only, real backup still required", "backup")
    else:
        doctor.warn("Control-plane restic backup", detail, "backup")


def check_control_plane_runtime_dashboard(doctor: Doctor) -> None:
    status, age = runtime_dashboard_status()
    if not isinstance(status, dict):
        doctor.warn(
            "Control-plane runtime dashboard",
            "missing; run control-plane-runtime-dashboard",
            "runtime",
        )
        return

    age_note = f", {age:.1f}h old" if age is not None else ""
    result = str(status.get("result", "unknown"))
    tmux = status.get("tmux") if isinstance(status.get("tmux"), dict) else {}
    provider_count = tmux.get("provider_worker_count", "?")
    cleanup_count = tmux.get("cleanup_candidate_count", "?")
    detail = f"{result}: providers={provider_count}, cleanup={cleanup_count}{age_note}"
    if age is not None and age > 2:
        doctor.warn("Control-plane runtime dashboard", f"{detail}; stale", "runtime")
    elif result == "blocked":
        doctor.warn("Control-plane runtime dashboard", detail, "runtime")
    else:
        doctor.ok("Control-plane runtime dashboard", detail, "runtime")


def check_can_ops_brief(doctor: Doctor) -> None:
    status = read_json(CAN_OPS_BRIEF_STATUS)
    if not isinstance(status, dict):
        doctor.warn("Can ops brief", "missing; run can-ops-brief --refresh", "operations")
        return

    age = age_hours(status.get("updated_at"))
    age_note = f", {age:.1f}h old" if age is not None else ""
    result = str(status.get("result", "unknown"))
    summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
    priorities = status.get("top_priorities") if isinstance(status.get("top_priorities"), list) else []
    detail = (
        f"{result}: priorities={len(priorities)}, "
        f"doctor={summary.get('can_doctor_result', 'unknown')}, "
        f"backup={summary.get('backup_readiness_result', 'unknown')}, "
        f"restic={summary.get('restic_backup_result', 'unknown')}{age_note}"
    )
    if age is not None and age > 12:
        doctor.warn("Can ops brief", f"{detail}; stale", "operations")
    else:
        doctor.ok("Can ops brief", detail, "operations")


def check_can_ops_refresh(doctor: Doctor) -> None:
    status = read_json(CAN_OPS_REFRESH_STATUS)
    if not isinstance(status, dict):
        doctor.warn("Can ops refresh", "missing; run can-ops-refresh", "operations")
        return

    age = age_hours(status.get("updated_at"))
    age_note = f", {age:.1f}h old" if age is not None else ""
    result = str(status.get("result", "unknown"))
    brief = status.get("brief") if isinstance(status.get("brief"), dict) else {}
    command = status.get("command") if isinstance(status.get("command"), dict) else {}
    duration = command.get("duration_seconds", "?")
    detail = f"{result}: brief={brief.get('result', 'unknown')}, priorities={brief.get('top_priority_count', '?')}, duration={duration}s{age_note}"

    if age is not None and age > 12:
        doctor.warn("Can ops refresh", f"{detail}; stale", "operations")
    elif result in {"success", "warn", "skipped"}:
        doctor.ok("Can ops refresh", detail, "operations")
    else:
        doctor.warn("Can ops refresh", detail, "operations")


def check_can_ops_scheduler(doctor: Doctor) -> None:
    status = read_json(CAN_OPS_SCHEDULER_STATUS)
    if not isinstance(status, dict):
        doctor.warn("Can ops scheduler", "missing; run can-ops-scheduler start", "operations")
        return

    age = age_hours(status.get("updated_at"))
    age_note = f", {age:.1f}h old" if age is not None else ""
    result = str(status.get("result", "unknown"))
    mode = str(status.get("mode", "unknown"))
    note = str(status.get("note", ""))
    tmux_active = bool(status.get("tmux_active"))
    systemd_active = bool(status.get("systemd_timer_active"))
    detail = f"{result}: mode={mode}, tmux={tmux_active}, systemd={systemd_active}, {note}{age_note}"

    if age is not None and age > 12:
        doctor.warn("Can ops scheduler", f"{detail}; stale", "operations")
    elif result == "success":
        doctor.ok("Can ops scheduler", detail, "operations")
    else:
        doctor.warn("Can ops scheduler", detail, "operations")


def check_tmux_cleanup_review(doctor: Doctor) -> None:
    status = read_json(TMUX_CLEANUP_REVIEW_STATUS)
    if not isinstance(status, dict):
        doctor.warn("Tmux cleanup review", "missing; run tmux-cleanup-review", "runtime")
        return

    age = age_hours(status.get("updated_at"))
    age_note = f", {age:.1f}h old" if age is not None else ""
    result = str(status.get("result", "unknown"))
    summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
    detail = (
        f"{result}: candidates={summary.get('candidate_count', '?')}, "
        f"stop={summary.get('stop_candidate_count', '?')}, "
        f"high={summary.get('review_high_count', '?')}, "
        f"medium={summary.get('review_medium_count', '?')}{age_note}"
    )
    if age is not None and age > 24:
        doctor.warn("Tmux cleanup review", f"{detail}; stale", "runtime")
    elif result == "blocked":
        doctor.warn("Tmux cleanup review", detail, "runtime")
    else:
        doctor.ok("Tmux cleanup review", detail, "runtime")


def check_auth_and_remotes(doctor: Doctor) -> None:
    if shutil.which("gh"):
        gh = run(["gh", "auth", "status"], timeout=10)
        if gh.returncode == 0:
            doctor.ok("GitHub CLI", "authenticated", "auth")
        else:
            doctor.warn("GitHub CLI", "not authenticated", "auth")
    else:
        doctor.warn("GitHub CLI", "gh not installed", "auth")

    if shutil.which("rclone"):
        remotes = run(["rclone", "listremotes"], timeout=10)
        remote_names = remotes.stdout.splitlines() if remotes.returncode == 0 else []
        if "r2:" in remote_names:
            if os.environ.get("CAN_DOCTOR_R2_WRITE") == "1":
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=True) as temp:
                    temp.write("can-doctor r2 write check\n")
                    temp.flush()
                    write = run(
                        [
                            "rclone",
                            "copyto",
                            temp.name,
                            "r2:vm-backup/_smoke/can-doctor-write-check.txt",
                            "--no-update-modtime",
                        ],
                        timeout=20,
                    )
                if write.returncode == 0:
                    doctor.ok("Rclone R2 write", "smoke upload ok", "backup")
                else:
                    text = f"{write.stdout}\n{write.stderr}"
                    if "AccessDenied" in text:
                        detail = "AccessDenied during smoke upload"
                    elif "NotImplemented" in text:
                        detail = "NotImplemented during smoke upload"
                    else:
                        lines = text.strip().splitlines()
                        detail = lines[-1] if lines else "smoke upload failed"
                    doctor.warn("Rclone R2 write", detail, "backup")
            else:
                doctor.ok("Rclone R2 remote", "r2 configured; write smoke skipped unless CAN_DOCTOR_R2_WRITE=1", "backup")
        elif any("r2" in remote.lower() or "vm-backup" in remote.lower() for remote in remote_names):
            visible = ", ".join(remote_names[:5])
            doctor.warn("Rclone R2 remote", f"no active r2: remote; configured remotes: {visible}", "backup")
        else:
            doctor.warn("Rclone R2 remote", "r2 missing", "backup")
    else:
        doctor.warn("Rclone", "not installed", "backup")

    if shutil.which("obsidian"):
        files = run(["obsidian", "files"], timeout=10)
        text = (files.stdout or files.stderr).strip().replace("\n", "; ")
        if files.returncode == 0 and not text.startswith("Error:"):
            first = text.split("; ", 1)[0] if text else "available"
            doctor.ok("Obsidian CLI", f"reachable ({first})", "vault")
        else:
            doctor.warn("Obsidian CLI", text or "not reachable", "vault")
    else:
        doctor.warn("Obsidian CLI", "not installed", "vault")


def check_hetzner_access(doctor: Doctor) -> None:
    if os.environ.get("CAN_DOCTOR_SKIP_HETZNER_SSH") == "1":
        doctor.warn("Hetzner SSH", "skipped by CAN_DOCTOR_SKIP_HETZNER_SSH=1", "migration")
        return
    if not shutil.which("ssh"):
        doctor.warn("Hetzner SSH", "ssh not installed", "migration")
        return
    args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=6",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if HETZNER_KEY.exists():
        args.extend(["-o", "IdentitiesOnly=yes", "-i", str(HETZNER_KEY)])
    args.extend([HETZNER_TARGET, "true"])
    proc = run(args, timeout=10)
    if proc.returncode == 0:
        doctor.ok("Hetzner SSH", f"key-based login works for {HETZNER_TARGET}", "migration")
        return
    text = f"{proc.stdout}\n{proc.stderr}".strip().splitlines()
    detail = text[-1] if text else "ssh failed"
    doctor.warn("Hetzner SSH", f"{HETZNER_TARGET}: {detail}", "migration")


def check_hetzner_access_preflight(doctor: Doctor) -> None:
    status = read_json(HETZNER_ACCESS_PREFLIGHT_STATUS)
    if not isinstance(status, dict):
        doctor.warn("Hetzner access preflight", "missing; run hetzner-access-preflight", "migration")
        return

    age = age_hours(status.get("updated_at"))
    age_note = f", {age:.1f}h old" if age is not None else ""
    result = str(status.get("result", "unknown"))
    target = status.get("target") if isinstance(status.get("target"), dict) else {}
    key = status.get("key") if isinstance(status.get("key"), dict) else {}
    auth = status.get("auth") if isinstance(status.get("auth"), dict) else {}
    explicit = auth.get("explicit_key") if isinstance(auth.get("explicit_key"), dict) else {}
    detail = (
        f"{result}: target={target.get('raw', HETZNER_TARGET)}, "
        f"tcp={status.get('tcp', {}).get('reachable', '?') if isinstance(status.get('tcp'), dict) else '?'}, "
        f"ssh={explicit.get('ok', '?')}, "
        f"key={key.get('public_key_fingerprint', '')}{age_note}"
    )
    if age is not None and age > 24:
        doctor.warn("Hetzner access preflight", f"{detail}; stale", "migration")
    elif result == "ready":
        doctor.ok("Hetzner access preflight", detail, "migration")
    else:
        doctor.warn("Hetzner access preflight", detail, "migration")


def check_hetzner_hardening_preflight(doctor: Doctor) -> None:
    status = read_json(HETZNER_HARDENING_PREFLIGHT_STATUS)
    if not isinstance(status, dict):
        doctor.warn("Hetzner hardening preflight", "missing; run hetzner-hardening-preflight", "migration")
        return

    age = age_hours(status.get("updated_at"))
    age_note = f", {age:.1f}h old" if age is not None else ""
    result = str(status.get("result", "unknown"))
    blockers = status.get("blockers") if isinstance(status.get("blockers"), list) else []
    warnings = status.get("warnings") if isinstance(status.get("warnings"), list) else []
    remote = status.get("remote") if isinstance(status.get("remote"), dict) else {}
    docker = remote.get("docker") if isinstance(remote.get("docker"), dict) else {}
    disk = remote.get("disk") if isinstance(remote.get("disk"), dict) else {}
    services = remote.get("services") if isinstance(remote.get("services"), dict) else {}
    detail = (
        f"{result}: blockers={len(blockers)}, warnings={len(warnings)}, "
        f"host={remote.get('hostname', 'unknown')}, "
        f"docker={services.get('docker', 'unknown')}, "
        f"containers={docker.get('container_count', '?')}, "
        f"disk={disk.get('used_percent', '?')}%{age_note}"
    )
    if age is not None and age > 24:
        doctor.warn("Hetzner hardening preflight", f"{detail}; stale", "migration")
    elif result == "ready":
        doctor.ok("Hetzner hardening preflight", detail, "migration")
    else:
        next_action = str(status.get("next_action", "review Hetzner hardening report"))
        doctor.warn("Hetzner hardening preflight", f"{detail}; {next_action}", "migration")


def render_summary(payload: dict[str, Any]) -> None:
    result = payload["result"]
    if result == "fail":
        print(f"Result: fail ({payload['failures']} failures, {payload['warnings']} warnings)")
    elif result == "warn":
        print(f"Result: warn ({payload['warnings']} warnings)")
    else:
        print("Result: ok")
    print(f"Status file: {STATUS_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Can workspace and migration health check")
    parser.add_argument("--json", action="store_true", help="print JSON status instead of text")
    args = parser.parse_args()

    doctor = Doctor(json_mode=args.json)
    if not args.json:
        print("can-doctor: VM/control-plane health check")
        print("No secret values are printed.")
        print("")

    check_system(doctor)
    check_vault(doctor)
    check_migration_docs(doctor)
    check_vault_guard(doctor)
    check_tmux(doctor)
    check_control_plane_runtime_dashboard(doctor)
    check_tmux_cleanup_review(doctor)
    check_backup_status(doctor)
    check_control_plane_backup_readiness(doctor)
    check_control_plane_restic_backup(doctor)
    check_can_ops_brief(doctor)
    check_can_ops_refresh(doctor)
    check_can_ops_scheduler(doctor)
    check_auth_and_remotes(doctor)
    check_hetzner_access(doctor)
    check_hetzner_access_preflight(doctor)
    check_hetzner_hardening_preflight(doctor)

    payload = doctor.payload()
    write_json_atomic(STATUS_PATH, payload)
    append_jsonl(HISTORY_PATH, payload)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("")
        render_summary(payload)

    return 1 if doctor.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

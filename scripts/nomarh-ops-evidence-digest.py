#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import socket
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
VAULT = HOME / "Can"
DAILY_DIR = VAULT / "daily notes"
INFRA_DIR = VAULT / "infrastructure"
STATE_DIR = HOME / ".local/state/nomarh-ops-evidence-digest"
STATUS_PATH = STATE_DIR / "status.json"
REPORT_PATH = STATE_DIR / "digest.md"

NOMARH_OPS_STATUS = HOME / ".local/state/nomarh-ops/status.json"
MIGRATION_STATE_MANIFEST_STATUS = HOME / ".local/state/nomarh-migration-state-manifest/manifest.json"
ACTION_PACK_STATUS = HOME / ".local/state/nomarh-action-pack/status.json"
TMUX_CLEANUP_STATUS = HOME / ".local/state/tmux-cleanup-review/status.json"
SECRET_ROTATION_STATUS = HOME / ".local/state/nomarh-secret-rotation-plan/status.json"

DATE_RE = re.compile(r"^(20\d\d-\d\d-\d\d)\.md$")
SECRET_RE = re.compile(
    r"cfut_[A-Za-z0-9_]+|"
    r"-----BEGIN (?:OPENSSH|RSA|EC|PRIVATE) KEY-----|"
    r"AKIA[0-9A-Z]{16}|"
    r"AIza[0-9A-Za-z_-]{20,}|"
    r"xox[baprs]-[0-9A-Za-z-]{20,}|"
    r"gh[pousr]_[0-9A-Za-z_]{20,}|"
    r"sk-[A-Za-z0-9]{32,}"
)

THEMES: dict[str, list[str]] = {
    "tmux_runtime": ["tmux", "session", "pane"],
    "coder_workspace": ["coder", "workspace", "vnc", "novnc"],
    "vault_obsidian": ["vault", "obsidian", "daily note", "sync"],
    "backup_restore": ["backup", "restic", "restore", "snapshot", "r2"],
    "cloudflare_edge": ["cloudflare", "worker", "access", "dns", "r2", "zero trust"],
    "mail": ["mail", "mailcow", "smtp", "imap", "mx", "dkim", "dmarc", "spf"],
    "security_access": ["secret", "token", "ssh", "firewall", "ufw", "hardening", "passkey", "otp"],
    "providers_workers": ["aws", "hetzner", "salad", "clore", "gpu", "provider", "worker"],
    "observability": ["health", "status", "monitor", "dashboard", "doctor", "scheduler"],
    "incidents_repairs": ["blocker", "failed", "failure", "error", "oom", "memory pressure", "corrupt", "repair"],
}


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


def dict_get(payload: Any, key: str, default: Any = None) -> Any:
    return payload.get(key, default) if isinstance(payload, dict) else default


def int_get(payload: Any, key: str) -> int:
    try:
        return int(dict_get(payload, key, 0) or 0)
    except Exception:
        return 0


def safe_md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def daily_files(window_start: date, window_end: date) -> list[tuple[date, Path]]:
    items: list[tuple[date, Path]] = []
    if not DAILY_DIR.exists():
        return items
    for path in sorted(DAILY_DIR.glob("20??-??-??.md")):
        match = DATE_RE.match(path.name)
        if not match:
            continue
        item_date = parse_day(match.group(1))
        if window_start <= item_date <= window_end:
            items.append((item_date, path))
    return items


def expected_dates(window_start: date, window_end: date) -> list[date]:
    days = (window_end - window_start).days
    return [window_start + timedelta(days=offset) for offset in range(days + 1)]


def note_themes(text: str) -> list[str]:
    lowered = text.lower()
    hits: list[str] = []
    for theme, keywords in THEMES.items():
        if any(keyword in lowered for keyword in keywords):
            hits.append(theme)
    return hits


def secret_like_count(text: str) -> int:
    return len(SECRET_RE.findall(text))


def infra_docs() -> list[str]:
    if not INFRA_DIR.exists():
        return []
    names: list[str] = []
    for path in sorted(INFRA_DIR.glob("*.md")):
        lowered = path.name.lower()
        if any(term in lowered for term in ["nomarh", "hetzner", "ops", "control plane", "migration", "r2", "restic"]):
            names.append(path.name)
    return names


def build_recommendations(theme_counts: dict[str, int], current: dict[str, Any]) -> list[dict[str, str]]:
    backup_count = theme_counts.get("backup_restore", 0)
    tmux_count = theme_counts.get("tmux_runtime", 0)
    security_count = theme_counts.get("security_access", 0)
    mail_count = theme_counts.get("mail", 0)
    cloudflare_count = theme_counts.get("cloudflare_edge", 0)
    observability_count = theme_counts.get("observability", 0)

    action_summary = dict_get(dict_get(current, "action_pack", {}), "summary", {})
    manifest_summary = dict_get(dict_get(current, "migration_state_manifest", {}), "summary", {})

    return [
        {
            "lane": "P0 backup",
            "title": "Finish R2/restic backup and restore gate",
            "why": f"Backup/restore appears in {backup_count} recent daily notes and the migration manifest still has {int_get(manifest_summary, 'blocker_count')} blocker(s).",
            "next_action": "Provide scoped R2/restic inputs through the secure path, configure active r2:, run real backup, then run restore drill.",
            "verify": "nomarh-ops --refresh --json",
        },
        {
            "lane": "P0 runtime",
            "title": "Convert durable tmux loops into supervised services",
            "why": f"tmux appears in {tmux_count} recent daily notes and action pack has {int_get(action_summary, 'safe_review_count')} safe review(s).",
            "next_action": "Review tmux-cleanup-review and supervision unit bundle; install only reviewed guarded units.",
            "verify": "nomarh-supervision-unit-bundle --json",
        },
        {
            "lane": "P0 security",
            "title": "Keep secret and access handling separate from notes",
            "why": f"Security/access appears in {security_count} recent daily notes; Cloudflare/API/SSH workflows recur often.",
            "next_action": "Use scoped tokens, secure env files, and rotation logs; never paste raw values into vault or tmux output.",
            "verify": "nomarh-secret-rotation-plan --json",
        },
        {
            "lane": "P1 daily ops",
            "title": "Make nomarh-ops the only morning entrypoint",
            "why": f"Observability/status appears in {observability_count} recent daily notes, showing repeated manual status gathering.",
            "next_action": "Run nomarh-ops first, then only drill into the named blocker or safe review.",
            "verify": "nomarh-ops --refresh --json",
        },
        {
            "lane": "P2 mail",
            "title": "Treat mail as a separate production gate",
            "why": f"Mail appears in {mail_count} recent daily notes and Cloudflare/edge appears in {cloudflare_count}; mail protocols cannot be hidden behind Cloudflare Access.",
            "next_action": "Keep IMAP/SMTP DNS-only, protect admin/browser surfaces with Access, and delay MX cutover until delivery tests pass.",
            "verify": "nomarh-cutover-guard --json",
        },
    ]


def build_payload(days: int, today: date) -> dict[str, Any]:
    window_end = today
    window_start = today - timedelta(days=days - 1)
    files = daily_files(window_start, window_end)
    present_dates = {item_date for item_date, _ in files}
    missing_dates = [item.isoformat() for item in expected_dates(window_start, window_end) if item not in present_dates]

    theme_counts = {theme: 0 for theme in THEMES}
    date_index: list[dict[str, Any]] = []
    risky_secret_pattern_files: list[str] = []
    total_heading_count = 0

    for item_date, path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            text = ""
        themes = note_themes(text)
        for theme in themes:
            theme_counts[theme] += 1
        heading_count = sum(1 for line in text.splitlines() if line.startswith("#"))
        total_heading_count += heading_count
        if secret_like_count(text):
            risky_secret_pattern_files.append(path.name)
        date_index.append(
            {
                "date": item_date.isoformat(),
                "theme_count": len(themes),
                "themes": themes,
                "heading_count": heading_count,
            }
        )

    top_themes = [
        {"theme": theme, "daily_note_count": count}
        for theme, count in sorted(theme_counts.items(), key=lambda item: (-item[1], item[0]))
        if count
    ]
    docs = infra_docs()
    current = {
        "nomarh_ops": read_json(NOMARH_OPS_STATUS),
        "migration_state_manifest": read_json(MIGRATION_STATE_MANIFEST_STATUS),
        "action_pack": read_json(ACTION_PACK_STATUS),
        "tmux_cleanup": read_json(TMUX_CLEANUP_STATUS),
        "secret_rotation": read_json(SECRET_ROTATION_STATUS),
    }
    recommendations = build_recommendations(theme_counts, current)
    result = "blocked" if not files else "warn" if missing_dates or risky_secret_pattern_files else "ready"

    return {
        "schema": "nomarh-ops-evidence-digest.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "window": {
            "days": days,
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
        },
        "summary": {
            "daily_note_count": len(files),
            "missing_day_count": len(missing_dates),
            "total_heading_count": total_heading_count,
            "infrastructure_doc_count": len(docs),
            "secret_pattern_file_count": len(risky_secret_pattern_files),
            "top_themes": top_themes[:8],
            "nomarh_ops_result": dict_get(current["nomarh_ops"], "result", "missing"),
            "migration_state_manifest_result": dict_get(current["migration_state_manifest"], "result", "missing"),
            "action_pack_result": dict_get(current["action_pack"], "result", "missing"),
            "tmux_cleanup_result": dict_get(current["tmux_cleanup"], "result", "missing"),
            "secret_rotation_result": dict_get(current["secret_rotation"], "result", "missing"),
        },
        "theme_counts": theme_counts,
        "date_index": date_index,
        "missing_dates": missing_dates,
        "secret_pattern_files": risky_secret_pattern_files,
        "infrastructure_docs": docs,
        "recommendations": recommendations,
        "paths": {
            "status": str(STATUS_PATH),
            "report": str(REPORT_PATH),
            "daily_notes": str(DAILY_DIR),
            "infrastructure": str(INFRA_DIR),
            "nomarh_ops": str(NOMARH_OPS_STATUS),
            "migration_state_manifest": str(MIGRATION_STATE_MANIFEST_STATUS),
            "action_pack": str(ACTION_PACK_STATUS),
            "tmux_cleanup": str(TMUX_CLEANUP_STATUS),
            "secret_rotation": str(SECRET_ROTATION_STATUS),
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    window = payload["window"]
    lines = [
        "# Nomarh Ops Evidence Digest",
        "",
        "This no-secret digest reads daily note files and existing status JSON. It prints counts, themes, and recommendations, not raw credential values or long logs.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Window: `{window['start']}` to `{window['end']}`",
        f"- Daily notes: `{summary['daily_note_count']}`",
        f"- Missing calendar days: `{summary['missing_day_count']}`",
        f"- Infrastructure docs indexed: `{summary['infrastructure_doc_count']}`",
        f"- Secret-pattern daily files: `{summary['secret_pattern_file_count']}`",
        "",
        "## Current Status Sources",
        "",
        f"- `nomarh-ops`: `{safe_md(summary['nomarh_ops_result'])}`",
        f"- `migration-state-manifest`: `{safe_md(summary['migration_state_manifest_result'])}`",
        f"- `action-pack`: `{safe_md(summary['action_pack_result'])}`",
        f"- `tmux-cleanup`: `{safe_md(summary['tmux_cleanup_result'])}`",
        f"- `secret-rotation`: `{safe_md(summary['secret_rotation_result'])}`",
        "",
        "## Top Themes",
        "",
        "| Theme | Daily notes |",
        "|---|---:|",
    ]
    for item in summary["top_themes"]:
        lines.append(f"| `{safe_md(item['theme'])}` | {safe_md(item['daily_note_count'])} |")

    lines.extend(["", "## Recommendations", "", "| Lane | Title | Why | Verify |", "|---|---|---|---|"])
    for item in payload["recommendations"]:
        lines.append(
            f"| `{safe_md(item['lane'])}` | {safe_md(item['title'])} | {safe_md(item['why'])} | `{safe_md(item['verify'])}` |"
        )

    lines.extend(["", "## Missing Dates", ""])
    if payload["missing_dates"]:
        lines.append(", ".join(f"`{safe_md(item)}`" for item in payload["missing_dates"]))
    else:
        lines.append("No missing dates in the scanned window.")

    if payload["secret_pattern_files"]:
        lines.extend(["", "## Secret Pattern Attention", ""])
        lines.append("These daily files matched high-confidence secret patterns and should be reviewed/rotated without printing values:")
        lines.extend(f"- `{safe_md(item)}`" for item in payload["secret_pattern_files"])

    lines.extend(["", "## Infrastructure Docs Indexed", ""])
    for name in payload["infrastructure_docs"][:40]:
        lines.append(f"- `{safe_md(name)}`")

    lines.extend(["", "## Source Paths", ""])
    for key, path in payload["paths"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate no-secret evidence digest from recent Nomarh daily notes")
    parser.add_argument("--days", type=int, default=60, help="calendar days to scan")
    parser.add_argument("--today", help="override window end date as YYYY-MM-DD")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.days < 1:
        raise SystemExit("--days must be at least 1")
    today = parse_day(args.today) if args.today else datetime.now(timezone.utc).date()
    payload = build_payload(args.days, today)
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Nomarh ops evidence digest")
        print(f"Result: {payload['result']}")
        print(f"Daily notes: {payload['summary']['daily_note_count']}")
        print(f"Report: {REPORT_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

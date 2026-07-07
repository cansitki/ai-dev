#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-service-migration-map"
STATUS_PATH = STATE_DIR / "map.json"
REPORT_PATH = STATE_DIR / "map.md"
TMUX_INVENTORY_PATH = HOME / ".local/state/can-doctor/tmux-inventory.json"
RUNTIME_DASHBOARD_STATUS = HOME / ".local/state/control-plane-runtime-dashboard/status.json"
READINESS_STATUS = HOME / ".local/state/nomarh-migration-readiness/readiness.json"

CRITICAL_TARGETS = {
    "bot": {
        "priority": "P0",
        "target_model": "systemd service",
        "risk": "high",
        "action": "Migrate as a supervised service only after secrets, owner, and access policy are reviewed.",
    },
    "can-ops-refresh-loop": {
        "priority": "P0",
        "target_model": "systemd user timer",
        "risk": "medium",
        "action": "Replace tmux fallback with `can-ops-scheduler install-systemd --interval 1800` on Hetzner.",
    },
    "github-repo-sweep": {
        "priority": "P1",
        "target_model": "systemd timer",
        "risk": "medium",
        "action": "Run as a bounded timer with persistent status and no pane output dependency.",
    },
    "novnc": {
        "priority": "P2",
        "target_model": "review or Cloudflare Access protected service",
        "risk": "high",
        "action": "Keep only if mobile/browser access is still needed; protect with Cloudflare Access or retire.",
    },
    "obsidian-headless": {
        "priority": "P1",
        "target_model": "systemd service or retire",
        "risk": "medium",
        "action": "Decide whether headless Obsidian is still required after sync/backup migration; supervise if kept.",
    },
    "tmux-theme-sync": {
        "priority": "P3",
        "target_model": "systemd timer or retire",
        "risk": "low",
        "action": "Convert to a timer only if VM theme sync remains useful after Hetzner cutover.",
    },
    "ttyd": {
        "priority": "P2",
        "target_model": "review or retire",
        "risk": "high",
        "action": "Avoid public terminal exposure; keep only behind Cloudflare Access or retire.",
    },
    "vault-backup": {
        "priority": "P0",
        "target_model": "restic/systemd timer",
        "risk": "high",
        "action": "Replace raw backup flow with scoped restic backup and restore drill.",
    },
}

EXPECTED_TARGETS: dict[str, dict[str, str]] = {}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


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


def group_for_session(name: str, path: str) -> str:
    lowered = name.lower()
    path_lower = path.lower()
    if lowered.startswith("salad-") or "/salad" in path_lower:
        return "salad"
    if lowered.startswith("prlcompute") or "prlcompute" in path_lower:
        return "prlcompute"
    if lowered.startswith("clore-") or "clore" in path_lower:
        return "clore"
    if lowered.startswith("provider-"):
        return "provider-gateway"
    if lowered.startswith("main"):
        return "main-work"
    return lowered.split("-", 1)[0] if "-" in lowered else lowered


def provider_target(group: str) -> dict[str, str]:
    if group == "salad":
        return {
            "priority": "P2",
            "target_model": "project supervisor service",
            "risk": "medium",
            "action": "Collapse many Salad tmux loops into one supervised orchestrator with explicit stop conditions.",
        }
    if group in {"prlcompute", "clore"}:
        return {
            "priority": "P2",
            "target_model": "project service plus timer",
            "risk": "medium",
            "action": "Keep only profitable/current monitors; supervise active ones and retire stale watchers.",
        }
    if group == "provider-gateway":
        return {
            "priority": "P1",
            "target_model": "systemd service",
            "risk": "high",
            "action": "Audit provider gateway/key broker before migration; never expose raw keys.",
        }
    return {
        "priority": "P3",
        "target_model": "review",
        "risk": "medium",
        "action": "Review owner and business value before migrating.",
    }


def project_target(session: dict[str, Any], cleanup_names: set[str]) -> dict[str, str]:
    name = str(session.get("name", ""))
    command = str(session.get("command", ""))
    if name in cleanup_names:
        return {
            "priority": "P3",
            "target_model": "review/archive",
            "risk": "medium",
            "action": "Review dirty state and archive or stop before copying runtime state.",
        }
    if command in {"node", "npm"}:
        return {
            "priority": "P2",
            "target_model": "project service or manual workspace",
            "risk": "medium",
            "action": "Decide whether this is a real service or only an active development session.",
        }
    return {
        "priority": "P3",
        "target_model": "manual workspace",
        "risk": "low",
        "action": "Do not migrate as always-on unless there is an owner and uptime requirement.",
    }


def sensitive_target(session: dict[str, Any]) -> dict[str, str]:
    return {
        "priority": "P1",
        "target_model": "ephemeral secure intake",
        "risk": "high",
        "action": "Do not migrate as a persistent tmux loop; replace with audited secure intake and cleanup.",
    }


def classify_session(session: dict[str, Any], cleanup_names: set[str]) -> dict[str, Any]:
    name = str(session.get("name", ""))
    category = str(session.get("category", ""))
    path = str(session.get("path", ""))
    if category == "critical":
        target = CRITICAL_TARGETS.get(
            name,
            {
                "priority": "P1",
                "target_model": "systemd service",
                "risk": "medium",
                "action": "Review and supervise as a named service if still required.",
            },
        )
    elif category == "expected_missing_or_disabled":
        target = EXPECTED_TARGETS.get(
            name,
            {
                "priority": "P2",
                "target_model": "review",
                "risk": "medium",
                "action": "Confirm whether this expected service should run on Hetzner.",
            },
        )
    elif category == "provider_worker":
        target = provider_target(group_for_session(name, path))
    elif category == "project_work":
        target = project_target(session, cleanup_names)
    elif category == "sensitive":
        target = sensitive_target(session)
    else:
        target = {
            "priority": "P3",
            "target_model": "review",
            "risk": "medium",
            "action": "Review manually before migration.",
        }

    return {
        "name": name,
        "category": category,
        "group": group_for_session(name, path),
        "current": {
            "command": str(session.get("command", "")),
            "path": path,
            "age_days": session.get("age_days"),
            "attached": session.get("attached"),
        },
        "priority": target["priority"],
        "target_model": target["target_model"],
        "risk": target["risk"],
        "action": target["action"],
    }


def missing_expected_items(missing: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for name in missing:
        target = EXPECTED_TARGETS.get(
            name,
            {
                "priority": "P2",
                "target_model": "review",
                "risk": "medium",
                "action": "Confirm whether this expected service should exist on Hetzner.",
            },
        )
        items.append(
            {
                "name": name,
                "category": "missing_expected",
                "group": group_for_session(name, ""),
                "current": {"command": "", "path": "", "age_days": None, "attached": 0},
                "priority": target["priority"],
                "target_model": target["target_model"],
                "risk": target["risk"],
                "action": target["action"],
            }
        )
    return items


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    by_priority: dict[str, int] = {}
    by_model: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for item in items:
        by_priority[item["priority"]] = by_priority.get(item["priority"], 0) + 1
        by_model[item["target_model"]] = by_model.get(item["target_model"], 0) + 1
        by_risk[item["risk"]] = by_risk.get(item["risk"], 0) + 1
        by_category[item["category"]] = by_category.get(item["category"], 0) + 1
    return {
        "total_items": len(items),
        "by_priority": dict(sorted(by_priority.items())),
        "by_model": dict(sorted(by_model.items())),
        "by_risk": dict(sorted(by_risk.items())),
        "by_category": dict(sorted(by_category.items())),
    }


def build_payload() -> dict[str, Any]:
    inventory = read_json(TMUX_INVENTORY_PATH)
    runtime = read_json(RUNTIME_DASHBOARD_STATUS)
    readiness = read_json(READINESS_STATUS)
    blockers: list[str] = []
    warnings: list[str] = []

    if not isinstance(inventory, dict):
        blockers.append(f"tmux inventory missing or invalid: {TMUX_INVENTORY_PATH}")
        sessions: list[dict[str, Any]] = []
        cleanup_names: set[str] = set()
        missing: list[str] = []
    else:
        sessions = [item for item in inventory.get("sessions", []) if isinstance(item, dict)]
        cleanup = inventory.get("cleanup_candidates") if isinstance(inventory.get("cleanup_candidates"), list) else []
        cleanup_names = {str(item.get("name", "")) for item in cleanup if isinstance(item, dict)}
        missing = [str(item) for item in inventory.get("missing_expected", []) if str(item)]

    items = [classify_session(session, cleanup_names) for session in sessions]
    items.extend(missing_expected_items(missing))

    summary = summarize(items)
    p0_items = [item for item in items if item["priority"] == "P0"]
    high_risk = [item for item in items if item["risk"] == "high"]
    review_or_archive = [item for item in items if item["target_model"] in {"review/archive", "review", "retired"}]

    if p0_items:
        warnings.append(f"{len(p0_items)} P0 service migration item(s) need explicit owner/model before cutover")
    if high_risk:
        warnings.append(f"{len(high_risk)} high-risk service item(s) require access/secret review")
    if review_or_archive:
        warnings.append(f"{len(review_or_archive)} item(s) should be reviewed, archived, retired, or explicitly kept")

    runtime_summary = runtime.get("tmux") if isinstance(runtime, dict) and isinstance(runtime.get("tmux"), dict) else {}
    readiness_summary = readiness.get("summary") if isinstance(readiness, dict) and isinstance(readiness.get("summary"), dict) else {}

    result = "blocked" if blockers else "warn" if warnings else "ready"
    next_actions = [
        "Assign owners and target model for all P0 items before AWS/main cutover.",
        "Convert ops refresh, vault backup, repo sweep, and critical services from tmux to systemd services/timers on Hetzner.",
        "Review high-risk browser/terminal/secret-intake services before exposing them on Hetzner.",
        "Archive or stop cleanup candidates before copying runtime state.",
        "Use scoped restic backup and restore drills for durable workspace state.",
    ]

    return {
        "schema": "nomarh-service-migration-map.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "blockers": blockers,
        "warnings": warnings,
        "summary": summary,
        "runtime_context": {
            "tmux_total": runtime_summary.get("total"),
            "provider_worker_count": runtime_summary.get("provider_worker_count"),
            "cleanup_candidate_count": runtime_summary.get("cleanup_candidate_count"),
            "readiness_result": readiness.get("result") if isinstance(readiness, dict) else "missing",
            "readiness_blocked_gates": readiness_summary.get("blocked"),
            "readiness_warn_gates": readiness_summary.get("warn"),
        },
        "items": sorted(items, key=lambda item: (item["priority"], item["category"], item["name"])),
        "next_actions": next_actions,
        "paths": {"status": str(STATUS_PATH), "report": str(REPORT_PATH)},
        "sources": {
            "tmux_inventory": str(TMUX_INVENTORY_PATH),
            "runtime_dashboard": str(RUNTIME_DASHBOARD_STATUS),
            "migration_readiness": str(READINESS_STATUS),
        },
    }


def safe_md(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Nomarh Service Migration Map",
        "",
        "No secrets, tmux pane output, env files, or mailbox contents are read. This map is generated from existing status JSON only.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Items: {summary['total_items']}",
        f"- Priority counts: `{safe_md(summary['by_priority'])}`",
        f"- Risk counts: `{safe_md(summary['by_risk'])}`",
        "",
    ]
    if payload["warnings"]:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["warnings"])
        lines.append("")

    lines.extend(["## P0/P1 Items", "", "| Name | Category | Target | Risk | Action |", "|---|---|---|---|---|"])
    for item in payload["items"]:
        if item["priority"] not in {"P0", "P1"}:
            continue
        lines.append(
            f"| `{safe_md(item['name'])}` | `{safe_md(item['category'])}` | `{safe_md(item['target_model'])}` | `{safe_md(item['risk'])}` | {safe_md(item['action'])} |"
        )

    lines.extend(["", "## Review And Archive Items", "", "| Name | Priority | Category | Target | Action |", "|---|---|---|---|---|"])
    for item in payload["items"]:
        if item["target_model"] not in {"review/archive", "review", "retired"}:
            continue
        lines.append(
            f"| `{safe_md(item['name'])}` | `{safe_md(item['priority'])}` | `{safe_md(item['category'])}` | `{safe_md(item['target_model'])}` | {safe_md(item['action'])} |"
        )

    lines.extend(["", "## Target Model Counts", "", "| Target Model | Count |", "|---|---:|"])
    for model, count in summary["by_model"].items():
        lines.append(f"| `{safe_md(model)}` | {count} |")

    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"{idx}. {safe_md(action)}" for idx, action in enumerate(payload["next_actions"], start=1))

    lines.extend(["", "## Sources", ""])
    for key, path in payload["sources"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate no-secret service migration map from current VM inventory")
    parser.add_argument("--json", action="store_true", help="print JSON payload")
    args = parser.parse_args()

    payload = build_payload()
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        summary = payload["summary"]
        print("Nomarh service migration map")
        print(f"Result: {payload['result']}")
        print(f"Items: {summary['total_items']}")
        print(f"Status: {STATUS_PATH}")
        print(f"Report: {REPORT_PATH}")
    return 1 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

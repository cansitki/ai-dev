#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-runtime-stabilization-board"
STATUS_PATH = STATE_DIR / "status.json"
BOARD_PATH = STATE_DIR / "board.md"

TMUX_CLEANUP_STATUS = HOME / ".local/state/tmux-cleanup-review/status.json"
SUPERVISION_PLAN_STATUS = HOME / ".local/state/nomarh-supervision-plan/plan.json"
SUPERVISION_UNIT_BUNDLE_STATUS = HOME / ".local/state/nomarh-supervision-unit-bundle/status.json"
OPS_EVIDENCE_DIGEST_STATUS = HOME / ".local/state/nomarh-ops-evidence-digest/status.json"


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


def list_get(payload: Any, key: str) -> list[Any]:
    value = dict_get(payload, key, [])
    return value if isinstance(value, list) else []


def int_get(payload: Any, key: str) -> int:
    try:
        return int(dict_get(payload, key, 0) or 0)
    except Exception:
        return 0


def safe_md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def action(
    action_id: str,
    lane: str,
    title: str,
    status: str,
    kind: str,
    next_action: str,
    verify: str,
    source: Path | str,
    reason: str,
    priority: str = "",
    risk: str = "",
) -> dict[str, Any]:
    return {
        "id": action_id,
        "lane": lane,
        "title": title,
        "status": status,
        "kind": kind,
        "next_action": next_action,
        "verify": verify,
        "source": str(source),
        "reason": reason,
        "priority": priority,
        "risk": risk,
    }


def session_id(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-") or "session"


def tmux_actions(cleanup: Any) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for item in list_get(cleanup, "reviews"):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "unknown"))
        path = str(item.get("path", ""))
        git = item.get("git") if isinstance(item.get("git"), dict) else {}
        risk = str(git.get("risk", "unknown"))
        dirty_count = git.get("dirty_count")
        verdict = str(item.get("verdict", "review"))
        age_days = item.get("age_days")
        if risk == "dirty":
            next_action = (
                f"Inspect git status for `{path}` and commit, stash, archive, or write a handoff before stopping `{name}`."
            )
        elif risk == "not-git":
            next_action = f"Inspect `{path}` and decide archive, retire, or migrate before stopping `{name}`."
        else:
            next_action = f"Review `{name}` manually before stopping or migrating it."
        reason = (
            f"{verdict}; age {age_days}d; command {item.get('command', '')}; attached {item.get('attached', '')}; "
            f"git risk {risk}; dirty {dirty_count}; {item.get('reason', '')}"
        )
        actions.append(
            action(
                f"tmux-{session_id(name)}",
                "tmux-handoff",
                f"Handoff tmux session `{name}`",
                verdict,
                "safe-local-review",
                next_action,
                "tmux-cleanup-review --json",
                TMUX_CLEANUP_STATUS,
                reason,
                risk=risk,
            )
        )
    return actions


def supervision_actions(supervision: Any, bundle: Any) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    bundle_plans = {str(item.get("name")): item for item in list_get(bundle, "plans") if isinstance(item, dict)}
    for plan in list_get(supervision, "plans"):
        if not isinstance(plan, dict):
            continue
        name = str(plan.get("name", "unknown"))
        status = str(plan.get("status", "pending"))
        priority = str(plan.get("priority", ""))
        risk = str(plan.get("risk", ""))
        target_model = str(plan.get("target_model", ""))
        decisions = [str(item) for item in plan.get("decisions", [])] if isinstance(plan.get("decisions"), list) else []
        blockers = [str(item) for item in plan.get("blockers", [])] if isinstance(plan.get("blockers"), list) else []
        unit_plan = bundle_plans.get(name, {})
        unit_count = len(unit_plan.get("generated_units", [])) if isinstance(unit_plan.get("generated_units"), list) else 0
        if status == "ready-to-spec":
            actions.append(
                action(
                    f"supervision-ready-{session_id(name)}",
                    "supervision",
                    f"Review ready systemd spec for `{name}`",
                    status,
                    "ready-local-spec",
                    "Review generated unit examples; install only with the reviewed supervision guard after host/user policy is settled.",
                    "nomarh-supervision-unit-bundle --json",
                    SUPERVISION_UNIT_BUNDLE_STATUS,
                    f"{priority}/{risk}; target {target_model}; generated units {unit_count}.",
                    priority=priority,
                    risk=risk,
                )
            )
        elif status == "pending-decision":
            actions.append(
                action(
                    f"supervision-decision-{session_id(name)}",
                    "supervision",
                    f"Decide runtime model for `{name}`",
                    status,
                    "decision-needed",
                    "; ".join(decisions) or "Choose supervise, retire, ephemeral one-shot, or keep manual before migration.",
                    "nomarh-supervision-plan --json",
                    SUPERVISION_PLAN_STATUS,
                    f"{priority}/{risk}; target {target_model}; generated units {unit_count}.",
                    priority=priority,
                    risk=risk,
                )
            )
        elif status == "blocked":
            actions.append(
                action(
                    f"supervision-blocked-{session_id(name)}",
                    "supervision",
                    f"Keep `{name}` blocked",
                    status,
                    "blocked-by-gate",
                    "Resolve the listed blocker(s) before creating or installing a durable timer/service.",
                    "nomarh-supervision-plan --json",
                    SUPERVISION_PLAN_STATUS,
                    "; ".join(blockers) or "blocked by supervision plan",
                    priority=priority,
                    risk=risk,
                )
            )
        elif status == "pending":
            actions.append(
                action(
                    f"supervision-pending-{session_id(name)}",
                    "supervision",
                    f"Decide whether to retire `{name}`",
                    status,
                    "decision-needed",
                    "Confirm whether this runtime is still required after backup/sync migration; retire or supervise deliberately.",
                    "nomarh-supervision-plan --json",
                    SUPERVISION_PLAN_STATUS,
                    f"{priority}/{risk}; target {target_model}.",
                    priority=priority,
                    risk=risk,
                )
            )
    return actions


def top_theme_count(evidence: Any, theme_name: str) -> int:
    summary = dict_get(evidence, "summary", {})
    for item in dict_get(summary, "top_themes", []):
        if isinstance(item, dict) and item.get("theme") == theme_name:
            return int_get(item, "daily_note_count")
    return 0


def build_payload() -> dict[str, Any]:
    cleanup = read_json(TMUX_CLEANUP_STATUS)
    supervision = read_json(SUPERVISION_PLAN_STATUS)
    bundle = read_json(SUPERVISION_UNIT_BUNDLE_STATUS)
    evidence = read_json(OPS_EVIDENCE_DIGEST_STATUS)

    blockers: list[str] = []
    for label, status, path in [
        ("tmux cleanup", cleanup, TMUX_CLEANUP_STATUS),
        ("supervision plan", supervision, SUPERVISION_PLAN_STATUS),
        ("supervision unit bundle", bundle, SUPERVISION_UNIT_BUNDLE_STATUS),
    ]:
        if not isinstance(status, dict):
            blockers.append(f"{label} status missing or invalid: {path}")

    cleanup_summary = dict_get(cleanup, "summary", {})
    supervision_summary = dict_get(supervision, "summary", {})
    bundle_summary = dict_get(bundle, "summary", {})

    tmux_review_actions = tmux_actions(cleanup)
    supervision_review_actions = supervision_actions(supervision, bundle)
    actions = tmux_review_actions + supervision_review_actions
    decision_actions = [item for item in actions if item["kind"] == "decision-needed"]
    ready_specs = [item for item in actions if item["kind"] == "ready-local-spec"]
    blocked_actions = [item for item in actions if item["kind"] == "blocked-by-gate"]
    dirty_project_actions = [item for item in tmux_review_actions if item.get("risk") == "dirty"]
    not_git_actions = [item for item in tmux_review_actions if item.get("risk") == "not-git"]

    result = "fail" if blockers else "warn" if actions else "ready"
    next_action = (
        "Resolve tmux handoffs and supervision decisions; do not stop sessions or install units automatically."
        if actions
        else "No runtime stabilization actions currently open."
    )
    return {
        "schema": "nomarh-runtime-stabilization-board.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "summary": {
            "action_count": len(actions),
            "tmux_review_count": len(tmux_review_actions),
            "tmux_review_high": int_get(cleanup_summary, "review_high_count"),
            "tmux_review_medium": int_get(cleanup_summary, "review_medium_count"),
            "tmux_stop_candidates": int_get(cleanup_summary, "stop_candidate_count"),
            "dirty_project_count": len(dirty_project_actions),
            "not_git_project_count": len(not_git_actions),
            "supervision_action_count": len(supervision_review_actions),
            "decision_needed_count": len(decision_actions),
            "ready_spec_count": len(ready_specs),
            "blocked_by_gate_count": len(blocked_actions),
            "supervision_plan_count": int_get(supervision_summary, "plan_count"),
            "supervision_pending_decision_count": int_get(bundle_summary, "pending_decision_plan_count"),
            "ready_to_install_file_count": int_get(bundle_summary, "ready_to_install_file_count"),
            "generated_unit_count": int_get(bundle_summary, "generated_file_count"),
            "daily_notes_with_tmux_runtime": top_theme_count(evidence, "tmux_runtime"),
        },
        "blockers": blockers,
        "next_action": next_action,
        "actions": actions,
        "tmux_handoffs": tmux_review_actions,
        "supervision_reviews": supervision_review_actions,
        "verify_sequence": [
            "tmux-cleanup-review --json",
            "nomarh-supervision-plan --json",
            "nomarh-supervision-unit-bundle --json",
            "nomarh-runtime-stabilization-board --json",
        ],
        "paths": {
            "status": str(STATUS_PATH),
            "board": str(BOARD_PATH),
            "tmux_cleanup": str(TMUX_CLEANUP_STATUS),
            "supervision_plan": str(SUPERVISION_PLAN_STATUS),
            "supervision_unit_bundle": str(SUPERVISION_UNIT_BUNDLE_STATUS),
            "ops_evidence_digest": str(OPS_EVIDENCE_DIGEST_STATUS),
        },
    }


def render_action_table(actions: list[dict[str, Any]]) -> list[str]:
    lines = ["| Lane | Title | Status | Kind | Next Action | Verify |", "|---|---|---|---|---|---|"]
    if not actions:
        lines.append("| none | none | none | none | none | none |")
        return lines
    for item in actions:
        lines.append(
            f"| `{safe_md(item['lane'])}` | {safe_md(item['title'])} | `{safe_md(item['status'])}` | `{safe_md(item['kind'])}` | {safe_md(item['next_action'])} | `{safe_md(item['verify'])}` |"
        )
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Nomarh Runtime Stabilization Board",
        "",
        "No tmux pane output, env values, private keys, mailbox contents, or repo file contents are read. This board turns tmux cleanup and supervision status into review decisions.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Actions: `{summary['action_count']}`",
        f"- Tmux handoffs: `{summary['tmux_review_count']}`; high `{summary['tmux_review_high']}`, medium `{summary['tmux_review_medium']}`, stop candidates `{summary['tmux_stop_candidates']}`",
        f"- Dirty project sessions: `{summary['dirty_project_count']}`; non-git project sessions: `{summary['not_git_project_count']}`",
        f"- Supervision actions: `{summary['supervision_action_count']}`; decisions `{summary['decision_needed_count']}`, ready specs `{summary['ready_spec_count']}`, blocked by gate `{summary['blocked_by_gate_count']}`",
        f"- Unit examples: generated `{summary['generated_unit_count']}`, ready files `{summary['ready_to_install_file_count']}`",
        f"- Daily-note evidence with tmux runtime theme: `{summary['daily_notes_with_tmux_runtime']}`",
        "",
    ]
    if payload["blockers"]:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["blockers"])
        lines.append("")

    lines.extend(["## Tmux Handoffs", ""])
    lines.extend(render_action_table(payload["tmux_handoffs"]))
    lines.extend(["", "## Supervision Reviews", ""])
    lines.extend(render_action_table(payload["supervision_reviews"]))
    lines.extend(["", "## Verify Sequence", ""])
    lines.extend(f"{idx}. `{safe_md(command)}`" for idx, command in enumerate(payload["verify_sequence"], start=1))
    lines.extend(["", "## Next Action", "", safe_md(payload["next_action"]), "", "## Source Paths", ""])
    for key, path in payload["paths"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def render_console(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return "\n".join(
        [
            "Nomarh Runtime Stabilization Board",
            f"Result: {payload['result']}",
            f"Actions: {summary['action_count']}",
            f"Tmux: handoffs={summary['tmux_review_count']} high={summary['tmux_review_high']} medium={summary['tmux_review_medium']} dirty={summary['dirty_project_count']} not_git={summary['not_git_project_count']} stop={summary['tmux_stop_candidates']}",
            f"Supervision: actions={summary['supervision_action_count']} decisions={summary['decision_needed_count']} ready_specs={summary['ready_spec_count']} blocked={summary['blocked_by_gate_count']} units={summary['generated_unit_count']}",
            f"Next: {payload['next_action']}",
            f"Board: {BOARD_PATH}",
            f"Status: {STATUS_PATH}",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build no-secret runtime stabilization board for Nomarh tmux and supervision decisions")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_payload()
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(BOARD_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_console(payload))
    return 1 if payload["result"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())

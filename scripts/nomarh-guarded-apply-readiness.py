#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-guarded-apply-readiness"
STATUS_PATH = STATE_DIR / "status.json"
REPORT_PATH = STATE_DIR / "readiness.md"

ACTION_PACK_STATUS = HOME / ".local/state/nomarh-action-pack/status.json"
GUARDED_ACTION_AUDIT_STATUS = HOME / ".local/state/nomarh-guarded-action-audit/status.json"
HARDENING_BUNDLE_STATUS = HOME / ".local/state/hetzner-hardening-command-bundle/status.json"
SUPERVISION_BUNDLE_STATUS = HOME / ".local/state/nomarh-supervision-unit-bundle/status.json"
RUNTIME_STABILIZATION_STATUS = HOME / ".local/state/nomarh-runtime-stabilization-board/status.json"
CUTOVER_GUARD_STATUS = HOME / ".local/state/nomarh-cutover-guard/guard.json"
R2_SECURE_INPUT_PACKET_STATUS = HOME / ".local/state/control-plane-r2-secure-input-packet/status.json"
STATE_TRANSFER_PLAN_STATUS = HOME / ".local/state/nomarh-state-transfer-plan/status.json"
MAIL_PRODUCTION_GATE_STATUS = HOME / ".local/state/nomarh-mail-production-gate/status.json"


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


def compact_action(item: Any) -> dict[str, str]:
    if not isinstance(item, dict):
        return {
            "id": "",
            "lane": "",
            "title": "",
            "status": "",
            "kind": "",
            "next_action": "",
            "verify": "",
            "source": "",
            "reason": "",
            "guard": "",
        }
    return {
        "id": str(item.get("id", "")),
        "lane": str(item.get("lane", "")),
        "title": str(item.get("title", "")),
        "status": str(item.get("status", "")),
        "kind": str(item.get("kind", "")),
        "next_action": str(item.get("next_action", "")),
        "verify": str(item.get("verify", "")),
        "source": str(item.get("source", "")),
        "reason": str(item.get("reason", "")),
        "guard": str(item.get("guard", "")),
    }


def unique_strings(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        key = text.lower().rstrip(".")
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def blocker(
    blocker_id: str,
    lane: str,
    title: str,
    reason: str,
    verify: str,
    source: Path | str,
) -> dict[str, str]:
    return {
        "id": blocker_id,
        "lane": lane,
        "title": title,
        "reason": reason,
        "verify": verify,
        "source": str(source),
    }


def annotate_guarded_actions(
    actions: list[dict[str, str]],
    *,
    audit_result: str,
    gate_blockers: list[dict[str, str]],
    hard_stops: list[str],
) -> list[dict[str, str]]:
    annotated: list[dict[str, str]] = []
    for item in actions:
        enriched = dict(item)
        if audit_result != "ready":
            enriched["apply_readiness"] = "blocked-audit"
            enriched["operator_instruction"] = "Do not run. Fix the guarded action audit first."
        elif gate_blockers or hard_stops:
            enriched["apply_readiness"] = "review-only"
            enriched["operator_instruction"] = (
                "Review source and rollback only. Do not run while external blockers or cutover hard stops are present."
            )
        else:
            enriched["apply_readiness"] = "ready-for-manual-guarded-apply"
            enriched["operator_instruction"] = (
                "Manual apply is allowed only after source and rollback review, with the printed guard set explicitly."
            )
        annotated.append(enriched)
    return annotated


def build_payload() -> dict[str, Any]:
    action_pack = read_json(ACTION_PACK_STATUS)
    guarded_audit = read_json(GUARDED_ACTION_AUDIT_STATUS)
    hardening_bundle = read_json(HARDENING_BUNDLE_STATUS)
    supervision_bundle = read_json(SUPERVISION_BUNDLE_STATUS)
    runtime_stabilization = read_json(RUNTIME_STABILIZATION_STATUS)
    cutover = read_json(CUTOVER_GUARD_STATUS)
    secure_packet = read_json(R2_SECURE_INPUT_PACKET_STATUS)
    state_transfer = read_json(STATE_TRANSFER_PLAN_STATUS)
    mail_gate = read_json(MAIL_PRODUCTION_GATE_STATUS)

    action_summary = dict_get(action_pack, "summary", {})
    audit_summary = dict_get(guarded_audit, "summary", {})
    hardening_summary = dict_get(hardening_bundle, "summary", {})
    supervision_summary = dict_get(supervision_bundle, "summary", {})
    runtime_summary = dict_get(runtime_stabilization, "summary", {})
    secure_packet_summary = dict_get(secure_packet, "summary", {})
    state_transfer_summary = dict_get(state_transfer, "summary", {})
    mail_gate_summary = dict_get(mail_gate, "summary", {})

    audit_result = str(dict_get(guarded_audit, "result", "missing"))
    requires_input = [compact_action(item) for item in list_get(action_pack, "external_blockers")]
    safe_reviews = [compact_action(item) for item in list_get(action_pack, "safe_reviews")]
    guarded_actions_raw = [compact_action(item) for item in list_get(action_pack, "guarded_actions")]
    hard_stops = [str(item) for item in list_get(cutover, "hard_stops")]

    gate_blockers: list[dict[str, str]] = []
    if requires_input:
        gate_blockers.append(
            blocker(
                "external-input-required",
                "backup",
                "Secure input is still required before state copy or cutover",
                f"Action pack has {len(requires_input)} external blocker(s).",
                "control-plane-r2-secure-input-packet --json",
                R2_SECURE_INPUT_PACKET_STATUS,
            )
        )
    if int_get(secure_packet_summary, "missing_required_input_groups"):
        gate_blockers.append(
            blocker(
                "r2-secure-input-missing-groups",
                "backup",
                "R2/restic secure input packet is incomplete",
                f"Missing groups: {int_get(secure_packet_summary, 'missing_required_input_groups')}; active r2 {bool(dict_get(secure_packet_summary, 'active_r2_remote', False))}.",
                "control-plane-r2-secure-input-packet --json",
                R2_SECURE_INPUT_PACKET_STATUS,
            )
        )
    if audit_result != "ready":
        gate_blockers.append(
            blocker(
                "guarded-action-audit-not-ready",
                "guarded-apply",
                "Guarded action audit is not ready",
                f"Audit result {audit_result}; blockers {int_get(audit_summary, 'blocker_count')}.",
                "nomarh-guarded-action-audit --json",
                GUARDED_ACTION_AUDIT_STATUS,
            )
        )
    if str(dict_get(state_transfer, "result", "missing")) != "ready":
        gate_blockers.append(
            blocker(
                "state-transfer-not-ready",
                "migration",
                "State transfer plan is not ready",
                f"Blocked surfaces {int_get(state_transfer_summary, 'blocked_surface_count')}; blocked services {int_get(state_transfer_summary, 'blocked_service_count')}; backup ready {bool(dict_get(state_transfer_summary, 'backup_ready', False))}.",
                "nomarh-state-transfer-plan --json",
                STATE_TRANSFER_PLAN_STATUS,
            )
        )
    if str(dict_get(mail_gate, "result", "missing")) != "ready":
        gate_blockers.append(
            blocker(
                "mail-production-not-ready",
                "mail",
                "Mail production cutover gate is not ready",
                f"Blockers {int_get(mail_gate_summary, 'blocker_count')}; warnings {int_get(mail_gate_summary, 'warning_count')}; MX {bool(dict_get(mail_gate_summary, 'mx_points_to_mailhost', False))}; SPF {bool(dict_get(mail_gate_summary, 'spf_authorizes_mailhost', False))}.",
                "nomarh-mail-production-gate --json",
                MAIL_PRODUCTION_GATE_STATUS,
            )
        )

    guarded_actions = annotate_guarded_actions(
        guarded_actions_raw,
        audit_result=audit_result,
        gate_blockers=gate_blockers,
        hard_stops=hard_stops,
    )

    can_run_guarded_actions = bool(guarded_actions) and audit_result == "ready" and not gate_blockers and not hard_stops
    result = "blocked" if gate_blockers or hard_stops else "warn" if safe_reviews or guarded_actions else "ready"

    if requires_input:
        next_safe_thing = {
            "lane": "backup",
            "title": "Complete the secure R2/restic input packet",
            "command": "control-plane-r2-secure-input-packet --json",
            "reason": "No state copy, mail cutover, or AWS decommission before backup inputs are complete.",
        }
    elif audit_result != "ready":
        next_safe_thing = {
            "lane": "guarded-apply",
            "title": "Fix guarded action audit",
            "command": "nomarh-guarded-action-audit --json",
            "reason": "Guarded scripts must prove guard structure and rollback presence before any manual apply.",
        }
    elif safe_reviews:
        first = safe_reviews[0]
        next_safe_thing = {
            "lane": first["lane"],
            "title": first["title"],
            "command": first["verify"],
            "reason": first["reason"],
        }
    elif can_run_guarded_actions:
        first = guarded_actions[0]
        next_safe_thing = {
            "lane": first["lane"],
            "title": first["title"],
            "command": first["verify"],
            "reason": first["operator_instruction"],
        }
    else:
        next_safe_thing = {
            "lane": "ops",
            "title": "No guarded apply action is currently pending",
            "command": "nomarh-ops --refresh --json",
            "reason": "Refresh before making the next migration decision.",
        }

    do_not = unique_strings(list_get(action_pack, "do_not") + list_get(cutover, "do_not"))

    payload = {
        "schema": "nomarh-guarded-apply-readiness.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "read_only": True,
        "can_run_guarded_actions": can_run_guarded_actions,
        "next_safe_thing": next_safe_thing,
        "summary": {
            "requires_input_count": len(requires_input),
            "safe_review_count": len(safe_reviews),
            "guarded_action_count": len(guarded_actions),
            "gate_blocker_count": len(gate_blockers),
            "hard_stop_count": len(hard_stops),
            "do_not_count": len(do_not),
            "guarded_audit_result": audit_result,
            "guarded_audit_actions": int_get(audit_summary, "action_count"),
            "guarded_audit_blockers": int_get(audit_summary, "blocker_count"),
            "hardening_pending_actions": int_get(hardening_summary, "pending_action_count"),
            "supervision_ready_unit_files": int_get(supervision_summary, "ready_to_install_file_count"),
            "runtime_stabilization_actions": int_get(runtime_summary, "action_count"),
            "runtime_stabilization_tmux_handoffs": int_get(runtime_summary, "tmux_review_count"),
            "runtime_stabilization_decisions": int_get(runtime_summary, "decision_needed_count"),
            "r2_secure_input_missing_groups": int_get(secure_packet_summary, "missing_required_input_groups"),
            "r2_secure_input_active_r2": bool(dict_get(secure_packet_summary, "active_r2_remote", False)),
            "state_transfer_result": str(dict_get(state_transfer, "result", "missing")),
            "state_transfer_blocked_surfaces": int_get(state_transfer_summary, "blocked_surface_count"),
            "state_transfer_blocked_services": int_get(state_transfer_summary, "blocked_service_count"),
            "mail_production_gate_result": str(dict_get(mail_gate, "result", "missing")),
            "mail_production_blockers": int_get(mail_gate_summary, "blocker_count"),
            "mail_production_warnings": int_get(mail_gate_summary, "warning_count"),
            "action_pack_result": str(dict_get(action_pack, "result", "missing")),
            "action_pack_external_blockers": int_get(action_summary, "external_blocker_count"),
            "action_pack_safe_reviews": int_get(action_summary, "safe_review_count"),
            "action_pack_guarded_actions": int_get(action_summary, "guarded_action_count"),
        },
        "requires_input": requires_input,
        "safe_reviews": safe_reviews,
        "guarded_actions": guarded_actions,
        "blocked_by_gate": gate_blockers,
        "do_not": do_not,
        "hard_stops": hard_stops,
        "verify_sequence": [
            "control-plane-r2-secure-input-packet --json",
            "nomarh-guarded-action-audit --json",
            "nomarh-action-pack --json",
            "nomarh-cutover-guard --json",
            "nomarh-state-transfer-plan --json",
            "nomarh-mail-production-gate --json",
            "nomarh-guarded-apply-readiness --json",
        ],
        "paths": {
            "status": str(STATUS_PATH),
            "report": str(REPORT_PATH),
            "action_pack": str(ACTION_PACK_STATUS),
            "guarded_action_audit": str(GUARDED_ACTION_AUDIT_STATUS),
            "hardening_bundle": str(HARDENING_BUNDLE_STATUS),
            "supervision_bundle": str(SUPERVISION_BUNDLE_STATUS),
            "runtime_stabilization": str(RUNTIME_STABILIZATION_STATUS),
            "cutover_guard": str(CUTOVER_GUARD_STATUS),
            "r2_secure_input_packet": str(R2_SECURE_INPUT_PACKET_STATUS),
            "state_transfer_plan": str(STATE_TRANSFER_PLAN_STATUS),
            "mail_production_gate": str(MAIL_PRODUCTION_GATE_STATUS),
        },
    }
    return payload


def render_action_table(actions: list[dict[str, str]], *, include_instruction: bool = False) -> list[str]:
    header = "| Lane | Title | Status | Kind | Next Action | Verify |"
    separator = "|---|---|---|---|---|---|"
    if include_instruction:
        header = "| Lane | Title | Status | Apply Readiness | Instruction | Guard | Source |"
        separator = "|---|---|---|---|---|---|---|"
    lines = [header, separator]
    if not actions:
        lines.append("| none | none | none | none | none | none |" if not include_instruction else "| none | none | none | none | none | none | none |")
        return lines
    for item in actions:
        if include_instruction:
            lines.append(
                f"| `{safe_md(item['lane'])}` | {safe_md(item['title'])} | `{safe_md(item['status'])}` | `{safe_md(item.get('apply_readiness', ''))}` | {safe_md(item.get('operator_instruction', ''))} | `{safe_md(item.get('guard', ''))}` | `{safe_md(item.get('source', ''))}` |"
            )
        else:
            lines.append(
                f"| `{safe_md(item['lane'])}` | {safe_md(item['title'])} | `{safe_md(item['status'])}` | `{safe_md(item['kind'])}` | {safe_md(item['next_action'])} | `{safe_md(item['verify'])}` |"
            )
    return lines


def render_blocker_table(blockers: list[dict[str, str]]) -> list[str]:
    lines = ["| Lane | Title | Reason | Verify |", "|---|---|---|---|"]
    if not blockers:
        lines.append("| none | none | none | none |")
        return lines
    for item in blockers:
        lines.append(
            f"| `{safe_md(item['lane'])}` | {safe_md(item['title'])} | {safe_md(item['reason'])} | `{safe_md(item['verify'])}` |"
        )
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    next_safe = payload["next_safe_thing"]
    lines = [
        "# Nomarh Guarded Apply Readiness",
        "",
        "No secrets, env values, tmux pane output, private keys, mailbox contents, or guarded script bodies are read. This view aggregates status JSON and never executes apply or rollback scripts.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Can run guarded actions: `{payload['can_run_guarded_actions']}`",
        f"- Requires input: `{summary['requires_input_count']}`",
        f"- Safe reviews: `{summary['safe_review_count']}`",
        f"- Guarded actions: `{summary['guarded_action_count']}`",
        f"- Gate blockers: `{summary['gate_blocker_count']}`",
        f"- Hard stops: `{summary['hard_stop_count']}`",
        f"- Guarded audit: `{summary['guarded_audit_result']}` actions `{summary['guarded_audit_actions']}`, blockers `{summary['guarded_audit_blockers']}`",
        f"- R2 secure packet: missing groups `{summary['r2_secure_input_missing_groups']}`, active r2 `{summary['r2_secure_input_active_r2']}`",
        f"- State transfer: `{summary['state_transfer_result']}` blocked surfaces `{summary['state_transfer_blocked_surfaces']}`, blocked services `{summary['state_transfer_blocked_services']}`",
        f"- Mail production: `{summary['mail_production_gate_result']}` blockers `{summary['mail_production_blockers']}`, warnings `{summary['mail_production_warnings']}`",
        "",
        "## Next Safe Thing",
        "",
        f"- Lane: `{safe_md(next_safe['lane'])}`",
        f"- Task: **{safe_md(next_safe['title'])}**",
        f"- Command: `{safe_md(next_safe['command'])}`",
        f"- Reason: {safe_md(next_safe['reason'])}",
        "",
        "## Requires Secure Input",
        "",
    ]
    lines.extend(render_action_table(payload["requires_input"]))
    lines.extend(["", "## Blocked By Gate", ""])
    lines.extend(render_blocker_table(payload["blocked_by_gate"]))
    lines.extend(["", "## Safe Reviews", ""])
    lines.extend(render_action_table(payload["safe_reviews"]))
    lines.extend(["", "## Guarded Actions", ""])
    lines.extend(render_action_table(payload["guarded_actions"], include_instruction=True))

    lines.extend(["", "## Do Not", ""])
    if payload["do_not"]:
        lines.extend(f"- {safe_md(item)}" for item in payload["do_not"])
    else:
        lines.append("- No do-not rules listed.")

    lines.extend(["", "## Hard Stops", ""])
    if payload["hard_stops"]:
        lines.extend(f"- {safe_md(item)}" for item in payload["hard_stops"])
    else:
        lines.append("- No hard stops listed.")

    lines.extend(["", "## Verify Sequence", ""])
    lines.extend(f"{idx}. `{safe_md(command)}`" for idx, command in enumerate(payload["verify_sequence"], start=1))

    lines.extend(["", "## Source Paths", ""])
    for key, path in payload["paths"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def render_console(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    next_safe = payload["next_safe_thing"]
    lines = [
        "Nomarh Guarded Apply Readiness",
        f"Result: {payload['result']}",
        f"Can run guarded actions: {payload['can_run_guarded_actions']}",
        f"Requires input: {summary['requires_input_count']} | safe_reviews={summary['safe_review_count']} | guarded_actions={summary['guarded_action_count']} | gate_blockers={summary['gate_blocker_count']} | hard_stops={summary['hard_stop_count']}",
        f"Audit: {summary['guarded_audit_result']} actions={summary['guarded_audit_actions']} blockers={summary['guarded_audit_blockers']}",
        f"R2: missing_groups={summary['r2_secure_input_missing_groups']} active_r2={summary['r2_secure_input_active_r2']} | state_transfer={summary['state_transfer_result']} blocked_surfaces={summary['state_transfer_blocked_surfaces']} blocked_services={summary['state_transfer_blocked_services']} | mail={summary['mail_production_gate_result']} blockers={summary['mail_production_blockers']}",
        "",
        f"Next safe thing: {next_safe['title']} [{next_safe['lane']}]",
        f"Command: {next_safe['command']}",
        f"Report: {REPORT_PATH}",
        f"Status: {STATUS_PATH}",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="No-secret readiness view for Nomarh guarded apply actions")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_payload()
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_console(payload))
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

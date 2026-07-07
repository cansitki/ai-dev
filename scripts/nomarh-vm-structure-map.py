#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-vm-structure-map"
STATUS_PATH = STATE_DIR / "status.json"
REPORT_PATH = STATE_DIR / "structure.md"

OPS_STATUS = HOME / ".local/state/nomarh-ops/status.json"
OPS_EVIDENCE_STATUS = HOME / ".local/state/nomarh-ops-evidence-digest/status.json"
RUNTIME_DASHBOARD_STATUS = HOME / ".local/state/control-plane-runtime-dashboard/status.json"
CAN_DOCTOR_STATUS = HOME / ".local/state/can-doctor/status.json"
SERVICE_MAP_STATUS = HOME / ".local/state/nomarh-service-migration-map/map.json"
STATE_MANIFEST_STATUS = HOME / ".local/state/nomarh-migration-state-manifest/manifest.json"
STATE_TRANSFER_STATUS = HOME / ".local/state/nomarh-state-transfer-plan/status.json"
MIGRATION_READINESS_STATUS = HOME / ".local/state/nomarh-migration-readiness/readiness.json"
CUTOVER_GUARD_STATUS = HOME / ".local/state/nomarh-cutover-guard/guard.json"
MAIL_GATE_STATUS = HOME / ".local/state/nomarh-mail-production-gate/status.json"
HETZNER_ACCESS_STATUS = HOME / ".local/state/hetzner-access-preflight/status.json"
HETZNER_HARDENING_STATUS = HOME / ".local/state/hetzner-hardening-preflight/status.json"
HETZNER_REMEDIATION_STATUS = HOME / ".local/state/hetzner-hardening-remediation/status.json"
R2_SECURE_PACKET_STATUS = HOME / ".local/state/control-plane-r2-secure-input-packet/status.json"
R2_REMOTE_CONFIG_STATUS = HOME / ".local/state/control-plane-r2-remote-config/status.json"
GUARDED_APPLY_STATUS = HOME / ".local/state/nomarh-guarded-apply-readiness/status.json"


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


def first_check_detail(checks: list[Any], label: str) -> str:
    for item in checks:
        if isinstance(item, dict) and str(item.get("label", "")) == label:
            return str(item.get("detail", ""))
    return ""


def count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key, "") or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def top_items(items: list[dict[str, Any]], priorities: set[str], limit: int = 12) -> list[dict[str, Any]]:
    selected = [item for item in items if str(item.get("priority", "")) in priorities]
    selected.sort(key=lambda item: (str(item.get("priority", "")), str(item.get("risk", "")), str(item.get("name", ""))))
    return [
        {
            "name": str(item.get("name", "")),
            "priority": str(item.get("priority", "")),
            "category": str(item.get("category", "")),
            "risk": str(item.get("risk", "")),
            "current_path": str(dict_get(dict_get(item, "current", {}), "path", "")),
            "current_command": str(dict_get(dict_get(item, "current", {}), "command", "")),
            "target_model": str(item.get("target_model", "")),
            "action": str(item.get("action", "")),
        }
        for item in selected[:limit]
    ]


def gate_statuses(readiness: Any) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for gate in list_get(readiness, "gates"):
        if not isinstance(gate, dict):
            continue
        statuses[str(gate.get("id", ""))] = str(gate.get("status", "missing"))
    return dict(sorted(statuses.items()))


def build_payload() -> dict[str, Any]:
    ops = read_json(OPS_STATUS)
    evidence = read_json(OPS_EVIDENCE_STATUS)
    runtime = read_json(RUNTIME_DASHBOARD_STATUS)
    can_doctor = read_json(CAN_DOCTOR_STATUS)
    service_map = read_json(SERVICE_MAP_STATUS)
    state_manifest = read_json(STATE_MANIFEST_STATUS)
    state_transfer = read_json(STATE_TRANSFER_STATUS)
    readiness = read_json(MIGRATION_READINESS_STATUS)
    cutover = read_json(CUTOVER_GUARD_STATUS)
    mail_gate = read_json(MAIL_GATE_STATUS)
    hetzner_access = read_json(HETZNER_ACCESS_STATUS)
    hetzner_hardening = read_json(HETZNER_HARDENING_STATUS)
    hetzner_remediation = read_json(HETZNER_REMEDIATION_STATUS)
    r2_packet = read_json(R2_SECURE_PACKET_STATUS)
    r2_remote = read_json(R2_REMOTE_CONFIG_STATUS)
    guarded_apply = read_json(GUARDED_APPLY_STATUS)

    ops_summary = dict_get(ops, "summary", {})
    evidence_summary = dict_get(evidence, "summary", {})
    runtime_tmux = dict_get(runtime, "tmux", {})
    service_summary = dict_get(service_map, "summary", {})
    service_items = [item for item in list_get(service_map, "items") if isinstance(item, dict)]
    manifest_summary = dict_get(state_manifest, "summary", {})
    state_transfer_summary = dict_get(state_transfer, "summary", {})
    mail_summary = dict_get(mail_gate, "summary", {})
    r2_summary = dict_get(r2_packet, "summary", {})
    r2_remote_summary = dict_get(r2_remote, "summary", {})
    guarded_summary = dict_get(guarded_apply, "summary", {})
    checks = list_get(can_doctor, "checks")

    current_main = {
        "id": "current-main",
        "role": "current AWS/Coder control plane and daily operations host",
        "host": dict_get(runtime, "host", dict_get(can_doctor, "host", "main")),
        "status": dict_get(runtime, "result", "missing"),
        "disk": first_check_detail(checks, "Disk"),
        "memory": first_check_detail(checks, "Memory"),
        "vault": first_check_detail(checks, "Vault"),
        "tmux_total": int_get(runtime_tmux, "total"),
        "critical_sessions": int_get(runtime_tmux, "critical_count"),
        "provider_workers": int_get(runtime_tmux, "provider_worker_count"),
        "cleanup_candidates": int_get(runtime_tmux, "cleanup_candidate_count"),
    }

    target = dict_get(hetzner_access, "target", {})
    hetzner_mail = {
        "id": "hetzner-mail",
        "role": "target mail host now; candidate main control plane only after gates pass",
        "target": dict_get(hetzner_hardening, "target", dict_get(target, "raw", "root@195.201.194.181")),
        "access": dict_get(hetzner_access, "result", "missing"),
        "hardening": dict_get(hetzner_hardening, "result", "missing"),
        "hardening_warnings": len(list_get(hetzner_hardening, "warnings")),
        "hardening_pending_actions": len(list_get(hetzner_remediation, "actions")),
        "mail_gate": dict_get(mail_gate, "result", "missing"),
        "mailcow_containers": int_get(mail_summary, "mailcow_container_count"),
        "ptr_ok": bool(dict_get(mail_summary, "ptr_points_to_mailhost", False)),
        "mx_aligned": bool(dict_get(mail_summary, "mx_points_to_mailhost", False)),
        "spf_aligned": bool(dict_get(mail_summary, "spf_authorizes_mailhost", False)),
        "dkim_selectors": int_get(mail_summary, "dkim_selector_count"),
        "port25_status": str(dict_get(mail_summary, "port25_status", "missing")),
    }

    r2_backup = {
        "id": "cloudflare-r2-restic",
        "role": "target encrypted backup and restore source for control-plane state",
        "secure_packet": dict_get(r2_packet, "result", "missing"),
        "missing_input_groups": int_get(r2_summary, "missing_required_input_groups"),
        "active_r2": bool(dict_get(r2_summary, "active_r2_remote", False))
        or bool(dict_get(r2_remote_summary, "active_r2_after", False)),
        "remote_config": dict_get(r2_remote, "result", "missing"),
        "remote_blockers": int_get(r2_remote_summary, "blocker_count"),
        "backup_ready": bool(dict_get(state_transfer_summary, "backup_ready", False)),
    }

    daily_ops = {
        "id": "daily-ops",
        "role": "operator entrypoint and evidence trail",
        "nomarh_ops": dict_get(ops, "result", "missing"),
        "daily_notes_scanned": int_get(evidence_summary, "daily_note_count"),
        "missing_daily_notes": int_get(evidence_summary, "missing_day_count"),
        "secret_pattern_files": int_get(evidence_summary, "secret_pattern_file_count"),
        "top_themes": list_get(evidence_summary, "top_themes")[:8],
    }

    service_counts = {
        "total": int_get(service_summary, "total_items"),
        "by_priority": dict_get(service_summary, "by_priority", {}),
        "by_risk": dict_get(service_summary, "by_risk", {}),
        "by_category": dict_get(service_summary, "by_category", {}),
        "by_target_model": dict_get(service_summary, "by_model", {}),
        "p0_p1_items": top_items(service_items, {"P0", "P1"}, limit=14),
        "provider_groups": list_get(runtime_tmux, "provider_groups")[:10],
    }

    state_shape = {
        "surface_count": int_get(manifest_summary, "surface_count"),
        "secret_bearing_surfaces": int_get(manifest_summary, "secret_bearing_surface_count"),
        "service_count": int_get(manifest_summary, "service_count"),
        "surface_decisions": dict_get(manifest_summary, "surface_decisions", {}),
        "service_decisions": dict_get(manifest_summary, "service_decisions", {}),
        "transfer_result": dict_get(state_transfer, "result", "missing"),
        "blocked_surfaces": int_get(state_transfer_summary, "blocked_surface_count"),
        "blocked_services": int_get(state_transfer_summary, "blocked_service_count"),
        "pending_items": int_get(state_transfer_summary, "pending_item_count"),
        "cleanup_handoffs": int_get(state_transfer_summary, "cleanup_handoff_count"),
    }

    gate_map = gate_statuses(readiness)
    hard_stops = [str(item) for item in list_get(cutover, "hard_stops")]
    do_not = [str(item) for item in list_get(cutover, "do_not")]
    blockers: list[str] = []
    warnings: list[str] = []

    if r2_backup["missing_input_groups"] or not r2_backup["active_r2"]:
        blockers.append("R2/restic secure input and active r2: remote are not ready.")
    if dict_get(state_transfer, "result") != "ready":
        blockers.append("State transfer is not ready; blocked surfaces/services remain.")
    if dict_get(mail_gate, "result") != "ready":
        blockers.append("Mail production gate is not ready; keep MX/outbound cutover blocked.")
    if hard_stops:
        blockers.append(f"Cutover guard has {len(hard_stops)} hard stop(s).")
    if dict_get(hetzner_hardening, "result") != "ready":
        warnings.append("Hetzner hardening is not green; non-root admin/firewall/port review remain.")
    if int_get(runtime_tmux, "cleanup_candidate_count"):
        warnings.append("Current VM has tmux cleanup candidates; do not copy live session sprawl.")
    if int_get(guarded_summary, "gate_blocker_count"):
        warnings.append("Guarded apply readiness is blocked; review-only for generated apply scripts.")

    improvements = [
        {
            "priority": "P0",
            "lane": "backup",
            "title": "Finish scoped encrypted R2/restic backup and restore drill",
            "why": "Every state copy and cutover depends on a real restore path.",
            "next_action": "Complete secure R2/restic input, configure active r2:, run backup, then restore drill.",
            "verify": "control-plane-r2-secure-input-packet --json && nomarh-state-transfer-plan --json",
        },
        {
            "priority": "P0",
            "lane": "hardening",
            "title": "Make Hetzner safe as an operating host before moving main duties",
            "why": "Root-only operation, inactive firewall, and public mail ports need explicit policy.",
            "next_action": "Review guarded hardening bundle; create non-root sudo admin, firewall policy, and port review only after gates allow.",
            "verify": "nomarh-guarded-apply-readiness --json && hetzner-hardening-preflight --json",
        },
        {
            "priority": "P1",
            "lane": "runtime",
            "title": "Move durable tmux loops to supervised services/timers",
            "why": "The current host has many long-lived tmux sessions and provider workers.",
            "next_action": "Use supervision plan/unit bundle for P0/P1 services; archive or retire cleanup candidates.",
            "verify": "nomarh-runtime-stabilization-board --json",
        },
        {
            "priority": "P1",
            "lane": "mail",
            "title": "Keep mail as a separate production gate",
            "why": "Mailcow is running, but DNS/auth alignment is not production-ready.",
            "next_action": "Keep MX on current provider until MX/SPF/DKIM/DMARC/port25 checks pass.",
            "verify": "nomarh-mail-production-gate --json",
        },
        {
            "priority": "P1",
            "lane": "daily-ops",
            "title": "Use one morning entrypoint and drill down only from named blockers",
            "why": "Daily notes show repeated manual status gathering across backup, Cloudflare, tmux, security, and mail.",
            "next_action": "Run nomarh-operator-card --refresh first, then follow next safe item.",
            "verify": "nomarh-operator-card --refresh --json",
        },
    ]

    result = "blocked" if blockers else "warn" if warnings else "ready"
    next_safe_thing = (
        improvements[0]
        if blockers
        else improvements[1]
        if warnings
        else {
            "priority": "ready",
            "lane": "ops",
            "title": "Refresh daily operator card",
            "why": "Structure map has no current blockers.",
            "next_action": "Run the daily operator card and execute the named item.",
            "verify": "nomarh-operator-card --refresh --json",
        }
    )

    return {
        "schema": "nomarh-vm-structure-map.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "summary": {
            "node_count": 4,
            "service_count": service_counts["total"],
            "p0_count": int(dict_get(service_counts["by_priority"], "P0", 0) or 0),
            "p1_count": int(dict_get(service_counts["by_priority"], "P1", 0) or 0),
            "high_risk_count": int(dict_get(service_counts["by_risk"], "high", 0) or 0),
            "tmux_total": current_main["tmux_total"],
            "provider_workers": current_main["provider_workers"],
            "cleanup_candidates": current_main["cleanup_candidates"],
            "state_surfaces": state_shape["surface_count"],
            "secret_bearing_surfaces": state_shape["secret_bearing_surfaces"],
            "blocked_surfaces": state_shape["blocked_surfaces"],
            "blocked_services": state_shape["blocked_services"],
            "mailcow_containers": hetzner_mail["mailcow_containers"],
            "mail_gate_result": hetzner_mail["mail_gate"],
            "r2_active": r2_backup["active_r2"],
            "r2_missing_groups": r2_backup["missing_input_groups"],
            "cutover_hard_stops": len(hard_stops),
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
        },
        "nodes": [current_main, hetzner_mail, r2_backup, daily_ops],
        "service_structure": service_counts,
        "state_structure": state_shape,
        "gate_statuses": gate_map,
        "blockers": blockers,
        "warnings": warnings,
        "improvements": improvements,
        "next_safe_thing": next_safe_thing,
        "do_not": do_not,
        "hard_stops": hard_stops,
        "verify_sequence": [
            "nomarh-ops-evidence-digest --json",
            "control-plane-runtime-dashboard",
            "nomarh-service-migration-map --json",
            "nomarh-migration-state-manifest --json",
            "nomarh-state-transfer-plan --json",
            "nomarh-mail-production-gate --json",
            "nomarh-vm-structure-map --json",
        ],
        "paths": {
            "status": str(STATUS_PATH),
            "report": str(REPORT_PATH),
            "ops": str(OPS_STATUS),
            "ops_evidence": str(OPS_EVIDENCE_STATUS),
            "runtime_dashboard": str(RUNTIME_DASHBOARD_STATUS),
            "can_doctor": str(CAN_DOCTOR_STATUS),
            "service_map": str(SERVICE_MAP_STATUS),
            "state_manifest": str(STATE_MANIFEST_STATUS),
            "state_transfer": str(STATE_TRANSFER_STATUS),
            "migration_readiness": str(MIGRATION_READINESS_STATUS),
            "cutover_guard": str(CUTOVER_GUARD_STATUS),
            "mail_gate": str(MAIL_GATE_STATUS),
            "hetzner_access": str(HETZNER_ACCESS_STATUS),
            "hetzner_hardening": str(HETZNER_HARDENING_STATUS),
            "r2_secure_packet": str(R2_SECURE_PACKET_STATUS),
            "r2_remote_config": str(R2_REMOTE_CONFIG_STATUS),
            "guarded_apply": str(GUARDED_APPLY_STATUS),
        },
    }


def render_node_table(nodes: list[dict[str, Any]]) -> list[str]:
    lines = ["| Node | Role | Status | Key Facts |", "|---|---|---|---|"]
    for node in nodes:
        if node["id"] == "current-main":
            facts = (
                f"tmux={node['tmux_total']}; critical={node['critical_sessions']}; "
                f"providers={node['provider_workers']}; cleanup={node['cleanup_candidates']}"
            )
            status = node["status"]
        elif node["id"] == "hetzner-mail":
            facts = (
                f"access={node['access']}; hardening={node['hardening']}; mailcow={node['mailcow_containers']}; "
                f"MX={node['mx_aligned']}; SPF={node['spf_aligned']}; DKIM={node['dkim_selectors']}"
            )
            status = node["mail_gate"]
        elif node["id"] == "cloudflare-r2-restic":
            facts = (
                f"secure_packet={node['secure_packet']}; missing_groups={node['missing_input_groups']}; "
                f"active_r2={node['active_r2']}; backup_ready={node['backup_ready']}"
            )
            status = node["remote_config"]
        else:
            themes = ", ".join(item["theme"] for item in node.get("top_themes", [])[:4] if isinstance(item, dict))
            facts = (
                f"notes={node['daily_notes_scanned']}; missing={node['missing_daily_notes']}; "
                f"secret_patterns={node['secret_pattern_files']}; themes={themes}"
            )
            status = node["nomarh_ops"]
        lines.append(f"| `{safe_md(node['id'])}` | {safe_md(node['role'])} | `{safe_md(status)}` | {safe_md(facts)} |")
    return lines


def render_action_table(actions: list[dict[str, Any]]) -> list[str]:
    lines = ["| Priority | Lane | Title | Next Action | Verify |", "|---|---|---|---|---|"]
    for item in actions:
        lines.append(
            f"| `{safe_md(item['priority'])}` | `{safe_md(item['lane'])}` | {safe_md(item['title'])} | {safe_md(item['next_action'])} | `{safe_md(item['verify'])}` |"
        )
    return lines


def render_service_table(items: list[dict[str, Any]]) -> list[str]:
    lines = ["| Name | Priority | Category | Risk | Target | Action |", "|---|---|---|---|---|---|"]
    if not items:
        lines.append("| none | none | none | none | none | none |")
        return lines
    for item in items:
        lines.append(
            f"| `{safe_md(item['name'])}` | `{safe_md(item['priority'])}` | `{safe_md(item['category'])}` | `{safe_md(item['risk'])}` | `{safe_md(item['target_model'])}` | {safe_md(item['action'])} |"
        )
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    next_safe = payload["next_safe_thing"]
    lines = [
        "# Nomarh VM Structure Map",
        "",
        "No secrets, env values, tmux pane output, private keys, mailbox contents, or remote command bodies are read. This map aggregates existing status JSON and vault/daily-note evidence.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Services/items: `{summary['service_count']}`",
        f"- P0/P1: `{summary['p0_count']}`/`{summary['p1_count']}`",
        f"- High risk: `{summary['high_risk_count']}`",
        f"- Runtime: tmux `{summary['tmux_total']}`, providers `{summary['provider_workers']}`, cleanup `{summary['cleanup_candidates']}`",
        f"- State: surfaces `{summary['state_surfaces']}`, secret-bearing `{summary['secret_bearing_surfaces']}`, blocked surfaces `{summary['blocked_surfaces']}`, blocked services `{summary['blocked_services']}`",
        f"- Mail: `{summary['mail_gate_result']}`, Mailcow containers `{summary['mailcow_containers']}`",
        f"- Backup: active r2 `{summary['r2_active']}`, missing groups `{summary['r2_missing_groups']}`",
        f"- Cutover hard stops: `{summary['cutover_hard_stops']}`",
        "",
        "## Next Safe Thing",
        "",
        f"- Lane: `{safe_md(next_safe['lane'])}`",
        f"- Task: **{safe_md(next_safe['title'])}**",
        f"- Next action: {safe_md(next_safe['next_action'])}",
        f"- Verify: `{safe_md(next_safe['verify'])}`",
        "",
        "## Nodes",
        "",
    ]
    lines.extend(render_node_table(payload["nodes"]))

    if payload["blockers"]:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["blockers"])
    if payload["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["warnings"])

    lines.extend(["", "## Service Structure", ""])
    lines.extend(
        [
            f"- Priority counts: `{safe_md(payload['service_structure']['by_priority'])}`",
            f"- Risk counts: `{safe_md(payload['service_structure']['by_risk'])}`",
            f"- Category counts: `{safe_md(payload['service_structure']['by_category'])}`",
            "",
            "### P0/P1 Items",
            "",
        ]
    )
    lines.extend(render_service_table(payload["service_structure"]["p0_p1_items"]))

    lines.extend(["", "## State Structure", ""])
    state = payload["state_structure"]
    lines.extend(
        [
            f"- Surface decisions: `{safe_md(state['surface_decisions'])}`",
            f"- Service decisions: `{safe_md(state['service_decisions'])}`",
            f"- Transfer result: `{safe_md(state['transfer_result'])}`",
            f"- Pending items: `{safe_md(state['pending_items'])}`",
            f"- Cleanup handoffs: `{safe_md(state['cleanup_handoffs'])}`",
        ]
    )

    lines.extend(["", "## Gate Statuses", "", "| Gate | Status |", "|---|---|"])
    for key, value in payload["gate_statuses"].items():
        lines.append(f"| `{safe_md(key)}` | `{safe_md(value)}` |")

    lines.extend(["", "## Improvements", ""])
    lines.extend(render_action_table(payload["improvements"]))

    lines.extend(["", "## Do Not", ""])
    if payload["do_not"]:
        lines.extend(f"- {safe_md(item)}" for item in payload["do_not"])
    else:
        lines.append("- No do-not rules listed.")

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
    return "\n".join(
        [
            "Nomarh VM Structure Map",
            f"Result: {payload['result']}",
            f"Services: {summary['service_count']} P0={summary['p0_count']} P1={summary['p1_count']} high_risk={summary['high_risk_count']}",
            f"Runtime: tmux={summary['tmux_total']} providers={summary['provider_workers']} cleanup={summary['cleanup_candidates']}",
            f"State: surfaces={summary['state_surfaces']} secret_surfaces={summary['secret_bearing_surfaces']} blocked_surfaces={summary['blocked_surfaces']} blocked_services={summary['blocked_services']}",
            f"Mail: {summary['mail_gate_result']} containers={summary['mailcow_containers']} | Backup: active_r2={summary['r2_active']} missing_groups={summary['r2_missing_groups']} | hard_stops={summary['cutover_hard_stops']}",
            f"Next safe thing: {next_safe['title']} [{next_safe['lane']}]",
            f"Verify: {next_safe['verify']}",
            f"Report: {REPORT_PATH}",
            f"Status: {STATUS_PATH}",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a no-secret VM/service structure map for Nomarh operations")
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

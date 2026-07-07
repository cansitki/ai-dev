#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-supervision-unit-bundle"
UNITS_DIR = STATE_DIR / "units"
STATUS_PATH = STATE_DIR / "status.json"
README_PATH = STATE_DIR / "README.md"
INSTALL_PATH = STATE_DIR / "install-reviewed.sh"
ROLLBACK_PATH = STATE_DIR / "rollback-reviewed.sh"
SUPERVISION_STATUS = HOME / ".local/state/nomarh-supervision-plan/plan.json"


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


def write_text_atomic(path: Path, text: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if not text.endswith("\n"):
        text += "\n"
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(mode)
    tmp.replace(path)
    path.chmod(mode)


def safe_md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def shell_quote(value: str) -> str:
    return shlex.quote(value)


def bool_label(value: Any) -> str:
    return "yes" if value else "no"


def plans(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("plans"), list):
        return []
    return [item for item in payload["plans"] if isinstance(item, dict)]


def sanitized_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value).strip("-").lower()
    return safe or "unknown"


def service_name_for(plan: dict[str, Any]) -> str:
    unit = str(plan.get("unit_name") or "")
    if unit.endswith(".timer"):
        return unit[:-6] + ".service"
    if unit.endswith(".service"):
        return unit
    return f"nomarh-{sanitized_name(str(plan.get('name', 'service')))}.service"


def timer_name_for(plan: dict[str, Any]) -> str:
    unit = str(plan.get("unit_name") or "")
    if unit.endswith(".timer"):
        return unit
    return f"nomarh-{sanitized_name(str(plan.get('name', 'timer')))}.timer"


def exec_start_for(name: str) -> str:
    if name == "can-ops-refresh-loop":
        return "/home/coder/.local/bin/can-ops-refresh --json"
    if name == "github-repo-sweep":
        return "/home/coder/.local/bin/github-repo-sweep"
    if name == "vault-backup":
        return "/home/coder/.local/bin/control-plane-restic-backup --json"
    return f"/usr/bin/env bash -lc 'echo review-required-for-{sanitized_name(name)}; exit 78'"


def working_directory_for(name: str) -> str:
    if name in {"can-ops-refresh-loop", "vault-backup"}:
        return "/home/coder/projects/nomarh"
    if name == "github-repo-sweep":
        return "/home/coder"
    return "/home/coder"


def timer_schedule_for(name: str) -> list[str]:
    if name == "can-ops-refresh-loop":
        return ["OnBootSec=5min", "OnUnitActiveSec=30min"]
    if name == "github-repo-sweep":
        return ["OnBootSec=15min", "OnUnitActiveSec=4h"]
    if name == "vault-backup":
        return ["OnCalendar=hourly", "Persistent=true"]
    return ["OnBootSec=10min", "OnUnitActiveSec=1h"]


def comment_block(plan: dict[str, Any]) -> list[str]:
    blockers = "; ".join(str(item) for item in plan.get("blockers", []) if item) or "none"
    decisions = "; ".join(str(item) for item in plan.get("decisions", []) if item) or "none"
    return [
        f"# Nomarh supervision status: {plan.get('status', '')}",
        f"# Priority: {plan.get('priority', '')}; risk: {plan.get('risk', '')}",
        f"# Target model: {plan.get('target_model', '')}",
        f"# Blockers: {blockers}",
        f"# Decisions: {decisions}",
    ]


def render_service(plan: dict[str, Any], *, oneshot: bool) -> str:
    name = str(plan.get("name") or "unknown")
    service_name = service_name_for(plan)
    lines = [
        *comment_block(plan),
        "[Unit]",
        f"Description=Nomarh supervised {name}",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        f"Type={'oneshot' if oneshot else 'simple'}",
        f"WorkingDirectory={working_directory_for(name)}",
        "Environment=HOME=/home/coder",
        "Environment=PATH=/home/coder/.local/bin:/usr/local/bin:/usr/bin:/bin",
        f"ExecStart={exec_start_for(name)}",
    ]
    if not oneshot:
        lines.extend(["Restart=on-failure", "RestartSec=15"])
    lines.extend(
        [
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
            f"# Unit filename: {service_name}",
        ]
    )
    return "\n".join(lines)


def render_timer(plan: dict[str, Any]) -> str:
    name = str(plan.get("name") or "unknown")
    timer_name = timer_name_for(plan)
    service_name = service_name_for(plan)
    lines = [
        *comment_block(plan),
        "[Unit]",
        f"Description=Nomarh timer for {name}",
        "",
        "[Timer]",
        *timer_schedule_for(name),
        f"Unit={service_name}",
        "",
        "[Install]",
        "WantedBy=timers.target",
        "",
        f"# Unit filename: {timer_name}",
    ]
    return "\n".join(lines)


def is_install_candidate(plan: dict[str, Any]) -> bool:
    return str(plan.get("status")) == "ready-to-spec" and str(plan.get("systemd_kind")) in {"service", "timer"}


def generated_for(plan: dict[str, Any]) -> list[dict[str, str]]:
    name = str(plan.get("name") or "unknown")
    kind = str(plan.get("systemd_kind") or "")
    generated: list[dict[str, str]] = []
    if kind == "timer":
        service_name = service_name_for(plan)
        timer_name = timer_name_for(plan)
        service_path = UNITS_DIR / f"{service_name}.example"
        timer_path = UNITS_DIR / f"{timer_name}.example"
        write_text_atomic(service_path, render_service(plan, oneshot=True))
        write_text_atomic(timer_path, render_timer(plan))
        generated.extend(
            [
                {"unit": service_name, "path": str(service_path), "kind": "service", "name": name},
                {"unit": timer_name, "path": str(timer_path), "kind": "timer", "name": name},
            ]
        )
    elif kind == "service":
        service_name = service_name_for(plan)
        service_path = UNITS_DIR / f"{service_name}.example"
        write_text_atomic(service_path, render_service(plan, oneshot=False))
        generated.append({"unit": service_name, "path": str(service_path), "kind": "service", "name": name})
    return generated


def render_install_script(install_units: list[dict[str, str]]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "if [[ \"${NOMARH_SUPERVISION_INSTALL:-}\" != reviewed ]]; then",
        "  echo \"Refusing to install. Set NOMARH_SUPERVISION_INSTALL=reviewed after reviewing generated units.\" >&2",
        "  exit 64",
        "fi",
        "",
        "SYSTEMD_USER_DIR=\"${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user\"",
        "install -d -m 700 \"$SYSTEMD_USER_DIR\"",
        "",
    ]
    if not install_units:
        lines.extend(["echo 'No ready-to-spec unit candidates to install.'", "exit 0", ""])
        return "\n".join(lines)

    for item in install_units:
        src = item["path"]
        dest = f"$SYSTEMD_USER_DIR/{item['unit']}"
        lines.append(f"install -m 600 {shell_quote(src)} \"{dest}\"")
    lines.extend(["systemctl --user daemon-reload"])
    for item in install_units:
        if item["kind"] == "timer":
            lines.append(f"systemctl --user enable --now {shell_quote(item['unit'])}")
    lines.extend(
        [
            "systemctl --user list-timers --all --no-pager | sed -n '1,120p'",
            "echo 'Installed ready-to-spec Nomarh supervision unit candidates.'",
            "",
        ]
    )
    return "\n".join(lines)


def render_rollback_script(install_units: list[dict[str, str]]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "if [[ \"${NOMARH_SUPERVISION_ROLLBACK:-}\" != reviewed ]]; then",
        "  echo \"Refusing to rollback. Set NOMARH_SUPERVISION_ROLLBACK=reviewed after reviewing units.\" >&2",
        "  exit 64",
        "fi",
        "",
        "SYSTEMD_USER_DIR=\"${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user\"",
    ]
    for item in install_units:
        if item["kind"] == "timer":
            lines.append(f"systemctl --user disable --now {shell_quote(item['unit'])} || true")
    for item in install_units:
        lines.append(f"rm -f \"$SYSTEMD_USER_DIR/{item['unit']}\"")
    lines.extend(["systemctl --user daemon-reload", "echo 'Rolled back ready-to-spec Nomarh supervision unit candidates.'", ""])
    return "\n".join(lines)


def render_readme(payload: dict[str, Any]) -> str:
    lines = [
        "# Nomarh Supervision Unit Bundle",
        "",
        "No unit is installed by this generator. It writes reviewable systemd user unit examples and guarded install/rollback scripts.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Result: `{payload['result']}`",
        f"- Generated files: `{payload['summary']['generated_file_count']}`",
        f"- Ready-to-install unit files: `{payload['summary']['ready_to_install_file_count']}`",
        f"- Blocked plans: `{payload['summary']['blocked_plan_count']}`",
        f"- Pending-decision plans: `{payload['summary']['pending_decision_plan_count']}`",
        "",
        "## Review",
        "",
        "```bash",
        f"find {shell_quote(payload['paths']['units_dir'])} -maxdepth 1 -type f -name '*.example' -print -exec sed -n '1,160p' {{}} \\;",
        "```",
        "",
        "## Install Ready Candidates Only",
        "",
        "```bash",
        f"NOMARH_SUPERVISION_INSTALL=reviewed bash {shell_quote(payload['paths']['install'])}",
        "```",
        "",
        "## Roll Back Ready Candidates",
        "",
        "```bash",
        f"NOMARH_SUPERVISION_ROLLBACK=reviewed bash {shell_quote(payload['paths']['rollback'])}",
        "```",
        "",
        "## Plans",
        "",
        "| Service | Status | Unit Files | Install Candidate |",
        "|---|---|---|---|",
    ]
    for plan in payload["plans"]:
        units = ", ".join(item["unit"] for item in plan["generated_units"]) or "none"
        lines.append(
            f"| `{safe_md(plan['name'])}` | `{safe_md(plan['status'])}` | `{safe_md(units)}` | `{bool_label(plan['install_candidate'])}` |"
        )
    lines.append("")
    if payload["blockers"]:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["blockers"])
        lines.append("")
    return "\n".join(lines)


def build_payload() -> dict[str, Any]:
    supervision = read_json(SUPERVISION_STATUS)
    source_plans = plans(supervision)
    blockers: list[str] = []
    if not isinstance(supervision, dict):
        blockers.append(f"supervision status missing or invalid: {SUPERVISION_STATUS}")

    for old in UNITS_DIR.glob("*.example") if UNITS_DIR.exists() else []:
        old.unlink()

    generated_all: list[dict[str, str]] = []
    install_units: list[dict[str, str]] = []
    plan_rows: list[dict[str, Any]] = []
    for plan in source_plans:
        generated = generated_for(plan)
        generated_all.extend(generated)
        if is_install_candidate(plan):
            install_units.extend(generated)
        plan_rows.append(
            {
                "name": str(plan.get("name") or ""),
                "priority": str(plan.get("priority") or ""),
                "status": str(plan.get("status") or ""),
                "systemd_kind": str(plan.get("systemd_kind") or ""),
                "unit_name": str(plan.get("unit_name") or ""),
                "install_candidate": is_install_candidate(plan),
                "generated_units": generated,
                "blockers": plan.get("blockers") if isinstance(plan.get("blockers"), list) else [],
                "decisions": plan.get("decisions") if isinstance(plan.get("decisions"), list) else [],
            }
        )

    write_text_atomic(INSTALL_PATH, render_install_script(install_units), mode=0o600)
    write_text_atomic(ROLLBACK_PATH, render_rollback_script(install_units), mode=0o600)

    status_counts: dict[str, int] = {}
    for plan in source_plans:
        key = str(plan.get("status") or "unknown")
        status_counts[key] = status_counts.get(key, 0) + 1

    result = "blocked" if blockers else "pending" if install_units or source_plans else "ready"
    payload = {
        "schema": "nomarh-supervision-unit-bundle.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "source_result": str(supervision.get("result", "missing")) if isinstance(supervision, dict) else "missing",
        "blockers": blockers,
        "summary": {
            "plan_count": len(source_plans),
            "status_counts": dict(sorted(status_counts.items())),
            "generated_file_count": len(generated_all),
            "ready_to_install_file_count": len(install_units),
            "ready_to_install_plan_count": sum(1 for plan in source_plans if is_install_candidate(plan)),
            "blocked_plan_count": status_counts.get("blocked", 0),
            "pending_decision_plan_count": status_counts.get("pending-decision", 0),
        },
        "generated_units": generated_all,
        "plans": plan_rows,
        "install_units": install_units,
        "paths": {
            "status": str(STATUS_PATH),
            "readme": str(README_PATH),
            "units_dir": str(UNITS_DIR),
            "install": str(INSTALL_PATH),
            "rollback": str(ROLLBACK_PATH),
            "source_supervision": str(SUPERVISION_STATUS),
        },
        "guards": {
            "install": "NOMARH_SUPERVISION_INSTALL=reviewed",
            "rollback": "NOMARH_SUPERVISION_ROLLBACK=reviewed",
        },
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate no-apply systemd user unit bundle for Nomarh supervision plan")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_payload()
    write_text_atomic(README_PATH, render_readme(payload), mode=0o600)
    write_json_atomic(STATUS_PATH, payload)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Nomarh supervision unit bundle")
        print(f"Result: {payload['result']}")
        print(f"Generated files: {payload['summary']['generated_file_count']}")
        print(f"Ready-to-install files: {payload['summary']['ready_to_install_file_count']}")
        print(f"README: {README_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

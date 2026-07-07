#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-guarded-action-audit"
STATUS_PATH = STATE_DIR / "status.json"
REPORT_PATH = STATE_DIR / "audit.md"

HARDENING_BUNDLE_STATUS = HOME / ".local/state/hetzner-hardening-command-bundle/status.json"
SUPERVISION_BUNDLE_STATUS = HOME / ".local/state/nomarh-supervision-unit-bundle/status.json"

SECRET_PATTERN = re.compile(
    r"cfut_[A-Za-z0-9_]+|"
    r"-----BEGIN (?:OPENSSH|RSA|EC|PRIVATE) KEY-----|"
    r"AKIA[0-9A-Z]{16}|"
    r"AIza[0-9A-Za-z_-]{20,}|"
    r"xox[baprs]-[0-9A-Za-z-]{20,}|"
    r"gh[pousr]_[0-9A-Za-z_]{20,}|"
    r"sk-[A-Za-z0-9]{32,}"
)

EFFECT_TOKENS = [
    "run_remote ",
    "run_local ",
    "ssh ",
    "systemctl ",
    "ufw ",
    "adduser ",
    "usermod ",
    "visudo ",
    "rm -f ",
    "install -",
    "bash -lc ",
]


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


def safe_md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def first_effect_index(text: str) -> int | None:
    indexes = [text.find(token) for token in EFFECT_TOKENS if text.find(token) >= 0]
    return min(indexes) if indexes else None


def audit_script(
    *,
    action_id: str,
    kind: str,
    path: Path,
    guard_var: str,
    rollback_path: Path | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {
        "present": path.exists(),
        "is_file": None,
        "mode": "",
        "mode_not_group_world_writable": None,
        "has_bash_shebang": False,
        "has_strict_mode": False,
        "has_expected_guard": False,
        "has_exit_64": False,
        "guard_before_effect": None,
        "secret_pattern_count": None,
        "rollback_present": None,
    }

    if not path.exists():
        blockers.append(f"script missing: {path}")
        return {
            "id": action_id,
            "kind": kind,
            "path": str(path),
            "guard_var": guard_var,
            "rollback_path": str(rollback_path) if rollback_path else "",
            "result": "blocked",
            "blockers": blockers,
            "warnings": warnings,
            "checks": checks,
        }

    stat = path.stat()
    mode = stat.st_mode & 0o777
    checks["is_file"] = path.is_file()
    checks["mode"] = oct(mode)
    checks["mode_not_group_world_writable"] = (mode & 0o022) == 0
    if not checks["is_file"]:
        blockers.append(f"not a regular file: {path}")
    if not checks["mode_not_group_world_writable"]:
        blockers.append(f"script is group/world-writable: {path}")

    text = path.read_text(encoding="utf-8", errors="replace")
    checks["has_bash_shebang"] = text.startswith("#!/usr/bin/env bash")
    checks["has_strict_mode"] = "set -euo pipefail" in text
    checks["has_expected_guard"] = guard_var in text and "!= reviewed" in text
    checks["has_exit_64"] = "exit 64" in text
    secret_matches = SECRET_PATTERN.findall(text)
    checks["secret_pattern_count"] = len(secret_matches)

    guard_index = text.find(guard_var)
    effect_index = first_effect_index(text)
    checks["guard_before_effect"] = guard_index >= 0 and (effect_index is None or guard_index < effect_index)

    if not checks["has_bash_shebang"]:
        blockers.append("missing bash shebang")
    if not checks["has_strict_mode"]:
        blockers.append("missing set -euo pipefail")
    if not checks["has_expected_guard"]:
        blockers.append(f"missing expected guard variable: {guard_var}")
    if not checks["has_exit_64"]:
        blockers.append("guard does not exit 64")
    if not checks["guard_before_effect"]:
        blockers.append("guard does not appear before effectful commands")
    if secret_matches:
        blockers.append("script contains secret-like pattern")

    if rollback_path is not None:
        checks["rollback_present"] = rollback_path.exists()
        if not rollback_path.exists():
            blockers.append(f"rollback script missing: {rollback_path}")

    result = "blocked" if blockers else "warn" if warnings else "ready"
    return {
        "id": action_id,
        "kind": kind,
        "path": str(path),
        "guard_var": guard_var,
        "rollback_path": str(rollback_path) if rollback_path else "",
        "result": result,
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
    }


def build_payload() -> dict[str, Any]:
    hardening = read_json(HARDENING_BUNDLE_STATUS)
    supervision = read_json(SUPERVISION_BUNDLE_STATUS)

    actions: list[dict[str, Any]] = []

    hardening_paths = dict_get(hardening, "paths", {})
    hardening_guards = dict_get(hardening, "guards", {})
    apply_path = Path(str(dict_get(hardening_paths, "apply", "")))
    hardening_rollback_path = Path(str(dict_get(hardening_paths, "rollback", "")))
    if str(apply_path):
        actions.append(
            audit_script(
                action_id="hetzner-hardening-apply",
                kind="guarded-remote-apply",
                path=apply_path,
                guard_var=str(dict_get(hardening_guards, "apply", "NOMARH_HARDENING_APPLY=reviewed")).split("=")[0],
                rollback_path=hardening_rollback_path,
            )
        )
    if str(hardening_rollback_path):
        actions.append(
            audit_script(
                action_id="hetzner-hardening-rollback",
                kind="guarded-remote-rollback",
                path=hardening_rollback_path,
                guard_var=str(dict_get(hardening_guards, "rollback", "NOMARH_HARDENING_ROLLBACK=reviewed")).split("=")[0],
            )
        )

    supervision_paths = dict_get(supervision, "paths", {})
    supervision_guards = dict_get(supervision, "guards", {})
    install_path = Path(str(dict_get(supervision_paths, "install", "")))
    supervision_rollback_path = Path(str(dict_get(supervision_paths, "rollback", "")))
    if str(install_path):
        actions.append(
            audit_script(
                action_id="supervision-unit-install",
                kind="guarded-local-install",
                path=install_path,
                guard_var=str(dict_get(supervision_guards, "install", "NOMARH_SUPERVISION_INSTALL=reviewed")).split("=")[0],
                rollback_path=supervision_rollback_path,
            )
        )
    if str(supervision_rollback_path):
        actions.append(
            audit_script(
                action_id="supervision-unit-rollback",
                kind="guarded-local-rollback",
                path=supervision_rollback_path,
                guard_var=str(dict_get(supervision_guards, "rollback", "NOMARH_SUPERVISION_ROLLBACK=reviewed")).split("=")[0],
            )
        )

    blockers = [blocker for action in actions for blocker in action["blockers"]]
    warnings = [warning for action in actions for warning in action["warnings"]]
    result = "blocked" if blockers else "warn" if warnings else "ready"
    return {
        "schema": "nomarh-guarded-action-audit.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "summary": {
            "action_count": len(actions),
            "ready_count": sum(1 for action in actions if action["result"] == "ready"),
            "blocked_count": sum(1 for action in actions if action["result"] == "blocked"),
            "warning_count": len(warnings),
            "blocker_count": len(blockers),
        },
        "blockers": blockers,
        "warnings": warnings,
        "actions": actions,
        "paths": {
            "status": str(STATUS_PATH),
            "report": str(REPORT_PATH),
            "hardening_bundle": str(HARDENING_BUNDLE_STATUS),
            "supervision_bundle": str(SUPERVISION_BUNDLE_STATUS),
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Nomarh Guarded Action Audit",
        "",
        "No guarded script is executed. This audit reads generated script text and validates guard structure, rollback presence, modes, and secret-like patterns.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Actions checked: `{payload['summary']['action_count']}`",
        f"- Ready: `{payload['summary']['ready_count']}`",
        f"- Blocked: `{payload['summary']['blocked_count']}`",
        f"- Blockers: `{payload['summary']['blocker_count']}`",
        "",
    ]
    if payload["blockers"]:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {safe_md(item)}" for item in payload["blockers"])
        lines.append("")

    lines.extend(["## Actions", "", "| Action | Kind | Result | Guard | Rollback | Checks |", "|---|---|---|---|---|---|"])
    for action in payload["actions"]:
        checks = action["checks"]
        check_text = (
            f"shebang={checks['has_bash_shebang']}; strict={checks['has_strict_mode']}; "
            f"guard={checks['has_expected_guard']}; exit64={checks['has_exit_64']}; "
            f"before_effect={checks['guard_before_effect']}; secrets={checks['secret_pattern_count']}"
        )
        lines.append(
            f"| `{safe_md(action['id'])}` | `{safe_md(action['kind'])}` | `{safe_md(action['result'])}` | `{safe_md(action['guard_var'])}` | `{safe_md(action.get('rollback_path') or 'n/a')}` | {safe_md(check_text)} |"
        )

    lines.extend(["", "## Source Paths", ""])
    for key, path in payload["paths"].items():
        lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit for generated guarded Nomarh action scripts")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_payload()
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Nomarh guarded action audit")
        print(f"Result: {payload['result']}")
        print(f"Actions: {payload['summary']['action_count']}")
        print(f"Ready: {payload['summary']['ready_count']}")
        print(f"Blocked: {payload['summary']['blocked_count']}")
        print(f"Report: {REPORT_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

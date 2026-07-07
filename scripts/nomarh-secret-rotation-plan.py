#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import socket
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/nomarh-secret-rotation-plan"
STATUS_PATH = STATE_DIR / "status.json"
REPORT_PATH = STATE_DIR / "report.md"

DEFAULT_ROOTS = [
    HOME / "Can",
    HOME / "projects/nomarh",
    HOME / "projects/ai-dev/scripts",
]

EXCLUDED_DIRS = {
    ".git",
    ".wrangler",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
}

MAX_FILE_BYTES = 2_000_000

PATTERNS: dict[str, re.Pattern[str]] = {
    "cloudflare_user_token": re.compile(r"cfut_[A-Za-z0-9_]+"),
    "private_key_block": re.compile(r"-----BEGIN (?:OPENSSH|RSA|EC|DSA|PRIVATE) KEY-----"),
    "aws_access_key_id": re.compile(r"AKIA[0-9A-Z]{16}"),
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    "github_token": re.compile(r"gh[pousr]_[0-9A-Za-z_]{20,}"),
    "openai_api_key": re.compile(r"sk-[A-Za-z0-9]{32,}"),
    "slack_token": re.compile(r"xox[baprs]-[0-9A-Za-z-]{20,}"),
    "discord_bot_token": re.compile(r"[MN][A-Za-z\d]{23}\.[\w-]{6}\.[\w-]{27}"),
}

LOCAL_SECRET_NAME_HINTS = {
    ".env",
    ".dev.vars",
    "secret",
    "secrets",
    "credential",
    "credentials",
    "token",
    "tokens",
    "password",
    "passwd",
    "key",
    "pem",
}


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def is_probably_text(path: Path) -> bool:
    if path.suffix.lower() in {
        ".md",
        ".txt",
        ".json",
        ".jsonc",
        ".py",
        ".sh",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".yml",
        ".yaml",
        ".toml",
        ".env",
        ".example",
        ".conf",
        ".service",
        ".timer",
    }:
        return True
    name = path.name.lower()
    return name.startswith(".env") or name in {".dev.vars", ".dev.vars.example"}


def file_class(path: Path) -> str:
    lowered = str(path).lower()
    name = path.name.lower()
    if str(HOME / "Can").lower() in lowered:
        return "vault_note"
    if any(hint in name for hint in LOCAL_SECRET_NAME_HINTS) or any(part in LOCAL_SECRET_NAME_HINTS for part in path.parts):
        return "local_secret_file"
    if str(HOME / "projects").lower() in lowered:
        return "workspace_source"
    return "other"


def risk_for_class(kind: str) -> str:
    if kind == "vault_note":
        return "rotate-and-redact"
    if kind == "workspace_source":
        return "review-tracking-and-rotate-if-shared"
    if kind == "local_secret_file":
        return "protect-permissions-and-rotate-if-exposed"
    return "review"


def iter_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            files.append(root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in EXCLUDED_DIRS]
            base = Path(dirpath)
            for filename in filenames:
                path = base / filename
                try:
                    if path.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                if is_probably_text(path):
                    files.append(path)
    return sorted(files)


def scan_file(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    counts: dict[str, int] = {}
    for name, pattern in PATTERNS.items():
        count = len(pattern.findall(text))
        if count:
            counts[name] = count
    if not counts:
        return None
    kind = file_class(path)
    try:
        mode = oct(path.stat().st_mode & 0o777)
    except OSError:
        mode = ""
    return {
        "path": str(path),
        "class": kind,
        "risk": risk_for_class(kind),
        "mode": mode,
        "match_counts": counts,
    }


def rotation_actions(findings: list[dict[str, Any]]) -> list[str]:
    pattern_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    for finding in findings:
        class_counts[str(finding["class"])] += 1
        for key, count in finding["match_counts"].items():
            pattern_counts[key] += int(count)

    actions: list[str] = []
    if pattern_counts.get("cloudflare_user_token"):
        actions.append("Rotate exposed Cloudflare user/API tokens and replace broad tokens with least-privilege DNS/Workers/R2/Access tokens.")
    if pattern_counts.get("private_key_block"):
        actions.append("Treat any matched private key block as compromised if it appears outside a local 0600 secret path; rotate the key and remove it from docs/source.")
    if pattern_counts.get("aws_access_key_id"):
        actions.append("Rotate matched AWS access keys and review IAM permissions before migration.")
    if pattern_counts.get("github_token"):
        actions.append("Revoke/rotate matched GitHub tokens and replace with scoped tokens or GitHub App flow.")
    if pattern_counts.get("openai_api_key"):
        actions.append("Rotate matched OpenAI keys and move usage to local env/secret store.")
    if pattern_counts.get("google_api_key"):
        actions.append("Rotate matched Google API keys and restrict key usage by API/referrer/IP where possible.")
    if pattern_counts.get("discord_bot_token"):
        actions.append("Reset matched Discord bot tokens and update only the secure runtime secret path.")
    if pattern_counts.get("slack_token"):
        actions.append("Rotate matched Slack tokens and audit app scopes.")
    if class_counts.get("vault_note"):
        actions.append("Redact matched vault notes after rotation; keep only token purpose, owner, scope, and rotation date.")
    if class_counts.get("local_secret_file"):
        actions.append("Verify local secret files are chmod 600/700 and excluded from backup/reporting paths unless encrypted.")
    return actions


def build_payload(roots: list[Path]) -> dict[str, Any]:
    files = iter_files(roots)
    findings = [finding for path in files if (finding := scan_file(path))]
    pattern_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    file_risk_counts: Counter[str] = Counter()
    for finding in findings:
        class_counts[str(finding["class"])] += 1
        file_risk_counts[str(finding["risk"])] += 1
        for key, count in finding["match_counts"].items():
            pattern_counts[key] += int(count)

    risky_docs = class_counts.get("vault_note", 0) + class_counts.get("workspace_source", 0)
    result = "blocked" if risky_docs else "warn" if findings else "ready"
    return {
        "schema": "nomarh-secret-rotation-plan.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "summary": {
            "roots_scanned": [str(root) for root in roots],
            "files_scanned": len(files),
            "finding_files": len(findings),
            "pattern_counts": dict(sorted(pattern_counts.items())),
            "class_counts": dict(sorted(class_counts.items())),
            "risk_counts": dict(sorted(file_risk_counts.items())),
            "risky_doc_or_source_files": risky_docs,
        },
        "findings": findings,
        "actions": rotation_actions(findings),
        "paths": {"status": str(STATUS_PATH), "report": str(REPORT_PATH)},
    }


def safe_md(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Nomarh Secret Rotation Plan",
        "",
        "No secret values are printed. This scanner reports only pattern types, counts, file paths, classes, and rotation actions.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Files scanned: `{summary['files_scanned']}`",
        f"- Files with findings: `{summary['finding_files']}`",
        f"- Risky doc/source files: `{summary['risky_doc_or_source_files']}`",
        f"- Pattern counts: `{safe_md(summary['pattern_counts'])}`",
        f"- Class counts: `{safe_md(summary['class_counts'])}`",
        "",
        "## Actions",
        "",
    ]
    if payload["actions"]:
        lines.extend(f"- {safe_md(item)}" for item in payload["actions"])
    else:
        lines.append("- No rotation action generated from current scan.")

    lines.extend(["", "## Findings", "", "| File | Class | Risk | Mode | Pattern Counts |", "|---|---|---|---|---|"])
    for finding in payload["findings"][:200]:
        lines.append(
            f"| `{safe_md(finding['path'])}` | `{safe_md(finding['class'])}` | `{safe_md(finding['risk'])}` | `{safe_md(finding['mode'])}` | `{safe_md(finding['match_counts'])}` |"
        )
    if not payload["findings"]:
        lines.append("| none | none | none |  |  |")
    if len(payload["findings"]) > 200:
        lines.append(f"| truncated |  |  |  | {len(payload['findings']) - 200} more finding file(s) omitted |")

    lines.extend(["", "## Roots", ""])
    lines.extend(f"- `{safe_md(root)}`" for root in summary["roots_scanned"])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="No-value secret exposure and rotation scanner for Nomarh operations")
    parser.add_argument("--root", action="append", help="root path to scan; repeatable")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    roots = [Path(item).expanduser() for item in args.root] if args.root else DEFAULT_ROOTS
    payload = build_payload(roots)
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REPORT_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Nomarh secret rotation plan")
        print(f"Result: {payload['result']}")
        print(f"Files with findings: {payload['summary']['finding_files']}")
        print(f"Risky doc/source files: {payload['summary']['risky_doc_or_source_files']}")
        print(f"Report: {REPORT_PATH}")
    return 2 if payload["result"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

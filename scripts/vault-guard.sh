#!/usr/bin/env bash
set -Eeuo pipefail

export PATH="$HOME/.local/bin:$PATH"

mkdir -p "$HOME/.local/bin"
install -m 0755 /dev/stdin "$HOME/.local/bin/vault-guard" <<'PY'
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
from pathlib import Path

HOME = Path.home()
DEFAULT_VAULT = HOME / "Can"
STATE_DIR = HOME / ".local/state/vault-guard"
STATUS_FILE = STATE_DIR / "status.json"
REPORT_FILE = STATE_DIR / "last-report.md"

NOTE_EXTENSIONS = {".md", ".canvas", ".base", ".excalidraw"}
ALLOWED_ROOT_FILES = {"AGENTS.md", "CLAUDE.md", "README.md", "LICENSE.md"}
IGNORED_TOP_LEVEL_DIRS = {".obsidian"}
BAD_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".trash",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".turbo",
    "target",
    "workspace-raw",
    "raw",
    "archives",
    "logs",
}
BAD_EXTENSIONS = {
    ".7z",
    ".bin",
    ".bz2",
    ".class",
    ".csv",
    ".db",
    ".dll",
    ".dmg",
    ".doc",
    ".docx",
    ".dylib",
    ".exe",
    ".gz",
    ".har",
    ".html",
    ".jar",
    ".jpeg",
    ".jpg",
    ".jsonl",
    ".log",
    ".mov",
    ".mp3",
    ".mp4",
    ".o",
    ".parquet",
    ".pdf",
    ".png",
    ".py",
    ".rar",
    ".sqlite",
    ".sqlite3",
    ".tar",
    ".tsv",
    ".wav",
    ".webm",
    ".webp",
    ".xls",
    ".xlsx",
    ".zip",
}


def rel_to_vault(path: Path, vault: Path) -> str:
    return path.relative_to(vault).as_posix()


def human_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    current = float(value)
    for unit in units:
        if current < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(current)} {unit}"
            return f"{current:.1f} {unit}"
        current /= 1024
    return f"{value} B"


def is_note_file(path: Path) -> bool:
    if path.name.endswith(".excalidraw.md"):
        return True
    return path.suffix.lower() in NOTE_EXTENSIONS


def scan_vault(vault: Path, large_bytes: int) -> dict:
    suspicious: list[dict] = []
    total_files = 0
    total_bytes = 0

    if not vault.exists():
        return {
            "state": "error",
            "message": f"vault not found: {vault}",
            "vault": str(vault),
            "total_files": 0,
            "total_bytes": 0,
            "suspicious": [],
        }

    vault = vault.resolve()

    for root, dirs, files in os.walk(vault):
        root_path = Path(root)
        rel_root = root_path.relative_to(vault)

        if rel_root.parts and rel_root.parts[0] in IGNORED_TOP_LEVEL_DIRS:
            dirs[:] = []
            continue

        kept_dirs = []
        for name in dirs:
            lowered = name.lower()
            path = root_path / name
            rel = rel_to_vault(path, vault)
            if rel_root == Path(".") and lowered == ".git":
                continue
            if lowered in BAD_DIR_NAMES:
                suspicious.append(
                    {
                        "kind": "directory",
                        "path": rel,
                        "reason": f"workspace/cache/raw directory: {name}",
                        "size": None,
                        "quarantinable": True,
                    }
                )
            else:
                kept_dirs.append(name)
        dirs[:] = kept_dirs

        for name in files:
            path = root_path / name
            rel = rel_to_vault(path, vault)

            try:
                size = path.stat().st_size
            except OSError:
                size = 0

            total_files += 1
            total_bytes += size

            if rel_root == Path(".") and name in ALLOWED_ROOT_FILES:
                continue

            if rel_root.parts and rel_root.parts[0] in IGNORED_TOP_LEVEL_DIRS:
                continue

            suffix = path.suffix.lower()
            note_file = is_note_file(path)
            reasons = []
            quarantinable = False

            if not note_file:
                reasons.append("non-note file in vault")
                quarantinable = True

            if suffix in BAD_EXTENSIONS:
                reasons.append(f"raw/code/media extension: {suffix}")
                quarantinable = True

            if size > large_bytes:
                reasons.append(f"large file: {human_bytes(size)}")
                quarantinable = quarantinable and not note_file

            if reasons:
                suspicious.append(
                    {
                        "kind": "file",
                        "path": rel,
                        "reason": "; ".join(dict.fromkeys(reasons)),
                        "size": size,
                        "quarantinable": quarantinable,
                    }
                )

    state = "ok" if not suspicious else "warn"
    return {
        "state": state,
        "message": "vault clean" if state == "ok" else "suspicious vault files found",
        "vault": str(vault),
        "total_files": total_files,
        "total_bytes": total_bytes,
        "suspicious": suspicious,
    }


def write_status(result: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    status = {
        "state": result["state"],
        "message": result["message"],
        "updated_at": now,
        "vault": result["vault"],
        "total_files": result["total_files"],
        "total_size": human_bytes(result["total_bytes"]),
        "suspicious_count": len(result["suspicious"]),
        "quarantinable_count": sum(1 for item in result["suspicious"] if item.get("quarantinable")),
    }
    STATUS_FILE.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Vault Guard Report",
        "",
        f"- State: `{status['state']}`",
        f"- Message: {status['message']}",
        f"- Updated: {status['updated_at']}",
        f"- Vault: `{status['vault']}`",
        f"- Files: {status['total_files']}",
        f"- Size: {status['total_size']}",
        f"- Suspicious: {status['suspicious_count']}",
        f"- Quarantinable: {status['quarantinable_count']}",
        "",
    ]
    if result["suspicious"]:
        lines.extend(["## Suspicious Paths", ""])
        for item in result["suspicious"][:500]:
            size = "" if item["size"] is None else f" ({human_bytes(item['size'])})"
            lines.append(f"- `{item['path']}`{size}: {item['reason']}")
        if len(result["suspicious"]) > 500:
            lines.append(f"- ... {len(result['suspicious']) - 500} more")
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_summary(result: dict, limit: int, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    suspicious = result["suspicious"]
    print(f"Vault guard: {result['state']} - {result['message']}")
    print(f"Vault: {result['vault']}")
    print(f"Files: {result['total_files']}  Size: {human_bytes(result['total_bytes'])}")
    print(f"Suspicious: {len(suspicious)}")
    print(f"Report: {REPORT_FILE}")
    if suspicious:
        print("")
        print("Top suspicious paths:")
        for item in suspicious[:limit]:
            size = "" if item["size"] is None else f" ({human_bytes(item['size'])})"
            print(f"- {item['path']}{size}: {item['reason']}")
        if len(suspicious) > limit:
            print(f"- ... {len(suspicious) - limit} more")
        print("")
        print("To move quarantinable raw/code files out of the vault:")
        print("  vault-guard quarantine")


def quarantine(result: dict, vault: Path) -> int:
    vault = vault.resolve()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_root = HOME / "vault-quarantine" / stamp
    moved = 0

    for item in result["suspicious"]:
        if not item.get("quarantinable"):
            continue
        source = (vault / item["path"]).resolve()
        try:
            source.relative_to(vault)
        except ValueError:
            continue
        if not source.exists():
            continue
        destination = dest_root / item["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        moved += 1

    print(f"Moved {moved} quarantinable paths to {dest_root}")
    return moved


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan the Obsidian vault for raw workspace noise.")
    parser.add_argument("command", nargs="?", choices=["scan", "status", "quarantine"], default="scan")
    parser.add_argument("--vault", default=os.environ.get("VAULT_DIR") or os.environ.get("OBSIDIAN_VAULT_DIR") or str(DEFAULT_VAULT))
    parser.add_argument("--large-mb", type=int, default=int(os.environ.get("VAULT_GUARD_LARGE_MB", "5")))
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.command == "status":
        if STATUS_FILE.exists():
            print(STATUS_FILE.read_text(encoding="utf-8"), end="")
            return 0
        print("vault guard has not run yet")
        return 1

    vault = Path(args.vault).expanduser()
    result = scan_vault(vault, args.large_mb * 1024 * 1024)
    write_status(result)

    if args.command == "quarantine":
        quarantine(result, vault)
        result = scan_vault(vault, args.large_mb * 1024 * 1024)
        write_status(result)

    print_summary(result, args.limit, args.json)
    return 0 if result["state"] in {"ok", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
PY

"$HOME/.local/bin/vault-guard" scan --limit 20 || true

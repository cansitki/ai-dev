#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
STATE_DIR = HOME / ".local/state/tmux-cleanup-review"
STATUS_PATH = STATE_DIR / "status.json"
REVIEW_PATH = STATE_DIR / "review.md"
TMUX_INVENTORY_PATH = Path(
    os.environ.get("TMUX_CLEANUP_INVENTORY")
    or HOME / ".local/state/can-doctor/tmux-inventory.json"
)


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
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def run(args: list[str], cwd: Path | None = None, timeout: int = 8) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, cwd=str(cwd) if cwd else None, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except Exception as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


def git_summary(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_dir():
        return {"is_git_repo": False, "dirty_count": None, "branch": "", "head": "", "risk": "path-missing"}

    inside = run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path, timeout=5)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return {"is_git_repo": False, "dirty_count": None, "branch": "", "head": "", "risk": "not-git"}

    status = run(["git", "status", "--porcelain"], cwd=path, timeout=8)
    dirty_count = len([line for line in status.stdout.splitlines() if line.strip()]) if status.returncode == 0 else None
    branch = run(["git", "branch", "--show-current"], cwd=path, timeout=5)
    head = run(["git", "rev-parse", "--short", "HEAD"], cwd=path, timeout=5)
    return {
        "is_git_repo": True,
        "dirty_count": dirty_count,
        "branch": branch.stdout.strip() if branch.returncode == 0 else "",
        "head": head.stdout.strip() if head.returncode == 0 else "",
        "risk": "dirty" if dirty_count else "clean",
    }


def classify_candidate(candidate: dict[str, Any], git: dict[str, Any]) -> tuple[str, str]:
    attached = int(candidate.get("attached") or 0)
    age_days = float(candidate.get("age_days") or 0)
    path = Path(str(candidate.get("path") or ""))

    if attached:
        return "keep", "attached session; do not touch"
    if not path.exists():
        return "review-high", "working path missing; inspect before stopping"
    if git.get("risk") == "dirty":
        return "review-high", "git repo has uncommitted/untracked changes"
    if not git.get("is_git_repo"):
        return "review-medium", "path is not a git repo; inspect manually"
    if age_days >= 30:
        return "stop-candidate", "old detached session with clean git repo"
    return "review-medium", "detached session but not old enough for automatic stop recommendation"


def safe_md(text: Any) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def build_payload() -> dict[str, Any]:
    inventory = read_json(TMUX_INVENTORY_PATH)
    blockers: list[str] = []
    if not isinstance(inventory, dict):
        blockers.append(f"tmux inventory missing or invalid: {TMUX_INVENTORY_PATH}")
        candidates: list[dict[str, Any]] = []
    else:
        candidates = [item for item in inventory.get("cleanup_candidates", []) if isinstance(item, dict)]

    reviews = []
    for candidate in candidates:
        path = Path(str(candidate.get("path") or ""))
        git = git_summary(path)
        verdict, reason = classify_candidate(candidate, git)
        reviews.append(
            {
                "name": candidate.get("name", ""),
                "category": candidate.get("category", ""),
                "created_at": candidate.get("created_at", ""),
                "age_days": candidate.get("age_days"),
                "attached": candidate.get("attached"),
                "command": candidate.get("command", ""),
                "path": str(path),
                "path_exists": path.exists(),
                "git": git,
                "verdict": verdict,
                "reason": reason,
            }
        )

    counts: dict[str, int] = {}
    for review in reviews:
        verdict = str(review["verdict"])
        counts[verdict] = counts.get(verdict, 0) + 1

    result = "blocked" if blockers else "warn" if reviews else "ok"
    return {
        "schema": "tmux-cleanup-review.v1",
        "updated_at": iso_now(),
        "host": socket.gethostname(),
        "result": result,
        "blockers": blockers,
        "summary": {
            "candidate_count": len(reviews),
            "verdict_counts": counts,
            "stop_candidate_count": counts.get("stop-candidate", 0),
            "review_high_count": counts.get("review-high", 0),
            "review_medium_count": counts.get("review-medium", 0),
        },
        "paths": {
            "status": str(STATUS_PATH),
            "review": str(REVIEW_PATH),
            "tmux_inventory": str(TMUX_INVENTORY_PATH),
        },
        "reviews": reviews,
        "next_action": "Inspect stop-candidates manually, then stop only sessions whose work is confirmed unnecessary.",
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Tmux Cleanup Review",
        "",
        "No pane output, env vars, command arguments, or secret files are read. This is non-destructive.",
        "",
        f"- Updated: `{payload['updated_at']}`",
        f"- Host: `{payload['host']}`",
        f"- Result: `{payload['result']}`",
        f"- Candidates: {payload['summary']['candidate_count']}",
        f"- Stop candidates: {payload['summary']['stop_candidate_count']}",
        f"- High review: {payload['summary']['review_high_count']}",
        f"- Medium review: {payload['summary']['review_medium_count']}",
        "",
    ]
    if payload["blockers"]:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {blocker}" for blocker in payload["blockers"])
        lines.append("")

    lines.extend(["## Candidates", "", "| Session | Verdict | Reason | Age | Command | Path | Git |", "|---|---|---|---:|---|---|---|"])
    for review in payload["reviews"]:
        git = review["git"]
        if git.get("is_git_repo"):
            dirty = git.get("dirty_count")
            git_text = f"{git.get('branch') or 'detached'}@{git.get('head')}; dirty={dirty}"
        else:
            git_text = str(git.get("risk") or "not-git")
        lines.append(
            "| "
            f"`{safe_md(review['name'])}` | "
            f"`{safe_md(review['verdict'])}` | "
            f"{safe_md(review['reason'])} | "
            f"{safe_md(review['age_days'])} | "
            f"`{safe_md(review['command'])}` | "
            f"`{safe_md(review['path'])}` | "
            f"{safe_md(git_text)} |"
        )
    if not payload["reviews"]:
        lines.append("| none | ok | no cleanup candidates |  |  |  |  |")

    lines.extend(["", "## Next Action", "", payload["next_action"], ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Review tmux cleanup candidates without stopping sessions")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_payload()
    write_json_atomic(STATUS_PATH, payload)
    write_text_atomic(REVIEW_PATH, render_markdown(payload))

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Tmux cleanup review")
        print(f"Result: {payload['result']}")
        print(f"Candidates: {payload['summary']['candidate_count']}")
        print(f"Stop candidates: {payload['summary']['stop_candidate_count']}")
        print(f"Status: {STATUS_PATH}")
        print(f"Review: {REVIEW_PATH}")
    return 2 if payload["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Puzzle swarm control plane.

This is the deterministic layer around Codex/OpenClaw puzzle agents. It owns
workspace structure, task packets, checker wait-state, and budget gates. It
does not solve puzzles itself and does not store secrets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path(os.environ.get("PUZZLE_SWARM_ROOT", "~/puzzles")).expanduser()
DEFAULT_SEEDCHECKER = Path(os.environ.get("SEEDCHECKER_HOME", "~/projects/seed-checker")).expanduser()
MAX_AUTO_CHECKER_ETA_SEC = 16 * 60 * 60
L2_MODEL_LANES = ("deepseek-v4-pro", "qwen3.7-max", "qwen3.6")
L3_MODEL_LANES = L2_MODEL_LANES
MIN_PROPOSALS_PER_L2_MODEL = 10
MIN_SELECTED_METHODS_PER_ROUND = 5
NO_HIT_NEW_ROUND_THRESHOLD = 3
REQUIRED_CHECKER_FIELDS = (
    "checker_job_id",
    "puzzle_id",
    "layer2_task_id",
    "layer3_task_id",
    "method_id",
    "variant_id",
    "submitting_agent",
    "candidate_manifest_path",
    "candidate_manifest_sha256",
    "target_profile",
    "evidence_reason",
    "failure_scope_if_no_hit",
    "duplicate_policy",
    "eta_seconds",
    "poll_after_seconds",
    "submitted_at",
    "files_to_update_on_result",
    "next_action_on_hit",
    "next_action_on_no_hit",
    "next_action_on_duplicate",
    "next_action_on_error",
)
SECRET_FIELD_NAMES = {
    "seed",
    "seed_phrase",
    "mnemonic",
    "private_key",
    "privkey",
    "wif",
    "secret",
    "passphrase",
    "password",
    "token",
    "api_key",
}
MODEL_LANE_ALIASES = {
    "deepseek-v4-pro": "deepseek-v4-pro",
    "deepseekv4pro": "deepseek-v4-pro",
    "deepseek-v4": "deepseek-v4-pro",
    "qwen3.7-max": "qwen3.7-max",
    "qwen-3.7-max": "qwen3.7-max",
    "qwen37max": "qwen3.7-max",
    "qwen3.7max": "qwen3.7-max",
    "qwen-max": "qwen3.7-max",
    "qwen3.6": "qwen3.6",
    "qwen-3.6": "qwen3.6",
    "qwen36": "qwen3.6",
    "qwen3.6-pro": "qwen3.6",
    "qwen3.6-plus": "qwen3.6",
    "qwen-3.6-pro": "qwen3.6",
    "qwen-3.6-plus": "qwen3.6",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    out = []
    for char in value.strip().lower():
        if char.isalnum():
            out.append(char)
        elif char in {"-", "_", "."}:
            out.append(char)
        else:
            out.append("-")
    slug = "".join(out).strip("-_.")
    while "--" in slug:
        slug = slug.replace("--", "-")
    if not slug:
        raise SystemExit("id cannot be empty")
    return slug


def canonical_model_lane(value: str) -> str:
    normalized = re.sub(r"[\s_]+", "-", value.strip().lower())
    compact = normalized.replace("-", "")
    lane = MODEL_LANE_ALIASES.get(normalized) or MODEL_LANE_ALIASES.get(compact)
    if lane not in L3_MODEL_LANES:
        allowed = ", ".join(L3_MODEL_LANES)
        raise SystemExit(f"unsupported model lane `{value}`; allowed: {allowed}")
    return lane


def read_status(workspace_dir: Path) -> dict[str, Any]:
    path = workspace_dir / "status" / "state.json"
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except Exception:
        return {}


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"JSON file must be an object: {path}")
    reject_inline_secrets(data, path)
    return data


def reject_inline_secrets(data: Any, source: Path | None = None) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            lowered = str(key).lower()
            if lowered in SECRET_FIELD_NAMES and value:
                where = f" in {source}" if source else ""
                raise SystemExit(f"refusing inline secret field `{key}`{where}")
            reject_inline_secrets(value, source)
    elif isinstance(data, list):
        for item in data:
            reject_inline_secrets(item, source)


def write_json(path: Path, data: dict[str, Any], *, overwrite: bool = True) -> None:
    reject_inline_secrets(data, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise SystemExit(f"refusing to overwrite existing file: {path}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, content: str, *, overwrite: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    reject_inline_secrets(data, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, sort_keys=True) + "\n")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def workspace(root: Path, puzzle_id: str) -> Path:
    return root.expanduser() / slugify(puzzle_id)


def event(workspace_dir: Path, event_type: str, **data: Any) -> None:
    append_jsonl(
        workspace_dir / "logs" / "events.jsonl",
        {
            "ts": utcnow(),
            "event": event_type,
            **data,
        },
    )


def update_status(workspace_dir: Path, **data: Any) -> None:
    path = workspace_dir / "status" / "state.json"
    current = read_status(workspace_dir)
    current.update(data)
    current["updated_at"] = utcnow()
    write_json(path, current)


def target_profile(args: argparse.Namespace) -> dict[str, Any]:
    profile = {
        "target_address": args.target_address,
        "target_kind": args.target_kind,
        "path_mode": args.path_mode,
        "path": args.path,
        "notes": args.target_notes or "",
    }
    if not profile["target_address"]:
        raise SystemExit("--target-address is required")
    if not profile["target_kind"]:
        raise SystemExit("--target-kind is required")
    return profile


def command_init(args: argparse.Namespace) -> int:
    puzzle_id = slugify(args.puzzle_id)
    root = args.root.expanduser()
    ws = workspace(root, puzzle_id)
    dirs = [
        "source",
        "memory",
        "memory/past-methods",
        "methods",
        "negative-results",
        "claims",
        "decisions",
        "layer2/rounds",
        "tasks/layer2",
        "tasks/layer3/queued",
        "tasks/layer3/active",
        "tasks/layer3/done",
        "candidates/manifests",
        "checker/requests",
        "checker/waiting",
        "checker/results",
        "handoffs",
        "provider/failures",
        "artifacts",
        "runs",
        "logs",
        "status",
    ]
    for rel in dirs:
        (ws / rel).mkdir(parents=True, exist_ok=True)

    brief = {
        "puzzle_id": puzzle_id,
        "name": args.name or puzzle_id,
        "created_at": utcnow(),
        "status": "active",
        "target_profile": target_profile(args),
        "scope": args.scope or "Solve puzzle by reasoning, evidence, and targeted checking. No brute-force flooding.",
        "source_notes": args.source_note or [],
        "safety": {
            "do_not_store_or_print_secrets": True,
            "hit_requires_can": True,
            "eta_over_16h_requires_can": True,
            "internet_policy": "read-only",
        },
        "model_lanes": {
            "layer1": ["master-codex", "can"],
            "layer2": list(L2_MODEL_LANES),
            "layer3": list(L3_MODEL_LANES),
        },
        "round_policy": {
            "no_hit_new_round_threshold": NO_HIT_NEW_ROUND_THRESHOLD,
            "min_proposals_per_layer2_model": MIN_PROPOSALS_PER_L2_MODEL,
            "min_selected_methods_per_round": MIN_SELECTED_METHODS_PER_ROUND,
        },
    }
    write_json(ws / "source" / "puzzle_brief.json", brief, overwrite=not args.no_overwrite)
    write_text(ws / "CURRENT_TRUTH.md", current_truth_template(brief), overwrite=not args.no_overwrite)
    write_text(ws / "README.md", readme_template(brief), overwrite=not args.no_overwrite)
    write_text(ws / "AGENTS.md", agents_template(brief), overwrite=not args.no_overwrite)
    write_text(ws / "methods" / "index.md", "# Methods Index\n\nNo methods recorded yet.\n", overwrite=False)
    write_json(
        ws / "methods" / "registry.json",
        {"version": 1, "methods": {}, "signatures": {}},
        overwrite=False,
    )
    write_text(ws / "memory" / "past-methods" / "index.md", "# Past Methods\n\nUse one file per method. Summarize killed branches here.\n", overwrite=False)
    write_text(ws / "layer2" / "rounds" / "index.md", "# Layer 2 Rounds\n\nNo rounds recorded yet.\n", overwrite=False)
    for rel in ("claims/promoted.jsonl", "decisions/decisions.jsonl", "logs/events.jsonl", "negative-results/negative_results.jsonl"):
        (ws / rel).touch(exist_ok=True)

    update_status(
        ws,
        puzzle_id=puzzle_id,
        status="initialized",
        active_layer2_tasks=0,
        active_layer3_tasks=0,
        waiting_checker_jobs=0,
        consecutive_no_hit_checks=0,
        layer2_new_round_required=False,
    )
    event(ws, "workspace_initialized", puzzle_id=puzzle_id, workspace=str(ws))
    print(str(ws))
    return 0


def current_truth_template(brief: dict[str, Any]) -> str:
    target = brief["target_profile"]
    return f"""# Current Truth - {brief["name"]}

## Target

- Address: `{target["target_address"]}`
- Target kind: `{target["target_kind"]}`
- Path mode: `{target["path_mode"]}`
- Path: `{target.get("path") or "unknown"}`

## Promoted Facts

- No promoted facts yet.

## Killed Branches

- No killed branches yet.

## Open Questions

- What is the strongest non-bruteforce direction?
"""


def readme_template(brief: dict[str, Any]) -> str:
    return f"""# {brief["name"]} Puzzle Workspace

This workspace is isolated for puzzle `{brief["puzzle_id"]}`.

Start here:

- `source/puzzle_brief.json`
- `CURRENT_TRUTH.md`
- `methods/index.md`
- `methods/registry.json`
- `layer2/rounds/`
- `tasks/layer2/`
- `tasks/layer3/`
- `checker/waiting/`

All agent reasoning that matters must be written to files before waiting,
sleeping, or handing off to another agent.
"""


def agents_template(brief: dict[str, Any]) -> str:
    return f"""# Puzzle Agent Instructions - {brief["name"]}

You are working only on puzzle `{brief["puzzle_id"]}`.

Rules:
- Read `source/puzzle_brief.json` and `CURRENT_TRUTH.md` first.
- Layer 2 lanes are: `{", ".join(L2_MODEL_LANES)}`.
- Layer 3 model lanes are: `{", ".join(L3_MODEL_LANES)}`.
- Do not store, print, or log seeds, private keys, API keys, Discord tokens, or PEM contents.
- If a hit is found, stop and ask Can. Do not post the secret.
- Do not flood checker jobs. Every checker request needs method id, variant id, evidence reason, and failure scope.
- If checker ETA is over 16 hours, ask Can before submitting or continuing.
- Before waiting for checker output, write a durable wait-state file under `checker/waiting/`.
- Layer 2 decides method promotion/death. Layer 3 executes scoped tasks and writes handoffs.
- After 3 consecutive no-hit checker outcomes, Layer 2 must create a new round before more Layer 3 work.
- Each Layer 2 round must contain at least 10 proposals from each Layer 2 model and at least 5 selected methods to verify.
- Every Layer 3 task must prove novelty with `novelty_summary`, `similar_prior_methods`, and `why_this_is_not_a_repeat`.
- Internet use is read-only unless Can explicitly allows otherwise.
"""


def command_start_budget(args: argparse.Namespace) -> int:
    cmd = [
        "codex-usage-guard",
        "start",
        "--name",
        args.name,
        "--max-weekly-delta-percent",
        str(args.max_weekly_delta_percent),
    ]
    if args.absolute_weekly_cap_percent is not None:
        cmd += ["--absolute-weekly-cap-percent", str(args.absolute_weekly_cap_percent)]
    if args.reserve_percent_points is not None:
        cmd += ["--reserve-percent-points", str(args.reserve_percent_points)]
    return subprocess.call(cmd)


def command_run_start(args: argparse.Namespace) -> int:
    root = args.root.expanduser()
    run_id = args.run_id or f"sleep-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    puzzles = [slugify(puzzle) for puzzle in args.puzzle]
    if not puzzles:
        raise SystemExit("at least one --puzzle is required")
    start_args = argparse.Namespace(
        name=args.budget_name,
        max_weekly_delta_percent=args.max_weekly_delta_percent,
        absolute_weekly_cap_percent=args.absolute_weekly_cap_percent,
        reserve_percent_points=args.reserve_percent_points,
    )
    rc = command_start_budget(start_args)
    if rc != 0:
        return rc
    run = {
        "run_id": run_id,
        "created_at": utcnow(),
        "status": "active",
        "mode": "sleep-auto",
        "puzzles": puzzles,
        "budget_name": args.budget_name,
        "max_weekly_delta_percent": args.max_weekly_delta_percent,
        "absolute_weekly_cap_percent": args.absolute_weekly_cap_percent,
        "reserve_percent_points": args.reserve_percent_points,
        "rules": {
            "master_must_check_budget_before_worker_launch": True,
            "workers_must_save_state_before_waiting": True,
            "hit_requires_can": True,
            "eta_over_16h_requires_can": True,
        },
    }
    path = root / "_control" / "runs" / f"{run_id}.json"
    write_json(path, run, overwrite=False)
    append_jsonl(root / "_control" / "events.jsonl", {"ts": utcnow(), "event": "sleep_run_started", **run})
    print(json.dumps({"run_file": str(path), **run}, indent=2, sort_keys=True))
    return 0


def command_run_status(args: argparse.Namespace) -> int:
    root = args.root.expanduser()
    path = root / "_control" / "runs" / f"{args.run_id}.json"
    if not path.is_file():
        raise SystemExit(f"run file not found: {path}")
    run = read_json(path)
    budget_proc = subprocess.run(
        ["codex-usage-guard", "check", "--name", run["budget_name"], "--format", "json"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    budget: dict[str, Any]
    try:
        budget = json.loads(budget_proc.stdout) if budget_proc.stdout.strip() else {"error": budget_proc.stderr.strip()}
    except json.JSONDecodeError:
        budget = {"output": budget_proc.stdout, "error": budget_proc.stderr.strip()}
    puzzle_statuses = {}
    for puzzle_id in run.get("puzzles", []):
        ws = workspace(root, puzzle_id)
        if not ws.exists():
            puzzle_statuses[puzzle_id] = {"status": "missing", "workspace": str(ws)}
            continue
        waiting = sorted((ws / "checker" / "waiting").glob("*.json"))
        puzzle_statuses[puzzle_id] = {
            "workspace": str(ws),
            "waiting_checker_jobs": [path.stem for path in waiting],
            "layer2_tasks": len(list((ws / "tasks" / "layer2").glob("*.json"))),
            "layer3_queued": len(list((ws / "tasks" / "layer3" / "queued").glob("*.json"))),
            "layer3_active": len(list((ws / "tasks" / "layer3" / "active").glob("*.json"))),
        }
    print(
        json.dumps(
            {
                "run": run,
                "budget_exit_code": budget_proc.returncode,
                "budget": budget,
                "puzzles": puzzle_statuses,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if budget_proc.returncode == 0 else budget_proc.returncode


def guard_check(args: argparse.Namespace) -> int:
    cmd = ["codex-usage-guard", "check", "--name", args.budget_name]
    return subprocess.call(cmd)


def command_guard(args: argparse.Namespace) -> int:
    return guard_check(args)


def next_id(prefix: str) -> str:
    return f"{prefix}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{os.getpid()}"


def require_workspace(args: argparse.Namespace) -> Path:
    ws = workspace(args.root.expanduser(), args.puzzle_id)
    if not (ws / "source" / "puzzle_brief.json").is_file():
        raise SystemExit(f"puzzle workspace not initialized: {ws}")
    return ws


def load_method_registry(ws: Path) -> dict[str, Any]:
    path = ws / "methods" / "registry.json"
    if not path.exists():
        return {"version": 1, "methods": {}, "signatures": {}}
    data = read_json(path)
    data.setdefault("version", 1)
    data.setdefault("methods", {})
    data.setdefault("signatures", {})
    return data


def save_method_registry(ws: Path, registry: dict[str, Any]) -> None:
    write_json(ws / "methods" / "registry.json", registry)


def normalized_method_text(*values: str) -> str:
    words = re.findall(r"[a-z0-9]{3,}", " ".join(value or "" for value in values).lower())
    return " ".join(words)


def method_signature(method_family: str, direction: str, objective: str) -> str:
    normalized = normalized_method_text(method_family, direction, objective)
    if not normalized:
        raise SystemExit("method text cannot be empty")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def require_text_field(name: str, value: str | None) -> str:
    if not value or not value.strip():
        raise SystemExit(f"--{name.replace('_', '-')} is required")
    return value.strip()


def validate_round_method(ws: Path, round_id: str | None, method_id: str) -> None:
    if not round_id:
        return
    path = ws / "layer2" / "rounds" / f"{round_id}.json"
    if not path.is_file():
        raise SystemExit(f"Layer 2 round not found: {path}")
    data = read_json(path)
    selected = {str(item) for item in data.get("selected_methods", [])}
    if method_id not in selected:
        raise SystemExit(f"method `{method_id}` is not selected in Layer 2 round `{round_id}`")


def register_method_attempt(
    ws: Path,
    *,
    method_id: str,
    variant_id: str,
    task_id: str,
    layer2_task_id: str,
    round_id: str | None,
    model_lane: str,
    method_family: str,
    direction: str,
    objective: str,
    novelty_summary: str,
    similar_prior_methods: list[str],
    why_this_is_not_a_repeat: str,
    failure_scope_if_no_hit: str,
    reopen_condition: str,
    allow_related_repeat: bool,
) -> str:
    registry = load_method_registry(ws)
    signature = method_signature(method_family, direction, objective)
    existing = registry["signatures"].get(signature)
    if existing and not allow_related_repeat:
        raise SystemExit(
            "method appears to repeat an existing task: "
            f"{existing.get('method_id')} / {existing.get('variant_id')} "
            "(pass --allow-related-repeat only when Layer 2 explicitly reopens it)"
        )

    method = registry["methods"].setdefault(
        method_id,
        {
            "method_id": method_id,
            "created_at": utcnow(),
            "status": "active",
            "variants": {},
        },
    )
    variants = method.setdefault("variants", {})
    if variant_id in variants and not allow_related_repeat:
        raise SystemExit(f"variant `{variant_id}` already exists for method `{method_id}`")
    variants[variant_id] = {
        "task_id": task_id,
        "layer2_task_id": layer2_task_id,
        "round_id": round_id,
        "model_lane": model_lane,
        "method_family": method_family,
        "direction": direction,
        "objective": objective,
        "novelty_summary": novelty_summary,
        "similar_prior_methods": similar_prior_methods,
        "why_this_is_not_a_repeat": why_this_is_not_a_repeat,
        "failure_scope_if_no_hit": failure_scope_if_no_hit,
        "reopen_condition": reopen_condition,
        "signature": signature,
        "created_at": utcnow(),
        "status": "queued",
    }
    registry["signatures"][signature] = {
        "method_id": method_id,
        "variant_id": variant_id,
        "task_id": task_id,
        "round_id": round_id,
        "created_at": utcnow(),
    }
    save_method_registry(ws, registry)
    return signature


def validate_l2_round_packet(data: dict[str, Any], *, trigger: str, no_hit_streak: int) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    proposals_raw = data.get("model_proposals")
    if not isinstance(proposals_raw, dict):
        raise SystemExit("Layer 2 round proposal file must contain object field `model_proposals`")

    normalized_proposals: dict[str, list[dict[str, Any]]] = {}
    strict_no_hit_round = trigger == "no-hit" or no_hit_streak >= NO_HIT_NEW_ROUND_THRESHOLD
    for lane in L2_MODEL_LANES:
        proposals = proposals_raw.get(lane)
        if proposals is None:
            proposals = proposals_raw.get(lane.replace(".", "-"))
        if not isinstance(proposals, list):
            raise SystemExit(f"model_proposals.{lane} must be a list")
        if strict_no_hit_round and len(proposals) < MIN_PROPOSALS_PER_L2_MODEL:
            raise SystemExit(
                f"{lane} must propose at least {MIN_PROPOSALS_PER_L2_MODEL} methods "
                f"after {NO_HIT_NEW_ROUND_THRESHOLD} no-hit outcomes"
            )
        for index, proposal in enumerate(proposals, start=1):
            if not isinstance(proposal, dict):
                raise SystemExit(f"{lane} proposal #{index} must be an object")
            for field in (
                "method_id",
                "title",
                "summary",
                "novelty_summary",
                "why_this_is_not_a_repeat",
                "failure_scope_if_no_hit",
                "testable_output",
            ):
                if not proposal.get(field):
                    raise SystemExit(f"{lane} proposal #{index} missing `{field}`")
        normalized_proposals[lane] = proposals

    selected = data.get("selected_methods") or []
    if not isinstance(selected, list):
        raise SystemExit("selected_methods must be a list")
    selected = [str(item) for item in selected if str(item).strip()]
    if len(selected) < MIN_SELECTED_METHODS_PER_ROUND:
        raise SystemExit(f"Layer 2 round must select at least {MIN_SELECTED_METHODS_PER_ROUND} methods")

    proposal_ids = {
        str(proposal["method_id"])
        for proposals in normalized_proposals.values()
        for proposal in proposals
    }
    missing = [method_id for method_id in selected if method_id not in proposal_ids]
    if missing:
        raise SystemExit(f"selected methods not present in model proposals: {', '.join(missing)}")
    return normalized_proposals, selected


def command_l2_round(args: argparse.Namespace) -> int:
    ws = require_workspace(args)
    proposal_path = Path(args.proposal_file).expanduser().resolve()
    if not proposal_path.is_file():
        raise SystemExit(f"proposal file not found: {proposal_path}")
    data = read_json(proposal_path)
    round_id = args.round_id or data.get("round_id") or next_id("L2ROUND")
    trigger = args.trigger or data.get("trigger") or "manual"
    no_hit_streak = args.no_hit_streak
    if no_hit_streak is None:
        no_hit_streak = int(read_status(ws).get("consecutive_no_hit_checks") or 0)
    proposals, selected = validate_l2_round_packet(data, trigger=trigger, no_hit_streak=no_hit_streak)
    packet = {
        "round_id": round_id,
        "puzzle_id": slugify(args.puzzle_id),
        "created_at": utcnow(),
        "created_by": args.created_by,
        "trigger": trigger,
        "no_hit_streak_at_start": no_hit_streak,
        "model_lanes": list(L2_MODEL_LANES),
        "min_proposals_per_layer2_model": MIN_PROPOSALS_PER_L2_MODEL,
        "min_selected_methods": MIN_SELECTED_METHODS_PER_ROUND,
        "model_proposals": proposals,
        "selected_methods": selected,
        "council_summary": data.get("council_summary") or "",
        "next_verification_plan": data.get("next_verification_plan") or "",
        "source_proposal_file": str(proposal_path),
    }
    write_json(ws / "layer2" / "rounds" / f"{round_id}.json", packet, overwrite=False)
    event(
        ws,
        "layer2_round_created",
        round_id=round_id,
        trigger=trigger,
        selected_method_count=len(selected),
    )
    update_status(
        ws,
        last_layer2_round=round_id,
        layer2_new_round_required=False,
        consecutive_no_hit_checks=0,
    )
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0


def command_l2_round_template(args: argparse.Namespace) -> int:
    ws = require_workspace(args)
    round_id = args.round_id or next_id("L2ROUND")
    data: dict[str, Any] = {
        "round_id": round_id,
        "trigger": args.trigger,
        "council_summary": "",
        "next_verification_plan": "",
        "model_proposals": {},
        "selected_methods": [],
    }
    for lane in L2_MODEL_LANES:
        proposals = []
        for index in range(1, MIN_PROPOSALS_PER_L2_MODEL + 1):
            method_id = f"{lane}-method-{index:02d}"
            proposals.append(
                {
                    "method_id": method_id,
                    "title": "",
                    "summary": "",
                    "novelty_summary": "",
                    "why_this_is_not_a_repeat": "",
                    "failure_scope_if_no_hit": "",
                    "testable_output": "",
                }
            )
            if len(data["selected_methods"]) < MIN_SELECTED_METHODS_PER_ROUND:
                data["selected_methods"].append(method_id)
        data["model_proposals"][lane] = proposals
    output = Path(args.output).expanduser() if args.output else ws / "layer2" / "rounds" / f"{round_id}.proposal.json"
    write_json(output, data, overwrite=False)
    print(str(output))
    return 0


def command_l2_task(args: argparse.Namespace) -> int:
    ws = require_workspace(args)
    task_id = args.task_id or next_id("L2")
    packet = {
        "task_id": task_id,
        "puzzle_id": slugify(args.puzzle_id),
        "created_at": utcnow(),
        "created_by": args.created_by,
        "status": "queued",
        "direction": args.direction,
        "question": args.question,
        "method_family": args.method_family,
        "evidence": args.evidence or [],
        "stop_conditions": args.stop_condition or [],
        "layer3_expected": args.layer3_expected or "Layer 2 must decide whether to spawn Layer 3.",
    }
    if not packet["direction"] or not packet["question"]:
        raise SystemExit("--direction and --question are required")
    write_json(ws / "tasks" / "layer2" / f"{task_id}.json", packet, overwrite=False)
    event(ws, "layer2_task_created", task_id=task_id, direction=args.direction)
    update_status(ws, last_layer2_task=task_id)
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0


def command_l3_task(args: argparse.Namespace) -> int:
    ws = require_workspace(args)
    status = read_status(ws)
    if status.get("layer2_new_round_required") and not args.round_id:
        raise SystemExit(
            "Layer 2 new-round gate is active after consecutive no-hit outcomes; "
            "create a validated l2-round and pass --round-id before spawning Layer 3"
        )
    task_id = args.task_id or next_id("L3")
    method_id = args.method_id or f"METHOD-{slugify(args.method_family or args.direction)[:40]}"
    variant_id = args.variant_id or f"{method_id}-V001"
    model_lane = canonical_model_lane(args.model_lane)
    novelty_summary = require_text_field("novelty_summary", args.novelty_summary)
    why_this_is_not_a_repeat = require_text_field("why_this_is_not_a_repeat", args.why_this_is_not_a_repeat)
    failure_scope_if_no_hit = require_text_field("failure_scope_if_no_hit", args.failure_scope_if_no_hit)
    reopen_condition = require_text_field("reopen_condition", args.reopen_condition)
    similar_prior_methods = args.similar_prior_method or []
    validate_round_method(ws, args.round_id, method_id)
    signature = register_method_attempt(
        ws,
        method_id=method_id,
        variant_id=variant_id,
        task_id=task_id,
        layer2_task_id=args.layer2_task_id,
        round_id=args.round_id,
        model_lane=model_lane,
        method_family=args.method_family,
        direction=args.direction,
        objective=args.objective,
        novelty_summary=novelty_summary,
        similar_prior_methods=similar_prior_methods,
        why_this_is_not_a_repeat=why_this_is_not_a_repeat,
        failure_scope_if_no_hit=failure_scope_if_no_hit,
        reopen_condition=reopen_condition,
        allow_related_repeat=bool(args.allow_related_repeat),
    )
    packet = {
        "task_id": task_id,
        "puzzle_id": slugify(args.puzzle_id),
        "layer2_task_id": args.layer2_task_id,
        "round_id": args.round_id,
        "created_at": utcnow(),
        "status": "queued",
        "model_lane": model_lane,
        "method_id": method_id,
        "variant_id": variant_id,
        "method_signature": signature,
        "direction": args.direction,
        "objective": args.objective,
        "inputs": args.input or [],
        "anti_loop": {
            "novelty_summary": novelty_summary,
            "similar_prior_methods": similar_prior_methods,
            "why_this_is_not_a_repeat": why_this_is_not_a_repeat,
            "failure_scope_if_no_hit": failure_scope_if_no_hit,
            "reopen_condition": reopen_condition,
            "allow_related_repeat": bool(args.allow_related_repeat),
        },
        "required_outputs": [
            "method note update",
            "candidate manifest if candidates are produced",
            "checker wait-state if MCP checker is used",
            "handoff summary",
        ],
        "stop_conditions": args.stop_condition or [],
        "checker_allowed": bool(args.checker_allowed),
    }
    required = ("layer2_task_id", "direction", "objective", "model_lane")
    missing = [key for key in required if not packet[key]]
    if missing:
        raise SystemExit(f"missing required fields: {', '.join(missing)}")
    write_json(ws / "tasks" / "layer3" / "queued" / f"{task_id}.json", packet, overwrite=False)
    ensure_method_file(ws, method_id, args.direction)
    event(ws, "layer3_task_created", task_id=task_id, method_id=method_id, variant_id=variant_id)
    update_status(ws, last_layer3_task=task_id)
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0


def ensure_method_file(ws: Path, method_id: str, title: str) -> None:
    path = ws / "methods" / f"{method_id}.md"
    if path.exists():
        return
    write_text(
        path,
        f"""# {method_id}

## Direction

{title}

## Attempts

- No attempts yet.

## Negative Results

- None.

## Current Status

active
""",
        overwrite=False,
    )


def command_manifest(args: argparse.Namespace) -> int:
    ws = require_workspace(args)
    candidate_file = Path(args.candidate_file).expanduser().resolve()
    if not candidate_file.is_file():
        raise SystemExit(f"candidate file not found: {candidate_file}")
    manifest_id = args.manifest_id or next_id("MANIFEST")
    data = {
        "manifest_id": manifest_id,
        "puzzle_id": slugify(args.puzzle_id),
        "created_at": utcnow(),
        "method_id": args.method_id,
        "variant_id": args.variant_id,
        "candidate_file": str(candidate_file),
        "candidate_file_sha256": file_sha256(candidate_file) if args.hash_file else None,
        "candidate_count": args.candidate_count,
        "candidate_type": args.candidate_type,
        "content_id": args.content_id or manifest_id,
        "generation_summary": args.generation_summary,
        "evidence_reason": args.evidence_reason,
        "failure_scope_if_no_hit": args.failure_scope_if_no_hit,
    }
    for field in ("method_id", "variant_id", "candidate_count", "candidate_type", "evidence_reason", "failure_scope_if_no_hit"):
        if not data[field]:
            raise SystemExit(f"--{field.replace('_', '-')} is required")
    write_json(ws / "candidates" / "manifests" / f"{manifest_id}.json", data, overwrite=False)
    event(ws, "candidate_manifest_created", manifest_id=manifest_id, method_id=args.method_id, variant_id=args.variant_id)
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


def seedchecker_cmd(seedchecker_home: Path) -> list[str]:
    script = seedchecker_home.expanduser() / "scripts" / "seedchecker_scheduler.py"
    if not script.is_file():
        raise SystemExit(f"seedchecker scheduler not found: {script}")
    return [sys.executable, str(script)]


def run_json(cmd: list[str]) -> dict[str, Any]:
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or proc.stdout.strip() or f"command failed: {' '.join(cmd)}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"command did not return JSON: {exc}\n{proc.stdout}") from exc
    if not isinstance(data, dict):
        raise SystemExit("command returned non-object JSON")
    return data


def checker_request_from_manifest(ws: Path, args: argparse.Namespace, manifest: dict[str, Any]) -> dict[str, Any]:
    brief = read_json(ws / "source" / "puzzle_brief.json")
    target = brief["target_profile"]
    request_type = args.request_type or manifest["candidate_type"]
    path_mode = args.path_mode or target.get("path_mode") or "auto"
    if path_mode == "none":
        path_mode = "auto"
    request = {
        "candidate_file": manifest["candidate_file"],
        "request_type": request_type,
        "target_address": args.target_address or target["target_address"],
        "candidate_count": int(manifest["candidate_count"]),
        "seed_standard": args.seed_standard,
        "path_mode": path_mode,
        "path": args.path if args.path is not None else target.get("path"),
        "passphrase_mode": args.passphrase_mode,
        "content_id": manifest.get("content_id") or manifest["manifest_id"],
    }
    if request["path"] in {"", "unknown", None}:
        request.pop("path", None)
    return request


def command_checker_submit(args: argparse.Namespace) -> int:
    ws = require_workspace(args)
    if args.budget_name and guard_check(args) != 0:
        raise SystemExit("Codex usage budget exhausted; not submitting checker job")

    manifest_path = (ws / "candidates" / "manifests" / f"{args.manifest_id}.json").resolve()
    if not manifest_path.is_file():
        raise SystemExit(f"manifest not found: {manifest_path}")
    manifest = read_json(manifest_path)
    request = checker_request_from_manifest(ws, args, manifest)
    request_id = args.request_id or next_id("CHECKREQ")
    request_path = ws / "checker" / "requests" / f"{request_id}.json"
    write_json(request_path, request, overwrite=False)

    submit = run_json(seedchecker_cmd(args.seedchecker_home) + ["submit", "--request", str(request_path)])
    eta = int(submit.get("estimated_finish_in_sec") or submit.get("estimated_runtime_sec") or 0)
    if eta > MAX_AUTO_CHECKER_ETA_SEC and not args.approved_over_16h:
        job_id = submit.get("job_id")
        if job_id:
            try:
                run_json(seedchecker_cmd(args.seedchecker_home) + ["cancel", str(job_id)])
            except SystemExit:
                pass
        raise SystemExit(f"checker ETA {eta}s exceeds 16h; canceled/blocked pending Can approval")

    wait_state = build_wait_state(ws, args, manifest, manifest_path, request_path, submit, eta)
    wait_path = ws / "checker" / "waiting" / f"{wait_state['checker_job_id']}.json"
    write_json(wait_path, wait_state, overwrite=False)
    event(
        ws,
        "checker_wait_state_created",
        checker_job_id=wait_state["checker_job_id"],
        method_id=wait_state["method_id"],
        variant_id=wait_state["variant_id"],
        eta_seconds=eta,
        status=submit.get("status"),
    )
    waiting_count = len(list((ws / "checker" / "waiting").glob("*.json")))
    update_status(ws, last_checker_job=wait_state["checker_job_id"], waiting_checker_jobs=waiting_count)
    print(json.dumps(wait_state, indent=2, sort_keys=True))
    return 0


def build_wait_state(
    ws: Path,
    args: argparse.Namespace,
    manifest: dict[str, Any],
    manifest_path: Path,
    request_path: Path,
    submit: dict[str, Any],
    eta: int,
) -> dict[str, Any]:
    checker_job_id = submit.get("job_id") or f"duplicate-{manifest['manifest_id']}"
    state = {
        "checker_job_id": checker_job_id,
        "checker_status": submit.get("status"),
        "duplicate": bool(submit.get("duplicate")),
        "puzzle_id": slugify(args.puzzle_id),
        "layer2_task_id": args.layer2_task_id,
        "layer3_task_id": args.layer3_task_id,
        "method_id": manifest["method_id"],
        "variant_id": manifest["variant_id"],
        "submitting_agent": args.submitting_agent,
        "model": args.model,
        "candidate_manifest_path": str(manifest_path),
        "candidate_manifest_sha256": file_sha256(manifest_path),
        "checker_request_path": str(request_path),
        "target_profile": read_json(ws / "source" / "puzzle_brief.json")["target_profile"],
        "evidence_reason": manifest["evidence_reason"],
        "failure_scope_if_no_hit": manifest["failure_scope_if_no_hit"],
        "duplicate_policy": args.duplicate_policy,
        "eta_seconds": eta,
        "poll_after_seconds": int(submit.get("poll_after_sec") or 300),
        "wake_after_seconds": int(submit.get("wake_after_sec") or eta or 300),
        "submitted_at": utcnow(),
        "files_to_update_on_result": [
            str(ws / "methods" / f"{manifest['method_id']}.md"),
            str(ws / "candidates" / "manifests" / f"{manifest['manifest_id']}.json"),
            str(ws / "handoffs" / f"{args.layer3_task_id or checker_job_id}-checker-result.md"),
        ],
        "next_action_on_hit": "Stop all related work, do not print secret material, ask Can.",
        "next_action_on_no_hit": args.next_action_on_no_hit,
        "next_action_on_duplicate": "Mark duplicate and return to Layer 2 with previous result reference.",
        "next_action_on_error": "Save error, do not retry blindly, ask Layer 2 to decide.",
        "scheduler_response": submit,
    }
    missing = [field for field in REQUIRED_CHECKER_FIELDS if not state.get(field)]
    if missing:
        raise SystemExit(f"wait-state missing required fields: {', '.join(missing)}")
    return state


def command_checker_poll(args: argparse.Namespace) -> int:
    ws = require_workspace(args)
    wait_path = ws / "checker" / "waiting" / f"{args.checker_job_id}.json"
    if not wait_path.is_file():
        raise SystemExit(f"wait-state not found: {wait_path}")
    state = read_json(wait_path)
    if state.get("duplicate"):
        result = {
            "job_id": state["checker_job_id"],
            "status": "completed",
            "result_status": "duplicate",
            "scheduler_response": state.get("scheduler_response"),
        }
    else:
        result = run_json(seedchecker_cmd(args.seedchecker_home) + ["status", state["checker_job_id"]])
    status = result.get("status")
    if status not in {"completed", "failed", "canceled"}:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    handoff = write_checker_handoff(ws, state, result)
    result_path = ws / "checker" / "results" / f"{state['checker_job_id']}.json"
    write_json(result_path, {"wait_state": state, "scheduler_result": result, "handoff": str(handoff)})
    done_path = ws / "checker" / "waiting" / "done" / wait_path.name
    done_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(wait_path), str(done_path))
    outcome_update = record_checker_outcome(ws, state, result)
    event(ws, "checker_result_recorded", checker_job_id=state["checker_job_id"], status=status, result_status=result.get("result_status"))
    waiting_count = len(list((ws / "checker" / "waiting").glob("*.json")))
    update_status(ws, last_checker_result=state["checker_job_id"], waiting_checker_jobs=waiting_count, **outcome_update)
    print(json.dumps({"result": result, "handoff": str(handoff), "result_path": str(result_path)}, indent=2, sort_keys=True))
    return 0


def write_checker_handoff(ws: Path, state: dict[str, Any], result: dict[str, Any]) -> Path:
    status = result.get("result_status") or result.get("status")
    if status == "hit":
        action = state["next_action_on_hit"]
    elif status == "duplicate":
        action = state["next_action_on_duplicate"]
    elif result.get("status") == "failed":
        action = state["next_action_on_error"]
    else:
        action = state["next_action_on_no_hit"]
    path = ws / "handoffs" / f"{state['layer3_task_id'] or state['checker_job_id']}-checker-result.md"
    content = f"""# Checker Result Handoff - {state['checker_job_id']}

## Status

- Scheduler status: `{result.get("status")}`
- Result status: `{status}`
- Method: `{state["method_id"]}`
- Variant: `{state["variant_id"]}`

## Failure Scope If No Hit

{state["failure_scope_if_no_hit"]}

## Evidence Reason

{state["evidence_reason"]}

## Next Action

{action}
"""
    write_text(path, content)
    return path


def checker_outcome_kind(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "").lower()
    result_status = str(result.get("result_status") or "").lower()
    if result_status in {"hit", "found", "success"}:
        return "hit"
    if result_status == "duplicate":
        return "duplicate"
    if status in {"failed", "canceled", "error"}:
        return "error"
    if result_status in {"no_hit", "no-hit", "not_found", "not-found", "miss", "none"}:
        return "no_hit"
    if status == "completed":
        return "no_hit"
    return "pending"


def mark_registry_variant(ws: Path, method_id: str, variant_id: str, status: str) -> None:
    registry = load_method_registry(ws)
    method = registry.get("methods", {}).get(method_id)
    if not method:
        return
    variant = method.get("variants", {}).get(variant_id)
    if not variant:
        return
    variant["status"] = status
    variant["updated_at"] = utcnow()
    if status in {"no_hit", "hit", "error", "duplicate"}:
        method["last_outcome"] = status
        method["updated_at"] = utcnow()
    save_method_registry(ws, registry)


def record_checker_outcome(ws: Path, state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    kind = checker_outcome_kind(result)
    mark_registry_variant(ws, state["method_id"], state["variant_id"], kind)
    current = read_status(ws)
    if kind == "hit":
        return {
            "last_checker_outcome": kind,
            "hit_found": True,
            "layer2_new_round_required": False,
            "consecutive_no_hit_checks": 0,
        }
    if kind == "no_hit":
        next_count = int(current.get("consecutive_no_hit_checks") or 0) + 1
        new_round_required = next_count >= NO_HIT_NEW_ROUND_THRESHOLD
        append_jsonl(
            ws / "negative-results" / "negative_results.jsonl",
            {
                "negative_id": f"N-{state['checker_job_id']}",
                "hypothesis": state["method_id"],
                "variant_id": state["variant_id"],
                "scope": state["failure_scope_if_no_hit"],
                "result": "checker_no_hit",
                "reopen_condition": "Layer 2 may reopen only with new evidence or a narrowed variant.",
                "created_at": utcnow(),
            },
        )
        if new_round_required:
            event(
                ws,
                "layer2_new_round_required",
                consecutive_no_hit_checks=next_count,
                threshold=NO_HIT_NEW_ROUND_THRESHOLD,
            )
        return {
            "last_checker_outcome": kind,
            "consecutive_no_hit_checks": next_count,
            "layer2_new_round_required": new_round_required,
        }
    return {
        "last_checker_outcome": kind,
        "consecutive_no_hit_checks": int(current.get("consecutive_no_hit_checks") or 0),
    }


def command_status(args: argparse.Namespace) -> int:
    ws = require_workspace(args)
    waiting = sorted((ws / "checker" / "waiting").glob("*.json"))
    layer2 = sorted((ws / "tasks" / "layer2").glob("*.json"))
    layer3_queued = sorted((ws / "tasks" / "layer3" / "queued").glob("*.json"))
    layer3_active = sorted((ws / "tasks" / "layer3" / "active").glob("*.json"))
    data = {
        "puzzle_id": slugify(args.puzzle_id),
        "workspace": str(ws),
        "waiting_checker_jobs": [path.stem for path in waiting],
        "layer2_tasks": len(layer2),
        "layer3_queued": len(layer3_queued),
        "layer3_active": len(layer3_active),
        "status": read_json(ws / "status" / "state.json") if (ws / "status" / "state.json").exists() else {},
    }
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--puzzle-id", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize an isolated puzzle workspace")
    add_common(init)
    init.add_argument("--name")
    init.add_argument("--target-address")
    init.add_argument("--target-kind", choices=["seed", "private-key", "raw-private-key", "wif", "unknown"])
    init.add_argument("--path-mode", default="auto", choices=["auto", "fixed", "common", "none"])
    init.add_argument("--path")
    init.add_argument("--target-notes")
    init.add_argument("--source-note", action="append")
    init.add_argument("--scope")
    init.add_argument("--no-overwrite", action="store_true")
    init.set_defaults(func=command_init)

    start_budget = sub.add_parser("start-budget", help="Start a Codex usage budget")
    start_budget.add_argument("--name", default="sleep")
    start_budget.add_argument("--max-weekly-delta-percent", type=float, default=10.0)
    start_budget.add_argument("--absolute-weekly-cap-percent", type=float)
    start_budget.add_argument("--reserve-percent-points", type=float, default=1.0)
    start_budget.set_defaults(func=command_start_budget)

    run_start = sub.add_parser("run-start", help="Start a durable sleep-mode puzzle run ledger and Codex budget")
    run_start.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    run_start.add_argument("--run-id")
    run_start.add_argument("--puzzle", action="append", required=True)
    run_start.add_argument("--budget-name", default="sleep")
    run_start.add_argument("--max-weekly-delta-percent", type=float, default=10.0)
    run_start.add_argument("--absolute-weekly-cap-percent", type=float)
    run_start.add_argument("--reserve-percent-points", type=float, default=1.0)
    run_start.set_defaults(func=command_run_start)

    run_status = sub.add_parser("run-status", help="Show sleep-mode run and budget status")
    run_status.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    run_status.add_argument("--run-id", required=True)
    run_status.set_defaults(func=command_run_status)

    guard = sub.add_parser("guard", help="Check a Codex usage budget")
    guard.add_argument("--budget-name", default="sleep")
    guard.set_defaults(func=command_guard)

    l2 = sub.add_parser("l2-task", help="Create a Layer 2 task packet")
    add_common(l2)
    l2.add_argument("--task-id")
    l2.add_argument("--created-by", default="master-codex")
    l2.add_argument("--direction", required=True)
    l2.add_argument("--question", required=True)
    l2.add_argument("--method-family", default="")
    l2.add_argument("--evidence", action="append")
    l2.add_argument("--stop-condition", action="append")
    l2.add_argument("--layer3-expected")
    l2.set_defaults(func=command_l2_task)

    l2_round = sub.add_parser("l2-round", help="Validate and record a Layer 2 council round")
    add_common(l2_round)
    l2_round.add_argument("--round-id")
    l2_round.add_argument("--proposal-file", required=True)
    l2_round.add_argument("--created-by", default="layer2-council")
    l2_round.add_argument("--trigger", choices=["manual", "scheduled", "no-hit", "new-eyes"], default="manual")
    l2_round.add_argument("--no-hit-streak", type=int)
    l2_round.set_defaults(func=command_l2_round)

    l2_round_template = sub.add_parser("l2-round-template", help="Create a Layer 2 round proposal skeleton")
    add_common(l2_round_template)
    l2_round_template.add_argument("--round-id")
    l2_round_template.add_argument("--trigger", choices=["manual", "scheduled", "no-hit", "new-eyes"], default="manual")
    l2_round_template.add_argument("--output")
    l2_round_template.set_defaults(func=command_l2_round_template)

    l3 = sub.add_parser("l3-task", help="Create a Layer 3 worker packet")
    add_common(l3)
    l3.add_argument("--task-id")
    l3.add_argument("--layer2-task-id", required=True)
    l3.add_argument("--round-id")
    l3.add_argument("--model-lane", required=True)
    l3.add_argument("--method-id")
    l3.add_argument("--variant-id")
    l3.add_argument("--method-family", default="")
    l3.add_argument("--direction", required=True)
    l3.add_argument("--objective", required=True)
    l3.add_argument("--novelty-summary", required=True)
    l3.add_argument("--similar-prior-method", action="append")
    l3.add_argument("--why-this-is-not-a-repeat", required=True)
    l3.add_argument("--failure-scope-if-no-hit", required=True)
    l3.add_argument("--reopen-condition", required=True)
    l3.add_argument("--allow-related-repeat", action="store_true")
    l3.add_argument("--input", action="append")
    l3.add_argument("--stop-condition", action="append")
    l3.add_argument("--checker-allowed", action="store_true")
    l3.set_defaults(func=command_l3_task)

    manifest = sub.add_parser("manifest", help="Create a candidate manifest")
    add_common(manifest)
    manifest.add_argument("--manifest-id")
    manifest.add_argument("--candidate-file", required=True)
    manifest.add_argument("--candidate-count", type=int, required=True)
    manifest.add_argument("--candidate-type", required=True, choices=["seed", "private-key", "translated-seed"])
    manifest.add_argument("--method-id", required=True)
    manifest.add_argument("--variant-id", required=True)
    manifest.add_argument("--content-id")
    manifest.add_argument("--generation-summary", required=True)
    manifest.add_argument("--evidence-reason", required=True)
    manifest.add_argument("--failure-scope-if-no-hit", required=True)
    manifest.add_argument("--hash-file", action="store_true")
    manifest.set_defaults(func=command_manifest)

    submit = sub.add_parser("checker-submit", help="Submit a manifest to the seedchecker scheduler and create wait-state")
    add_common(submit)
    submit.add_argument("--manifest-id", required=True)
    submit.add_argument("--layer2-task-id", required=True)
    submit.add_argument("--layer3-task-id", required=True)
    submit.add_argument("--submitting-agent", required=True)
    submit.add_argument("--model", default="")
    submit.add_argument("--request-id")
    submit.add_argument("--request-type", choices=["seed", "private-key", "translated-seed"])
    submit.add_argument("--target-address")
    submit.add_argument("--seed-standard", default="bip39")
    submit.add_argument("--path-mode", choices=["auto", "fixed", "common"])
    submit.add_argument("--path")
    submit.add_argument("--passphrase-mode", default="empty")
    submit.add_argument("--duplicate-policy", default="do-not-recheck-without-layer2-approval")
    submit.add_argument("--next-action-on-no-hit", required=True)
    submit.add_argument("--approved-over-16h", action="store_true")
    submit.add_argument("--budget-name")
    submit.add_argument("--seedchecker-home", type=Path, default=DEFAULT_SEEDCHECKER)
    submit.set_defaults(func=command_checker_submit)

    poll = sub.add_parser("checker-poll", help="Poll a checker wait-state and write result handoff when terminal")
    add_common(poll)
    poll.add_argument("--checker-job-id", required=True)
    poll.add_argument("--seedchecker-home", type=Path, default=DEFAULT_SEEDCHECKER)
    poll.set_defaults(func=command_checker_poll)

    status = sub.add_parser("status", help="Show puzzle workspace status")
    add_common(status)
    status.set_defaults(func=command_status)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

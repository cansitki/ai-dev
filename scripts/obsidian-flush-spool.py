#!/usr/bin/env python3
import argparse
import datetime as dt
import fcntl
import json
import os
import pathlib
import shutil
import subprocess
import sys
import uuid


HOME = pathlib.Path.home()
STATE_DIR = pathlib.Path(os.environ.get("OBSIDIAN_SPOOL_DIR", HOME / ".local/state/obsidian-cli"))
SPOOL_DIR = STATE_DIR / "spool"
DONE_DIR = STATE_DIR / "done"
FAILED_DIR = STATE_DIR / "failed"
LOCK_FILE = STATE_DIR / "flush.lock"
REAL = pathlib.Path(os.environ.get("OBSIDIAN_REAL", HOME / ".local/bin/obsidian-ipc"))
LOCAL_TZ = dt.timezone(dt.timedelta(hours=3), "Europe/Bucharest")


def ensure_state() -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    SPOOL_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    DONE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    FAILED_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    for directory in (STATE_DIR, SPOOL_DIR, DONE_DIR, FAILED_DIR):
        try:
            directory.chmod(0o700)
        except OSError:
            pass


def queue_append(argv: list[str], cwd: str, status: int) -> int:
    ensure_state()
    now = dt.datetime.now(LOCAL_TZ)
    payload = {
        "argv": argv,
        "cwd": cwd,
        "created_at": now.isoformat(),
        "local_date": now.strftime("%Y-%m-%d"),
        "reason": f"obsidian-ipc-status-{status}",
        "status": status,
    }
    name = f"{now.strftime('%Y%m%dT%H%M%S%z')}-{os.getpid()}-{uuid.uuid4().hex}.json"
    tmp = SPOOL_DIR / f".{name}.tmp"
    final = SPOOL_DIR / name
    with tmp.open("w", encoding="utf-8") as fh:
        os.chmod(tmp, 0o600)
        json.dump(payload, fh, ensure_ascii=False)
        fh.write("\n")
    tmp.rename(final)
    print(
        "obsidian: daily:append queued after IPC timeout/failure; "
        "it will be flushed by obsidian-flush-spool",
        file=sys.stderr,
    )
    return 0


def content_from_argv(argv: list[str]) -> str | None:
    for arg in argv:
        if arg.startswith("content="):
            return arg[len("content=") :]
    return None


def already_logged(argv: list[str], cwd: str, timeout_s: int) -> bool:
    content = content_from_argv(argv)
    if not content:
        return False
    try:
        result = subprocess.run(
            [str(REAL), "daily:read"],
            cwd=cwd if os.path.isdir(cwd) else str(HOME),
            text=True,
            capture_output=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and content in result.stdout


def run_real(argv: list[str], cwd: str, timeout_s: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [str(REAL), *argv],
            cwd=cwd if os.path.isdir(cwd) else str(HOME),
            text=True,
            capture_output=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess([str(REAL), *argv], 124, exc.stdout or "", exc.stderr or "")
    except OSError as exc:
        return subprocess.CompletedProcess([str(REAL), *argv], 127, "", str(exc))


def move_record(path: pathlib.Path, target_dir: pathlib.Path) -> None:
    target = target_dir / path.name
    if target.exists():
        target = target_dir / f"{path.stem}-{uuid.uuid4().hex}{path.suffix}"
    shutil.move(str(path), str(target))


def flush(max_items: int, timeout_s: int, quiet: bool) -> int:
    ensure_state()
    with LOCK_FILE.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0

        files = sorted(SPOOL_DIR.glob("*.json"))
        if max_items > 0:
            files = files[:max_items]

        failures = 0
        flushed = 0
        skipped = 0
        for path in files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                argv = payload["argv"]
                cwd = payload.get("cwd") or str(HOME)
            except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                failures += 1
                if not quiet:
                    print(f"obsidian-flush-spool: bad spool record {path.name}: {exc}", file=sys.stderr)
                move_record(path, FAILED_DIR)
                continue

            if not isinstance(argv, list) or not argv or argv[0] != "daily:append":
                failures += 1
                if not quiet:
                    print(f"obsidian-flush-spool: unsupported spool record {path.name}", file=sys.stderr)
                move_record(path, FAILED_DIR)
                continue

            if already_logged(argv, cwd, min(timeout_s, 10)):
                skipped += 1
                move_record(path, DONE_DIR)
                continue

            result = run_real(argv, cwd, timeout_s)
            if result.returncode == 0:
                flushed += 1
                move_record(path, DONE_DIR)
                continue

            failures += 1
            if not quiet:
                stderr = result.stderr.strip()
                print(
                    f"obsidian-flush-spool: flush failed for {path.name} "
                    f"with status {result.returncode}",
                    file=sys.stderr,
                )
                if stderr:
                    print(stderr, file=sys.stderr)
            break

        if not quiet:
            print(f"flushed={flushed} skipped={skipped} remaining={len(list(SPOOL_DIR.glob('*.json')))}")
        return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Queue and flush failed Obsidian daily append calls.")
    parser.add_argument("--queue", action="store_true", help="Queue the argv after -- instead of flushing.")
    parser.add_argument("--status", type=int, default=1, help="Original obsidian-ipc exit status.")
    parser.add_argument("--cwd", default=str(HOME), help="Original working directory.")
    parser.add_argument("--max-items", type=int, default=0, help="Maximum queued records to flush; 0 means all.")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout per Obsidian IPC command.")
    parser.add_argument("--quiet", action="store_true", help="Suppress normal flush output.")
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if args.queue:
        argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
        return queue_append(argv, args.cwd, args.status)

    return flush(args.max_items, args.timeout, args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())

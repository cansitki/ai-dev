#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/nomarh-p0-execution-board.py" "$HOME/.local/bin/nomarh-p0-execution-board"
"$HOME/.local/bin/nomarh-p0-execution-board" "$@"

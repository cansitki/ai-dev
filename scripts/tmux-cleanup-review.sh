#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/tmux-cleanup-review.py" "$HOME/.local/bin/tmux-cleanup-review"
"$HOME/.local/bin/tmux-cleanup-review" "$@"

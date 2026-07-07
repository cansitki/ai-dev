#!/usr/bin/env bash
set -Eeuo pipefail

export PATH="$HOME/.local/bin:$PATH"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$HOME/.local/bin"
install -m 0755 "$script_dir/control-plane-backup-readiness.py" "$HOME/.local/bin/control-plane-backup-readiness"

"$HOME/.local/bin/control-plane-backup-readiness"

#!/usr/bin/env bash
set -Eeuo pipefail

export PATH="$HOME/.local/bin:$PATH"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$HOME/.local/bin"
install -m 0755 "$script_dir/can-doctor.py" "$HOME/.local/bin/can-doctor"

"$HOME/.local/bin/can-doctor" || true

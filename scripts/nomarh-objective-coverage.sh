#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/nomarh-objective-coverage.py" "$HOME/.local/bin/nomarh-objective-coverage"
"$HOME/.local/bin/nomarh-objective-coverage" "$@"

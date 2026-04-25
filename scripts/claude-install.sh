#!/bin/bash
set -e

mkdir -p "$HOME/.local/bin"
export PATH="$HOME/.local/bin:$PATH"

# Install Claude Code if not present
if ! command -v claude &> /dev/null; then
  echo "Installing Claude Code..."
  # MUST use bash, not sh — Ubuntu's sh is dash which can't parse the installer
  if curl -fsSL https://claude.ai/install.sh | bash; then
    echo "Claude Code install script completed"
  else
    echo "WARNING: Claude Code installation failed, continuing..."
  fi
else
  echo "Claude Code already installed at $(command -v claude)"
fi

# Verify the binary exists
if command -v claude &> /dev/null; then
  echo "Claude Code ready: $(command -v claude)"
else
  echo "WARNING: Claude Code binary not found after install — may need manual installation"
fi

%{if claude_api_key != ""}
# API key is set via coder_agent env block — no need to persist to RC files
export ANTHROPIC_API_KEY="${claude_api_key}"
%{endif}

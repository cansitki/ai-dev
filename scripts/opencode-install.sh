#!/bin/bash
set -e

# Install OpenCode if not present
if ! command -v opencode &> /dev/null && [ ! -f "$HOME/.opencode/bin/opencode" ]; then
  echo "Installing OpenCode..."
  if curl -fsSL https://opencode.ai/install | bash; then
    echo "OpenCode installed successfully"
  else
    echo "WARNING: OpenCode installation failed, continuing..."
  fi
else
  echo "OpenCode already installed"
fi

# Write OpenCode config
mkdir -p "$HOME/.config/opencode"
echo '${opencode_config_json}' > "$HOME/.config/opencode/config.json"
echo "OpenCode configured"

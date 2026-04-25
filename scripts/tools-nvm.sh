#!/bin/bash
set -e

BOLD='\033[0;1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CODE='\033[36;40;1m'
RESET='\033[0m'

NVM_DIR="$HOME/.nvm"
NODE_VERSIONS=(${node_versions})
DEFAULT_VERSION="${default_node_version}"

# Install nvm if not present
if [ ! -s "$NVM_DIR/nvm.sh" ]; then
  printf "$${BOLD}[install] nvm...$${RESET}\n"
  curl -sS -o- https://raw.githubusercontent.com/nvm-sh/nvm/master/install.sh | bash 2>&1 || {
    printf "$${YELLOW}[warn] nvm installation failed, continuing...$${RESET}\n"
    exit 0
  }
  printf "$${GREEN}[ok] nvm installed$${RESET}\n\n"
else
  printf "$${GREEN}[ok] nvm already installed$${RESET}\n"
fi

# Load nvm
export NVM_DIR
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

if ! command -v nvm &>/dev/null; then
  printf "$${YELLOW}[warn] nvm not available after install, skipping node setup$${RESET}\n"
  exit 0
fi

# Install each node version
for version in "$${NODE_VERSIONS[@]}"; do
  [ -z "$version" ] && continue
  printf "Installing node $${CODE}$version$${RESET}...\n"
  if ! nvm install "$version" &>/dev/null; then
    printf "$${YELLOW}[warn] Failed to install node $version, continuing...$${RESET}\n"
  fi
done

# Set default version
if [ -n "$DEFAULT_VERSION" ]; then
  printf "Setting default node $${CODE}$DEFAULT_VERSION$${RESET}...\n"
  nvm alias default "$DEFAULT_VERSION" &>/dev/null || true
fi

printf "$${GREEN}[ok] Node.js versions ready$${RESET}\n"

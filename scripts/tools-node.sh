#!/bin/bash
set -e

BOLD='\033[0;1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RESET='\033[0m'

command_exists() {
  command -v "$1" &> /dev/null
}

install_if_missing() {
  local name=$1
  local check_cmd=$2
  local check_path=$3
  local install_cmd=$4

  if [ -n "$check_cmd" ] && command_exists "$check_cmd"; then
    printf "$${GREEN}[ok] $name already installed$${RESET}\n"
    return 0
  elif [ -n "$check_path" ] && [ -e "$check_path" ]; then
    printf "$${GREEN}[ok] $name already installed$${RESET}\n"
    return 0
  fi

  printf "$${BOLD}[install] $name...$${RESET}\n"
  if eval "$install_cmd"; then
    printf "$${GREEN}[ok] $name installed successfully$${RESET}\n\n"
  else
    printf "$${YELLOW}[warn] $name installation failed, continuing...$${RESET}\n\n"
  fi
}

# Install PNPM
install_if_missing "PNPM" "pnpm" "" '
  curl -fsSL https://get.pnpm.io/install.sh | sh -
'

# Install Yarn (corepack is enabled in the Dockerfile)
install_if_missing "Yarn" "yarn" "" '
  corepack prepare yarn@stable --activate
'

# Install Bun
install_if_missing "Bun" "bun" "" '
  curl -fsSL https://bun.sh/install | bash
'

# Ensure Bun is on PATH
if ! grep -q "BUN_INSTALL" $HOME/.zshrc 2>/dev/null; then
  echo 'export BUN_INSTALL="$HOME/.bun"' >> $HOME/.zshrc
  echo 'export PATH="$BUN_INSTALL/bin:$PATH"' >> $HOME/.zshrc
fi

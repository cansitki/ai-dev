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

# Install act (GitHub Actions locally)
install_if_missing "act" "act" "" '
  wget -qO /tmp/act.tar.gz https://github.com/nektos/act/releases/latest/download/act_Linux_x86_64.tar.gz &&
  sudo tar xf /tmp/act.tar.gz -C /usr/local/bin act &&
  rm /tmp/act.tar.gz
'

# Install GitHub CLI
install_if_missing "GitHub CLI" "gh" "" '
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg &&
  sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg &&
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null &&
  sudo apt-get update &&
  sudo apt-get install gh -y
'

# Configure GitHub CLI authentication using Coder external auth token
if command_exists gh && [ -n "${github_token}" ]; then
  if ! gh auth status &>/dev/null; then
    printf "$${BOLD}Configuring GitHub CLI authentication...$${RESET}\n"
    echo "${github_token}" | gh auth login --with-token
    printf "$${GREEN}[ok] GitHub CLI authenticated$${RESET}\n\n"
  else
    printf "$${GREEN}[ok] GitHub CLI already authenticated$${RESET}\n\n"
  fi
fi

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

# Install Oh My Zsh (without powerlevel10k — we use Starship)
install_if_missing "Oh My Zsh" "" "$HOME/.oh-my-zsh" '
  RUNZSH=no CHSH=no sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended &&
  git clone --quiet https://github.com/zsh-users/zsh-autosuggestions.git $HOME/.oh-my-zsh/custom/plugins/zsh-autosuggestions &&
  git clone --quiet https://github.com/zsh-users/zsh-syntax-highlighting.git $HOME/.oh-my-zsh/custom/plugins/zsh-syntax-highlighting &&
  git clone --quiet https://github.com/zsh-users/zsh-completions.git $HOME/.oh-my-zsh/custom/plugins/zsh-completions &&
  sed -i "s|^ZSH_THEME.*|ZSH_THEME=\"\"|g" $HOME/.zshrc &&
  sed -i "s|^plugins=.*|plugins=(git docker docker-compose zsh-autosuggestions zsh-syntax-highlighting zsh-completions direnv tmux)|g" $HOME/.zshrc
'

# Install Starship prompt
install_if_missing "Starship" "starship" "" '
  curl -sS https://starship.rs/install.sh | sh -s -- --yes
'

# Configure Starship — hide [Docker] container indicator
mkdir -p "$HOME/.config"
if [ ! -f "$HOME/.config/starship.toml" ]; then
  cat > "$HOME/.config/starship.toml" << 'STARSHIPEOF'
[container]
disabled = true
STARSHIPEOF
fi

# Remove Oh My Zsh git plugin aliases that conflict with our tools
# Place in custom/ dir so it loads AFTER plugins (including git plugin)
mkdir -p "$HOME/.oh-my-zsh/custom"
echo 'unalias gsd 2>/dev/null' > "$HOME/.oh-my-zsh/custom/unalias-gsd.zsh"

# Append shell config only if not already present (idempotency guard)
if ! grep -q '# Custom aliases' "$HOME/.zshrc" 2>/dev/null; then
  cat >> $HOME/.zshrc << 'ZSHEOF'

# Custom aliases
alias d="docker"
alias dc="docker-compose"
alias g="git"
alias gs="git status"
alias gp="git pull"
alias gc="git commit"
alias gco="git checkout"
alias ll="ls -lah"

# Direnv hook
eval "$(direnv hook zsh)"

# Starship prompt
eval "$(starship init zsh)"
ZSHEOF
fi

exit 0

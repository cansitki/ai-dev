terraform {
  required_providers {
    coder = {
      source = "coder/coder"
    }
    docker = {
      source = "kreuzwerker/docker"
    }
  }
}

locals {
  username = data.coder_workspace_owner.me.name
}

# =============================================================================
# Variables
# =============================================================================

variable "docker_socket" {
  description = "(Optional) Docker socket URI"
  type        = string
  default     = ""
}

variable "dotfiles_uri" {
  description = "Git URI for dotfiles repository (optional)"
  type        = string
  default     = ""
}

# --- OpenCode Configuration ---

variable "opencode_model" {
  description = "Default model for OpenCode"
  type        = string
  default     = "anthropic/claude-opus-4-6"
}

variable "opencode_config_json" {
  description = "Full OpenCode config JSON override (takes precedence over opencode_model when non-empty)"
  type        = string
  default     = ""
}

# --- Claude Code Configuration ---

variable "claude_code_model" {
  description = "Default model for Claude Code (e.g. sonnet, opus, or full model name)"
  type        = string
  default     = ""
}

variable "claude_code_api_key" {
  description = "Anthropic API key for Claude Code (leave empty to use AI Bridge or external auth)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "claude_code_system_prompt" {
  description = "Custom system prompt for Claude Code"
  type        = string
  default     = ""
}

variable "claude_code_allowed_tools" {
  description = "Comma-separated list of allowed tools for Claude Code"
  type        = string
  default     = ""
}

# --- Pi Coding Agent Configuration ---

variable "pi_api_key" {
  description = "API key for Pi coding agent LLM provider (e.g. Anthropic key)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "pi_model" {
  description = "Model for Pi coding agent (e.g. claude-opus-4-6)"
  type        = string
  default     = "claude-opus-4-6"
}

variable "pi_provider" {
  description = "LLM provider for Pi coding agent (e.g. anthropic, openai, google)"
  type        = string
  default     = "anthropic"
}

# =============================================================================
# Providers & Data Sources
# =============================================================================

provider "docker" {
  host = var.docker_socket != "" ? var.docker_socket : null
}

data "coder_provisioner" "me" {}
data "coder_workspace" "me" {}
data "coder_workspace_owner" "me" {}

# =============================================================================
# External Auth
# =============================================================================

# data "coder_external_auth" "github" {
#   id = "primary-github"
# }

# =============================================================================
# Coder Agent
# =============================================================================

resource "coder_agent" "main" {
  arch = data.coder_provisioner.me.arch
  os   = "linux"

  startup_script = templatefile("${path.module}/scripts/init.sh", {
    dotfiles_uri   = var.dotfiles_uri
    workspace_name = data.coder_workspace.me.name
    owner_name     = data.coder_workspace_owner.me.name
    owner_email    = data.coder_workspace_owner.me.email
  })

  env = merge(
    {
      GIT_AUTHOR_NAME     = coalesce(data.coder_workspace_owner.me.full_name, data.coder_workspace_owner.me.name)
      GIT_AUTHOR_EMAIL    = "${data.coder_workspace_owner.me.email}"
      GIT_COMMITTER_NAME  = coalesce(data.coder_workspace_owner.me.full_name, data.coder_workspace_owner.me.name)
      GIT_COMMITTER_EMAIL = "${data.coder_workspace_owner.me.email}"

      EXTENSIONS_GALLERY = "{\"serviceUrl\":\"https://marketplace.visualstudio.com/_apis/public/gallery\"}"
    },
    var.claude_code_api_key != "" ? { ANTHROPIC_API_KEY = var.claude_code_api_key } : {}
  )

  metadata {
    display_name = "CPU Usage"
    key          = "0_cpu_usage"
    script       = "coder stat cpu"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "RAM Usage"
    key          = "1_ram_usage"
    script       = "coder stat mem"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "Home Disk"
    key          = "3_home_disk"
    script       = "coder stat disk --path $${HOME}"
    interval     = 60
    timeout      = 1
  }

  metadata {
    display_name = "CPU Usage (Host)"
    key          = "4_cpu_usage_host"
    script       = "coder stat cpu --host"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "Memory Usage (Host)"
    key          = "5_mem_usage_host"
    script       = "coder stat mem --host"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "Load Average (Host)"
    key          = "6_load_host"
    script   = <<EOT
      echo "`cat /proc/loadavg | awk '{ print $1 }'` `nproc`" | awk '{ printf "%0.2f", $1/$2 }'
    EOT
    interval = 60
    timeout  = 1
  }

  metadata {
    display_name = "Swap Usage (Host)"
    key          = "7_swap_host"
    script       = <<EOT
      free -b | awk '/^Swap/ { printf("%.1f/%.1f", $3/1024.0/1024.0/1024.0, $2/1024.0/1024.0/1024.0) }'
    EOT
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "Workspace Size"
    key          = "10_workspace_size"
    script       = "du -sh /home/coder 2>/dev/null | cut -f1 || echo 'N/A'"
    interval     = 300
    timeout      = 10
  }
}

# =============================================================================
# Development Tools (separate scripts for clarity)
# =============================================================================

resource "coder_script" "tools_shell" {
  agent_id           = coder_agent.main.id
  display_name       = "Shell & Prompt"
  icon               = "/icon/terminal.svg"
  run_on_start       = true
  start_blocks_login = true
  script             = file("${path.module}/scripts/tools-shell.sh")
}

resource "coder_script" "tools_node" {
  agent_id           = coder_agent.main.id
  display_name       = "Node.js Package Managers"
  icon               = "/icon/nodejs.svg"
  run_on_start       = true
  start_blocks_login = true
  script             = file("${path.module}/scripts/tools-node.sh")
}

resource "coder_script" "tools_web3" {
  agent_id           = coder_agent.main.id
  display_name       = "Web3 Tools"
  icon               = "/icon/terminal.svg"
  run_on_start       = true
  start_blocks_login = true
  script             = file("${path.module}/scripts/tools-web3.sh")
}

resource "coder_script" "tools_ci" {
  agent_id           = coder_agent.main.id
  display_name       = "CI/CD Tools"
  icon               = "/icon/terminal.svg"
  run_on_start       = true
  start_blocks_login = true
  script = templatefile("${path.module}/scripts/tools-ci.sh", {
    github_token = ""
  })
}

resource "coder_script" "projects_bootstrap" {
  agent_id           = coder_agent.main.id
  display_name       = "Project Bootstrap"
  icon               = "/icon/git.svg"
  run_on_start       = true
  start_blocks_login = false
  script             = file("${path.module}/scripts/projects-bootstrap.sh")
}

resource "coder_script" "vault_github_backup" {
  agent_id           = coder_agent.main.id
  display_name       = "Vault GitHub Backup"
  icon               = "/icon/git.svg"
  run_on_start       = true
  start_blocks_login = false
  script             = file("${path.module}/scripts/vault-github-backup-loop.sh")
}

resource "coder_script" "tools_ai" {
  agent_id           = coder_agent.main.id
  display_name       = "AI Tools"
  icon               = "/icon/terminal.svg"
  run_on_start       = true
  start_blocks_login = true
  script = templatefile("${path.module}/scripts/tools-ai.sh", {
    pi_api_key  = var.pi_api_key
    pi_provider = var.pi_provider
    pi_model    = var.pi_model
  })
}

resource "coder_script" "codex_usage_guard" {
  agent_id           = coder_agent.main.id
  display_name       = "Codex & Puzzle Guards"
  icon               = "/icon/terminal.svg"
  run_on_start       = true
  start_blocks_login = false
  script             = <<-EOT
    #!/bin/bash
    set -euo pipefail
    mkdir -p "$HOME/.local/bin"
    cat > "$HOME/.local/bin/codex-usage-guard" <<'PY'
${file("${path.module}/scripts/codex-usage-guard.py")}
PY
    chmod +x "$HOME/.local/bin/codex-usage-guard"
    cat > "$HOME/.local/bin/puzzle-swarm" <<'PY'
${file("${path.module}/scripts/puzzle-swarm.py")}
PY
    chmod +x "$HOME/.local/bin/puzzle-swarm"
    echo "Installed codex-usage-guard and puzzle-swarm"
  EOT
}

resource "coder_script" "symlinks" {
  agent_id           = coder_agent.main.id
  display_name       = "Tool Symlinks"
  icon               = "/icon/terminal.svg"
  run_on_start       = true
  start_blocks_login = true
  script             = file("${path.module}/scripts/symlinks.sh")
}

resource "coder_script" "obsidian_serve" {
  agent_id           = coder_agent.main.id
  display_name       = "Obsidian (headless)"
  icon               = "/icon/folder.svg"
  run_on_start       = true
  start_blocks_login = false
  script             = file("${path.module}/scripts/obsidian-serve.sh")
}

resource "coder_script" "openclaw_install" {
  agent_id           = coder_agent.main.id
  display_name       = "OpenClaw Install"
  icon               = "/icon/terminal.svg"
  run_on_start       = true
  start_blocks_login = false
  script             = file("${path.module}/scripts/openclaw-install.sh")
}

resource "coder_script" "openclaw_gateway" {
  agent_id           = coder_agent.main.id
  display_name       = "OpenClaw Gateway"
  icon               = "/icon/terminal.svg"
  run_on_start       = true
  start_blocks_login = false
  script             = file("${path.module}/scripts/openclaw-gateway-serve.sh")
}

resource "coder_script" "workspace_r2_raw_backup" {
  agent_id           = coder_agent.main.id
  display_name       = "Workspace R2 Raw Backup"
  icon               = "/icon/database.svg"
  run_on_start       = true
  start_blocks_login = false
  script             = file("${path.module}/scripts/workspace-r2-raw-backup-loop.sh")
}

resource "coder_script" "ttyd_serve" {
  agent_id           = coder_agent.main.id
  display_name       = "Tmux Picker (ttyd)"
  icon               = "/icon/terminal.svg"
  run_on_start       = true
  start_blocks_login = false
  script             = file("${path.module}/scripts/ttyd-serve.sh")
}

resource "coder_script" "optimize_runtime" {
  agent_id           = coder_agent.main.id
  display_name       = "Runtime Optimizations"
  icon               = "/icon/terminal.svg"
  run_on_start       = true
  start_blocks_login = false
  script             = file("${path.module}/scripts/optimize-runtime.sh")
}

resource "coder_script" "discord_bot" {
  agent_id           = coder_agent.main.id
  display_name       = "Discord Bot"
  icon               = "/icon/terminal.svg"
  run_on_start       = true
  start_blocks_login = false
  script             = file("${path.module}/scripts/discord-bot-serve.sh")
}

# =============================================================================
# VS Code Server
# =============================================================================

module "code-server" {
  count   = data.coder_workspace.me.start_count
  source  = "registry.coder.com/modules/code-server/coder"
  version = "1.2.0"

  agent_id              = coder_agent.main.id
  order                 = 1
  subdomain             = true
  use_cached_extensions = true

  extensions = [
    "binary-ink.dark-modern-oled-theme-set",
    "pkief.material-icon-theme",
    "prisma.prisma",
    "graphql.vscode-graphql",
    "graphql.vscode-graphql-syntax",
    "bradlc.vscode-tailwindcss",
    "tintinweb.vscode-solidity-language",
    "nomicfoundation.hardhat-solidity",
    "esbenp.prettier-vscode",
    "eamodio.gitlens",
    "oderwat.indent-rainbow",
    "gruntfuggly.todo-tree",
    "pflannery.vscode-versionlens",
    "ms-vsliveshare.vsliveshare",
    "hashicorp.terraform",
    "ms-azuretools.vscode-docker",
    "cweijan.vscode-postgresql-client2",
    "usernamehw.errorlens",
    "streetsidesoftware.code-spell-checker",
    "wayou.vscode-todo-highlight",
  ]

  settings = {
    # Solidity
    "[solidity]" : {
      "editor.defaultFormatter" : "esbenp.prettier-vscode",
      "editor.formatOnSave" : true
    },
    "solidity.telemetry" : false,

    # Editor
    "editor.defaultFormatter" : "esbenp.prettier-vscode",
    "editor.fontFamily" : "Fira Code",
    "editor.fontLigatures" : true,
    "editor.formatOnSave" : true,
    "editor.wordWrap" : "on",
    "editor.inlineSuggest.enabled" : true,
    "editor.bracketPairColorization.enabled" : true,
    "editor.guides.bracketPairs" : true,
    "editor.minimap.enabled" : false,
    "editor.stickyScroll.enabled" : true,
    "editor.tabSize" : 2,

    # Files
    "files.autoSave" : "off",
    "files.watcherExclude" : {
      "**/.git/objects/**" : true,
      "**/.git/subtree-cache/**" : true,
      "**/node_modules/**" : true,
      "**/.hg/store/**" : true,
      "**/dist/**" : true,
      "**/build/**" : true,
      "**/.next/**" : true,
      "**/out/**" : true,
    },

    # Git
    "git.confirmSync" : false,
    "git.autofetch" : true,
    "git.enableSmartCommit" : true,

    # Terminal
    "terminal.integrated.scrollback" : 10000,
    "terminal.integrated.defaultProfile.linux" : "zsh",
    "terminal.integrated.fontSize" : 14,

    # Workbench
    "workbench.colorTheme" : "Dark Modern (OLED Black) [Orange]",
    "workbench.iconTheme" : "material-icon-theme",

    # Explorer
    "explorer.confirmDelete" : false,
    "explorer.confirmDragAndDrop" : false,

    # Docker
    "docker.showStartPage" : false,
  }
}

# =============================================================================
# OpenCode
# =============================================================================

resource "coder_script" "opencode_install" {
  agent_id           = coder_agent.main.id
  display_name       = "OpenCode Install"
  icon               = "/icon/opencode.svg"
  run_on_start       = true
  start_blocks_login = true
  script = templatefile("${path.module}/scripts/opencode-install.sh", {
    opencode_config_json = var.opencode_config_json != "" ? var.opencode_config_json : jsonencode({
      "$schema" = "https://opencode.ai/config.json"
      permission = {
        skill = {
          "*"              = "allow"
          "pr-review"      = "allow"
          "internal-*"     = "deny"
          "experimental-*" = "ask"
        }
      }
      model = var.opencode_model
    })
  })
}

resource "coder_app" "opencode_terminal" {
  agent_id     = coder_agent.main.id
  slug         = "opencode-terminal"
  display_name = "OpenCode"
  icon         = "/icon/opencode.svg"
  command      = "bash -l -c 'export PATH=\"$HOME/.opencode/bin:$PATH\" && opencode'"
  share        = "owner"
}

resource "coder_app" "opencode_ui" {
  agent_id     = coder_agent.main.id
  slug         = "opencode-ui"
  display_name = "OpenCode UI"
  url          = "http://localhost:62748"
  icon         = "/icon/opencode.svg"
  subdomain    = true
  share        = "owner"
}

resource "coder_script" "opencode_serve" {
  agent_id           = coder_agent.main.id
  display_name       = "OpenCode Serve"
  icon               = "/icon/opencode.svg"
  run_on_start       = true
  start_blocks_login = false
  script             = file("${path.module}/scripts/opencode-serve.sh")
}

# =============================================================================
# Claude Code
# =============================================================================

resource "coder_script" "claude_code_install" {
  agent_id           = coder_agent.main.id
  display_name       = "Claude Code Install"
  icon               = "/icon/claude.svg"
  run_on_start       = true
  start_blocks_login = true
  script = templatefile("${path.module}/scripts/claude-install.sh", {
    claude_api_key = var.claude_code_api_key
  })
}

resource "coder_app" "claude_code" {
  agent_id     = coder_agent.main.id
  slug         = "claude-code"
  display_name = "Claude Code"
  icon         = "/icon/claude.svg"
  command      = "bash -l -c 'export PATH=\"$HOME/.local/bin:$PATH\" && claude'"
  share        = "owner"
}

# =============================================================================
# Pi Coding Agent
# =============================================================================

resource "coder_app" "pi" {
  agent_id     = coder_agent.main.id
  slug         = "pi"
  display_name = "Pi Agent"
  icon         = "/icon/terminal.svg"
  command      = "bash -l -c 'export PATH=\"$HOME/.local/bin:$PATH\" && pi'"
  share        = "owner"
}

resource "coder_app" "gsd" {
  agent_id     = coder_agent.main.id
  slug         = "gsd"
  display_name = "GSD"
  icon         = "/icon/terminal.svg"
  command      = "bash -l -c 'export PATH=\"$HOME/.local/bin:$PATH\" && gsd'"
  share        = "owner"
}

# Quick terminal launchers for inspecting historical resource usage.
resource "coder_app" "sysstat_cpu" {
  agent_id     = coder_agent.main.id
  slug         = "sar-cpu"
  display_name = "sar — CPU history"
  icon         = "/icon/terminal.svg"
  command      = "bash -l -c 'sar -u | less'"
  share        = "owner"
}

resource "coder_app" "sysstat_ram" {
  agent_id     = coder_agent.main.id
  slug         = "sar-ram"
  display_name = "sar — RAM history"
  icon         = "/icon/terminal.svg"
  command      = "bash -l -c 'sar -r | less'"
  share        = "owner"
}

# Obsidian VNC — for one-time Sync login and any visual editing.
# x11vnc binds to :5999 inside the workspace; Coder forwards that port.
resource "coder_app" "obsidian_vnc" {
  agent_id     = coder_agent.main.id
  slug         = "obsidian-vnc"
  display_name = "Obsidian VNC"
  icon         = "/icon/folder.svg"
  # noVNC + websockify bridge serves the VNC GUI over HTTP at 6080.
  # subdomain=true so Coder routes via wildcard host (works with WebSockets,
  # which path-based proxying mangles). Requires CODER_WILDCARD_ACCESS_URL
  # set on the Coder server (e.g. *.dev.bmu.one).
  url       = "http://localhost:6080/"
  subdomain = true
  share     = "owner"
}

resource "coder_app" "openclaw_gateway" {
  agent_id     = coder_agent.main.id
  slug         = "openclaw"
  display_name = "OpenClaw"
  icon         = "/icon/terminal.svg"
  url          = "http://localhost:18789"
  subdomain    = true
  share        = "owner"
}

# Browser-accessible tmux session picker (ttyd on :7681).
resource "coder_app" "tmux_picker" {
  agent_id     = coder_agent.main.id
  slug         = "tmux"
  display_name = "Tmux"
  icon         = "/icon/terminal.svg"
  url          = "http://localhost:7681"
  subdomain    = true
  share        = "owner"
}

# =============================================================================
# File Browser
# =============================================================================

module "filebrowser" {
  count    = data.coder_workspace.me.start_count
  source   = "registry.coder.com/coder/filebrowser/coder"
  version  = "1.1.2"
  agent_id = coder_agent.main.id
}

# =============================================================================
# GitHub Integration
# =============================================================================

# Disabled: requires GitHub OAuth ('primary-github' external auth) to be
# set up on the Coder server first. Re-enable once OAuth is configured:
#   1. Create OAuth app at github.com/settings/developers
#   2. Configure in Coder: Admin Settings → External Auth → New Provider
#      ID = primary-github, Client ID/Secret from the OAuth app
#   3. Uncomment the block below and re-push the template.
#
# module "github-upload-public-key" {
#   count            = data.coder_workspace.me.start_count
#   source           = "registry.coder.com/coder/github-upload-public-key/coder"
#   version          = "1.0.15"
#   agent_id         = coder_agent.main.id
#   external_auth_id = "primary-github"
# }

module "git-commit-signing" {
  count    = data.coder_workspace.me.start_count
  source   = "registry.coder.com/coder/git-commit-signing/coder"
  version  = "1.0.11"
  agent_id = coder_agent.main.id
}

module "git-config" {
  count    = data.coder_workspace.me.start_count
  source   = "registry.coder.com/coder/git-config/coder"
  version  = "1.0.15"
  agent_id = coder_agent.main.id
}

# =============================================================================
# Node.js
# =============================================================================

resource "coder_script" "tools_nvm" {
  agent_id           = coder_agent.main.id
  display_name       = "Node.js (nvm)"
  icon               = "/icon/nodejs.svg"
  run_on_start       = true
  start_blocks_login = true
  script = templatefile("${path.module}/scripts/tools-nvm.sh", {
    node_versions        = join(" ", ["18", "20", "22", "24", "node"])
    default_node_version = "24"
  })
}

# =============================================================================
# Docker Resources
# =============================================================================

resource "docker_volume" "home_volume" {
  name = "coder-${data.coder_workspace.me.id}-home"

  lifecycle {
    ignore_changes = all
  }

  labels {
    label = "coder.owner"
    value = data.coder_workspace_owner.me.name
  }
  labels {
    label = "coder.owner_id"
    value = data.coder_workspace_owner.me.id
  }
  labels {
    label = "coder.workspace_id"
    value = data.coder_workspace.me.id
  }
  labels {
    label = "coder.workspace_name_at_creation"
    value = data.coder_workspace.me.name
  }
}

resource "docker_image" "main" {
  name = "coder-${data.coder_workspace.me.id}"
  build {
    context = "."
  }
  triggers = {
    dir_sha1 = sha1(join("", [for f in fileset(path.module, "Dockerfile") : filesha1(f)]))
  }
}

resource "docker_container" "workspace" {
  count    = data.coder_workspace.me.start_count
  image    = docker_image.main.name
  name     = "coder-${data.coder_workspace_owner.me.name}-${lower(data.coder_workspace.me.name)}"
  hostname = data.coder_workspace.me.name

  entrypoint = ["sh", "-c", replace(coder_agent.main.init_script, "/localhost|127\\.0\\.0\\.1/", "host.docker.internal")]
  env        = ["CODER_AGENT_TOKEN=${coder_agent.main.token}"]

  host {
    host = "host.docker.internal"
    ip   = "host-gateway"
  }

  # Resource limits: 12GB RAM, 20GB swap (32GB total), 6 CPU cores
  memory      = 12288
  memory_swap = 32768
  cpu_shares  = 6144

  # tmpfs /tmp — build artifacts and scratch files stay in RAM (capped at 2GB),
  # auto-cleared on container restart. Stops /tmp from filling the home volume
  # over months of use. `exec` is required because the Coder agent script
  # downloads its binary into /tmp and runs it; Docker tmpfs mounts default
  # to noexec which blocks that.
  tmpfs = {
    "/tmp" = "size=2g,mode=1777,exec"
  }

  # seccomp=unconfined relaxes the Docker default seccomp profile. Required
  # for Chromium/Electron processes (Obsidian, the obsidian-cli helper,
  # Claude Code internals, Playwright, Puppeteer) to set up their user
  # namespace sandboxes. Without this, those tools die with SIGTRAP on
  # "Failed to move to new namespace ... Operation not permitted".
  security_opts = ["seccomp=unconfined"]

  # Note: inotify watcher limits (fs.inotify.max_user_watches and
  # max_user_instances) are not namespaced in the default Linux kernel,
  # so Docker rejects them as per-container sysctls. They must be set
  # on the HOST instead, in /etc/sysctl.d/99-inotify.conf:
  #   fs.inotify.max_user_watches = 524288
  #   fs.inotify.max_user_instances = 1024
  # The host's settings apply to all containers automatically.

  # Home directory volume
  volumes {
    container_path = "/home/coder"
    volume_name    = docker_volume.home_volume.name
    read_only      = false
  }

  # Docker socket for full Docker functionality
  volumes {
    container_path = "/var/run/docker.sock"
    host_path      = "/var/run/docker.sock"
    read_only      = false
  }

  # Obsidian Desktop runs INSIDE each workspace now (see scripts/obsidian-serve.sh).
  # Vault, CLI, D-Bus socket, and Sync state all live in the home_volume —
  # no host mounts needed for Obsidian. First-time Sync login is done via the
  # "Obsidian VNC" Coder app.

  # Health check — verify the coder agent process is running
  healthcheck {
    test         = ["CMD-SHELL", "pgrep -x coder > /dev/null || pgrep -f 'coder agent' > /dev/null"]
    interval     = "30s"
    timeout      = "5s"
    retries      = 5
    start_period = "60s"
  }

  labels {
    label = "coder.owner"
    value = data.coder_workspace_owner.me.name
  }
  labels {
    label = "coder.owner_id"
    value = data.coder_workspace_owner.me.id
  }
  labels {
    label = "coder.workspace_id"
    value = data.coder_workspace.me.id
  }
  labels {
    label = "coder.workspace_name"
    value = data.coder_workspace.me.name
  }
  labels {
    label = "coder.template_version"
    value = "1.2.0"
  }
}

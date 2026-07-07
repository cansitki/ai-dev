terraform {
  required_providers {
    coder = {
      source  = "coder/coder"
      version = ">= 2.4.0"
    }
    docker = {
      source = "kreuzwerker/docker"
    }
  }
}

locals {
  username = data.coder_workspace_owner.me.name

  bootstrap_parameters = {
    claude_code_api_key                = { display_name = "Claude Code API key", description = "Anthropic API key for Claude Code", default = "", order = 100, form_type = "input", mask = true }
    openai_api_key                     = { display_name = "OpenAI API key", description = "OpenAI API key for Codex/OpenAI-backed tools", default = "", order = 120, form_type = "input", mask = true }
    github_token                       = { display_name = "GitHub token", description = "GitHub token for gh, private repos, and vault backup pushes", default = "", order = 130, form_type = "input", mask = true }
    remotely_save_s3_access_key_id     = { display_name = "Remotely Save S3 access key ID", description = "Obsidian Remotely Save S3 access key ID", default = "", order = 300, form_type = "input", mask = true }
    remotely_save_s3_secret_access_key = { display_name = "Remotely Save S3 secret access key", description = "Obsidian Remotely Save S3 secret access key", default = "", order = 310, form_type = "input", mask = true }
    remotely_save_s3_bucket            = { display_name = "Remotely Save S3 bucket", description = "Obsidian Remotely Save S3 bucket", default = "", order = 320, form_type = "input", mask = false }
    remotely_save_s3_endpoint          = { display_name = "Remotely Save S3 endpoint", description = "Obsidian Remotely Save S3 endpoint", default = "", order = 330, form_type = "input", mask = false }
    remotely_save_s3_region            = { display_name = "Remotely Save S3 region", description = "Obsidian Remotely Save S3 region, usually auto for R2", default = "auto", order = 340, form_type = "input", mask = false }
    remotely_save_remote_prefix        = { display_name = "Remotely Save remote prefix", description = "Optional Obsidian Remotely Save remote prefix", default = "", order = 350, form_type = "input", mask = false }
    cloudflare_api_token               = { display_name = "Cloudflare API token", description = "Cloudflare API token for tunnels, DNS, R2, workers, and migrations", default = "", order = 400, form_type = "input", mask = true }
    cloudflare_account_id              = { display_name = "Cloudflare account ID", description = "Cloudflare account ID", default = "", order = 410, form_type = "input", mask = false }
    cloudflare_zone_id                 = { display_name = "Cloudflare zone ID", description = "Cloudflare zone ID for dev.bmu.one/bmu.one automation", default = "", order = 420, form_type = "input", mask = false }
    cloudflare_kv_theme_namespace_id   = { display_name = "Theme KV namespace ID", description = "Cloudflare KV namespace ID used by the tmux theme sync worker", default = "", order = 430, form_type = "input", mask = false }
    tmux_theme_sync_url                = { display_name = "Tmux theme sync URL", description = "Cloudflare Worker URL for tmux/Codex theme sync", default = "https://theme.nomarh.com", order = 435, form_type = "input", mask = false }
    tmux_theme_sync_enabled            = { display_name = "Enable tmux theme sync", description = "Set false to install theme tools without auto-following the shared Worker theme", default = "true", order = 438, form_type = "input", mask = false }
    tmux_theme_sync_token              = { display_name = "Tmux theme sync token", description = "Shared token for the tmux theme sync service", default = "", order = 440, form_type = "input", mask = true }
    resend_api_key                     = { display_name = "Resend API key", description = "Resend API key for email tooling", default = "", order = 800, form_type = "input", mask = true }
    mailgun_api_key                    = { display_name = "Mailgun API key", description = "Mailgun API key for email tooling", default = "", order = 810, form_type = "input", mask = true }
    aws_access_key_id                  = { display_name = "AWS access key ID", description = "AWS access key ID for SES/S3/email tooling", default = "", order = 820, form_type = "input", mask = true }
    aws_secret_access_key              = { display_name = "AWS secret access key", description = "AWS secret access key for SES/S3/email tooling", default = "", order = 830, form_type = "input", mask = true }
  }

  bootstrap_values = {
    for key, parameter in data.coder_parameter.bootstrap : key => parameter.value
  }

  claude_code_api_key_value = local.bootstrap_values.claude_code_api_key != "" ? local.bootstrap_values.claude_code_api_key : var.claude_code_api_key
  bootstrap_env = {
    for env_name, value in {
      GITHUB_TOKEN                       = local.bootstrap_values.github_token
      GH_TOKEN                           = local.bootstrap_values.github_token
      OPENAI_API_KEY                     = local.bootstrap_values.openai_api_key
      ANTHROPIC_API_KEY                  = local.claude_code_api_key_value
      CLOUDFLARE_API_TOKEN               = local.bootstrap_values.cloudflare_api_token
      CLOUDFLARE_ACCOUNT_ID              = local.bootstrap_values.cloudflare_account_id
      CLOUDFLARE_ZONE_ID                 = local.bootstrap_values.cloudflare_zone_id
      CLOUDFLARE_KV_THEME_NAMESPACE_ID   = local.bootstrap_values.cloudflare_kv_theme_namespace_id
      TMUX_THEME_SYNC_URL                = local.bootstrap_values.tmux_theme_sync_url
      TMUX_THEME_SYNC_ENABLED            = local.bootstrap_values.tmux_theme_sync_enabled
      TMUX_THEME_SYNC_TOKEN              = local.bootstrap_values.tmux_theme_sync_token
      REMOTELY_SAVE_S3_ACCESS_KEY_ID     = local.bootstrap_values.remotely_save_s3_access_key_id
      REMOTELY_SAVE_S3_SECRET_ACCESS_KEY = local.bootstrap_values.remotely_save_s3_secret_access_key
      REMOTELY_SAVE_S3_BUCKET            = local.bootstrap_values.remotely_save_s3_bucket
      REMOTELY_SAVE_S3_ENDPOINT          = local.bootstrap_values.remotely_save_s3_endpoint
      REMOTELY_SAVE_S3_REGION            = local.bootstrap_values.remotely_save_s3_region
      REMOTELY_SAVE_REMOTE_PREFIX        = local.bootstrap_values.remotely_save_remote_prefix
      RESEND_API_KEY                     = local.bootstrap_values.resend_api_key
      MAILGUN_API_KEY                    = local.bootstrap_values.mailgun_api_key
      AWS_ACCESS_KEY_ID                  = local.bootstrap_values.aws_access_key_id
      AWS_SECRET_ACCESS_KEY              = local.bootstrap_values.aws_secret_access_key
    } : env_name => value if value != ""
  }

}

locals {
  coder_agent_internal_base_url = trimsuffix(var.coder_agent_url_override, "/")
  coder_agent_internal_script = replace(
    replace(
      coder_agent.main.init_script,
      "/export CODER_AGENT_URL=[^\\n]+/",
      "export CODER_AGENT_URL=${local.coder_agent_internal_base_url}/"
    ),
    "/BINARY_URL=[^\\n]+/",
    "BINARY_URL=${local.coder_agent_internal_base_url}/bin/coder-linux-${data.coder_provisioner.me.arch}"
  )
  coder_agent_init_script = var.coder_agent_url_override != "" ? local.coder_agent_internal_script : replace(
    coder_agent.main.init_script,
    "/localhost|127\\.0\\.0\\.1/",
    "host.docker.internal"
  )
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

variable "coder_agent_url_override" {
  description = "Optional internal URL used by workspace agents to reach Coder when the public URL is behind an access proxy"
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

# --- VM Bootstrap Secrets ---

variable "github_token" {
  description = "GitHub token for gh, private repo clones, and vault GitHub backup pushes"
  type        = string
  default     = ""
  sensitive   = true
}

variable "openai_api_key" {
  description = "OpenAI API key for Codex/OpenAI-backed tools"
  type        = string
  default     = ""
  sensitive   = true
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token for tunnels, DNS, R2, workers, and migration scripts"
  type        = string
  default     = ""
  sensitive   = true
}

variable "cloudflare_account_id" {
  description = "Cloudflare account ID"
  type        = string
  default     = ""
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID for dev.bmu.one/bmu.one automation"
  type        = string
  default     = ""
}

variable "cloudflare_kv_theme_namespace_id" {
  description = "Cloudflare KV namespace ID used by the tmux theme sync worker"
  type        = string
  default     = ""
}

variable "tmux_theme_sync_token" {
  description = "Shared token for the tmux theme sync service"
  type        = string
  default     = ""
  sensitive   = true
}

variable "tmux_theme_sync_url" {
  description = "Cloudflare Worker URL for tmux/Codex theme sync"
  type        = string
  default     = "https://theme.nomarh.com"
}

variable "tmux_theme_sync_enabled" {
  description = "Whether tmux/Codex theme sync should auto-start when a token is configured"
  type        = string
  default     = "true"
}

variable "remotely_save_s3_access_key_id" {
  description = "Obsidian Remotely Save S3 access key ID"
  type        = string
  default     = ""
  sensitive   = true
}

variable "remotely_save_s3_secret_access_key" {
  description = "Obsidian Remotely Save S3 secret access key"
  type        = string
  default     = ""
  sensitive   = true
}

variable "remotely_save_s3_bucket" {
  description = "Obsidian Remotely Save S3 bucket"
  type        = string
  default     = ""
}

variable "remotely_save_s3_endpoint" {
  description = "Obsidian Remotely Save S3 endpoint"
  type        = string
  default     = ""
}

variable "remotely_save_s3_region" {
  description = "Obsidian Remotely Save S3 region"
  type        = string
  default     = "auto"
}

variable "remotely_save_remote_prefix" {
  description = "Optional Obsidian Remotely Save remote prefix"
  type        = string
  default     = ""
}

variable "resend_api_key" {
  description = "Resend API key for email tooling"
  type        = string
  default     = ""
  sensitive   = true
}

variable "mailgun_api_key" {
  description = "Mailgun API key for email tooling"
  type        = string
  default     = ""
  sensitive   = true
}

variable "aws_access_key_id" {
  description = "AWS access key ID for SES/S3/email tooling"
  type        = string
  default     = ""
  sensitive   = true
}

variable "aws_secret_access_key" {
  description = "AWS secret access key for SES/S3/email tooling"
  type        = string
  default     = ""
  sensitive   = true
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

data "coder_parameter" "bootstrap" {
  for_each = local.bootstrap_parameters

  name         = each.key
  display_name = each.value.display_name
  description  = each.value.description
  type         = "string"
  form_type    = each.value.form_type
  mutable      = true
  default      = each.value.default
  order        = each.value.order
  styling      = each.value.mask ? jsonencode({ mask_input = true }) : jsonencode({})
}

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

    },
    local.bootstrap_env
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
    script       = <<EOT
      echo "`cat /proc/loadavg | awk '{ print $1 }'` `nproc`" | awk '{ printf "%0.2f", $1/$2 }'
    EOT
    interval     = 60
    timeout      = 1
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

resource "coder_script" "tmux_theme_sync" {
  agent_id           = coder_agent.main.id
  display_name       = "Tmux Theme Sync"
  icon               = "/icon/terminal.svg"
  run_on_start       = true
  start_blocks_login = false
  script             = file("${path.module}/scripts/tmux-theme-sync.sh")
}

resource "coder_script" "tools_node" {
  agent_id           = coder_agent.main.id
  display_name       = "Node.js Package Managers"
  icon               = "/icon/nodejs.svg"
  run_on_start       = true
  start_blocks_login = true
  script             = file("${path.module}/scripts/tools-node.sh")
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

resource "coder_script" "vault_github_backup" {
  agent_id           = coder_agent.main.id
  display_name       = "Vault GitHub Backup"
  icon               = "/icon/git.svg"
  run_on_start       = true
  start_blocks_login = false
  script             = file("${path.module}/scripts/vault-github-backup-loop.sh")
}

resource "coder_script" "codex_usage_guard" {
  agent_id           = coder_agent.main.id
  display_name       = "Codex Usage Guard"
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
    echo "Installed codex-usage-guard"
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

resource "coder_script" "vault_guard" {
  agent_id           = coder_agent.main.id
  display_name       = "Vault Guard"
  icon               = "/icon/folder.svg"
  run_on_start       = true
  start_blocks_login = false
  script             = file("${path.module}/scripts/vault-guard.sh")
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

resource "coder_script" "nomarh_ops_toolkit" {
  agent_id           = coder_agent.main.id
  display_name       = "Nomarh Ops Toolkit"
  icon               = "/icon/terminal.svg"
  run_on_start       = true
  start_blocks_login = false
  script             = file("${path.module}/scripts/nomarh-ops-toolkit.sh")
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
    claude_api_key = local.claude_code_api_key_value
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

resource "coder_app" "nomarh_ops" {
  agent_id     = coder_agent.main.id
  slug         = "nomarh-ops"
  display_name = "Nomarh Operator"
  icon         = "/icon/terminal.svg"
  command      = "bash -l -c 'can-morning || true; exec bash -l'"
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
  # Use path-based routing so the app works through coder.nomarh.com without
  # a separate wildcard app domain.
  url       = "http://localhost:6080/"
  subdomain = false
  share     = "owner"
}

# Browser-accessible tmux session picker (ttyd on :7681).
resource "coder_app" "tmux_picker" {
  agent_id     = coder_agent.main.id
  slug         = "tmux"
  display_name = "Tmux"
  icon         = "/icon/terminal.svg"
  url          = "http://localhost:7681"
  subdomain    = false
  share        = "owner"
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
    dir_sha1 = sha1(join("", [
      for f in sort(tolist(setunion(fileset(path.module, "Dockerfile"), fileset(path.module, "scripts/**")))) :
      filesha1("${path.module}/${f}")
    ]))
  }
}

resource "docker_container" "workspace" {
  count    = data.coder_workspace.me.start_count
  image    = docker_image.main.name
  name     = "coder-${data.coder_workspace_owner.me.name}-${lower(data.coder_workspace.me.name)}"
  hostname = data.coder_workspace.me.name

  entrypoint = ["sh", "-c", local.coder_agent_init_script]
  env        = ["CODER_AGENT_TOKEN=${coder_agent.main.token}"]

  host {
    host = "host.docker.internal"
    ip   = "host-gateway"
  }

  # Resource limits: 24GB RAM, 24GB swap (48GB total), 6 CPU cores
  memory      = 24576
  memory_swap = 49152
  cpu_shares  = 6144

  # tmpfs /tmp — build artifacts and scratch files stay in RAM (capped at 4GB),
  # auto-cleared on container restart. Stops /tmp from filling the home volume
  # over months of use. `exec` is required because the Coder agent script
  # downloads its binary into /tmp and runs it; Docker tmpfs mounts default
  # to noexec which blocks that.
  tmpfs = {
    "/tmp" = "size=4g,mode=1777,exec"
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

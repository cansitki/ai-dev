FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Base system update
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        lsb-release \
    && rm -rf /var/lib/apt/lists/*

# Add Docker's official GPG key
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc

# Add Docker repository
RUN echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install all packages in a single layer
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        apt-utils \
        bash \
        build-essential \
        containerd.io \
        direnv \
        docker-ce \
        docker-ce-cli \
        docker-buildx-plugin \
        docker-compose-plugin \
        fonts-firacode \
        fonts-powerline \
        git \
        htop \
        iotop \
        jq \
        locales \
        man \
        nano \
        nethogs \
        openssh-client \
        postgresql-16 \
        postgresql-contrib-16 \
        python3 \
        python3-pip \
        python3-venv \
        rclone \
        rsync \
        software-properties-common \
        sudo \
        sysstat \
        tmux \
        ttyd \
        unzip \
        vim \
        wget \
        zsh \
        # Obsidian Desktop runtime deps (headless via Xvfb)
        xvfb \
        x11vnc \
        novnc \
        websockify \
        dbus-x11 \
        libnss3 \
        libgbm1 \
        libasound2t64 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgtk-3-0 \
        libpango-1.0-0 \
        libcairo2 \
        libsecret-1-0 \
    && rm -rf /var/lib/apt/lists/*

# Enable sysstat collection (sa1/sa2 cron) so `sar` has historical data.
# Default Debian/Ubuntu config sets ENABLED=false; flip it on.
RUN sed -i 's/ENABLED="false"/ENABLED="true"/' /etc/default/sysstat \
    && sed -i 's/^HISTORY=.*/HISTORY=30/' /etc/sysstat/sysstat || true

# Install Obsidian Desktop (.deb). Pinned via env var so bumping is one line.
# 1.12+ ships improved CLI support that the can-workbench obsidian-cli
# binary expects; older installers segfault on commands.
ENV OBSIDIAN_VERSION=1.12.7
RUN curl -fsSL "https://github.com/obsidianmd/obsidian-releases/releases/download/v${OBSIDIAN_VERSION}/obsidian_${OBSIDIAN_VERSION}_amd64.deb" \
        -o /tmp/obsidian.deb \
    && apt-get update \
    && apt-get install --yes --no-install-recommends /tmp/obsidian.deb \
    && rm /tmp/obsidian.deb \
    && rm -rf /var/lib/apt/lists/*

# Coder exposes Obsidian VNC through a path-based app proxy. The launcher
# derives that browser-visible prefix and passes it to noVNC as the WebSocket
# path; otherwise the packaged client incorrectly connects to /websockify at
# the Coder domain root. A real file is required because websockify's Python
# HTTP handler does not follow symlinks for index files.
COPY scripts/novnc-index.html /usr/share/novnc/index.html

# Install Node.js 24 via NodeSource (always available, no nvm dependency)
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && corepack enable

# Setup docker-compose symlink
RUN systemctl enable docker
RUN ln -sf /usr/libexec/docker/cli-plugins/docker-compose /usr/bin/docker-compose

# Setup locale
RUN locale-gen en_US.UTF-8
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

# Create coder user with proper groups
RUN userdel -r ubuntu \
    && useradd coder \
        --create-home \
        --shell=/bin/zsh \
        --groups=docker \
        --uid=1000 \
        --user-group \
    && echo "coder ALL=(ALL) NOPASSWD:ALL" >>/etc/sudoers.d/nopasswd

USER coder
WORKDIR /home/coder

# Keep template helper scripts available at runtime. Coder executes individual
# startup scripts from temporary files, so sibling Python/helper files are not
# otherwise available to those scripts.
COPY --chown=coder:coder scripts /opt/ai-dev-template/scripts

# Create common directories
RUN mkdir -p ~/projects ~/bin ~/.config ~/.ssh ~/.local/bin

# Setup basic git configuration that can be overridden
RUN git config --global init.defaultBranch main \
    && git config --global pull.rebase false \
    && git config --global core.editor vim

# Setup .zshenv for PATH and env vars (survives Oh My Zsh .zshrc replacement)
# .zshenv is sourced by ALL zsh invocations (interactive, non-interactive, login, non-login)
RUN echo '# Tool PATH (set in .zshenv so it survives Oh My Zsh .zshrc replacement)' > ~/.zshenv \
    && echo 'export PATH="$HOME/.claude/local/bin:$HOME/.local/bin:$HOME/.local/share/pnpm:$HOME/.bun/bin:$HOME/bin:$PATH"' >> ~/.zshenv \
    && echo '' >> ~/.zshenv \
    && echo '# PostgreSQL' >> ~/.zshenv \
    && echo 'export PGHOST=localhost' >> ~/.zshenv \
    && echo 'export PGUSER=coder' >> ~/.zshenv \
    && echo 'export PGDATABASE=coder' >> ~/.zshenv

# Add PATH to .bashrc and .profile for bash -l commands (coder_app launchers)
RUN TOOL_PATH='export PATH="$HOME/.claude/local/bin:$HOME/.local/bin:$HOME/.local/share/pnpm:$HOME/.bun/bin:$PATH"' \
    && echo "$TOOL_PATH" >> ~/.bashrc \
    && echo "$TOOL_PATH" >> ~/.profile

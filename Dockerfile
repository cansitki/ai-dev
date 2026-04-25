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
        jq \
        locales \
        man \
        nano \
        openssh-client \
        postgresql-16 \
        postgresql-contrib-16 \
        python3 \
        python3-pip \
        rsync \
        software-properties-common \
        sudo \
        tmux \
        unzip \
        vim \
        wget \
        zsh \
    && rm -rf /var/lib/apt/lists/*

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

# Create common directories
RUN mkdir -p ~/projects ~/bin ~/.config ~/.ssh ~/.local/bin

# Setup basic git configuration that can be overridden
RUN git config --global init.defaultBranch main \
    && git config --global pull.rebase false \
    && git config --global core.editor vim

# Setup .zshenv for PATH and env vars (survives Oh My Zsh .zshrc replacement)
# .zshenv is sourced by ALL zsh invocations (interactive, non-interactive, login, non-login)
RUN echo '# Tool PATH (set in .zshenv so it survives Oh My Zsh .zshrc replacement)' > ~/.zshenv \
    && echo 'export PATH="$HOME/.claude/local/bin:$HOME/.local/bin:$HOME/.opencode/bin:$HOME/.local/share/pnpm:$HOME/.bun/bin:$HOME/.foundry/bin:$HOME/bin:$PATH"' >> ~/.zshenv \
    && echo '' >> ~/.zshenv \
    && echo '# PostgreSQL' >> ~/.zshenv \
    && echo 'export PGHOST=localhost' >> ~/.zshenv \
    && echo 'export PGUSER=coder' >> ~/.zshenv \
    && echo 'export PGDATABASE=coder' >> ~/.zshenv

# Add PATH to .bashrc and .profile for bash -l commands (coder_app launchers)
RUN TOOL_PATH='export PATH="$HOME/.claude/local/bin:$HOME/.local/bin:$HOME/.opencode/bin:$HOME/.local/share/pnpm:$HOME/.bun/bin:$HOME/.foundry/bin:$PATH"' \
    && echo "$TOOL_PATH" >> ~/.bashrc \
    && echo "$TOOL_PATH" >> ~/.profile

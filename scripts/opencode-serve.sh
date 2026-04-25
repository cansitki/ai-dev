#!/bin/bash
set -e

export PATH="/home/coder/.opencode/bin:/home/coder/.local/bin:$PATH"

# Wait for opencode to be installed
max_attempts=30
attempt=0
while ! command -v opencode &> /dev/null; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "ERROR: opencode CLI not found after $max_attempts attempts"
    exit 1
  fi
  echo "Waiting for opencode CLI to be installed... (attempt $attempt/$max_attempts)"
  sleep 10
done

echo "Starting opencode serve on port 62748..."
nohup opencode serve --port 62748 > /tmp/opencode-serve.log 2>&1 &
echo "opencode serve started (pid $!)"

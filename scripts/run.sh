#!/bin/bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export TZ="Asia/Tokyo"
umask 077
mkdir -p "$PROJECT_DIR/.local/logs"
TODAY="$(date +%F)"
exec uv run --frozen ai-journal >> "$PROJECT_DIR/.local/logs/$TODAY.log" 2>&1

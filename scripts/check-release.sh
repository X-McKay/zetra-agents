#!/usr/bin/env bash
# Agent-authored code never receives the release host's environment or filesystem.
set -euo pipefail
agent=${1:?usage: check-release.sh <agent>}
[[ "$agent" =~ ^[a-z0-9-]+$ ]] || { echo 'invalid agent name' >&2; exit 1; }
cd "${2:-$(dirname "$0")/..}"
image="zetra-${agent}-validation:local"
docker build --platform linux/amd64 --target validation -t "$image" "agents/$agent"
docker run --rm --read-only --user 1500:1500 --network none --tmpfs /tmp \
  -e UV_CACHE_DIR=/tmp/uv-cache -e RUFF_CACHE_DIR=/tmp/ruff-cache \
  -e PYTHONDONTWRITEBYTECODE=1 -e "PYTEST_ADDOPTS=-o cache_dir=/tmp/pytest-cache" "$image"

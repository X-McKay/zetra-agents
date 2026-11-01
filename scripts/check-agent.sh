#!/usr/bin/env bash
# Shared local/CI/release quality entrypoint; no cluster or deployment access.
set -euo pipefail
agent=${1:?usage: check-agent.sh <agent>}
[[ "$agent" =~ ^[a-z0-9-]+$ ]] || { echo 'invalid agent name' >&2; exit 1; }
cd "$(dirname "$0")/../agents/$agent"
bash scripts/check.sh

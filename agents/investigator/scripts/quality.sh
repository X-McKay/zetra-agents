#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --locked zetra quality . --mcp-fixtures evals/investigator/mcp.json "$@"

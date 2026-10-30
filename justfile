# Agents built with Zetra for the Kubani Agent Runtime Platform.

default:
    @just --list

# Install every project's locked environment.
setup:
    uv sync --locked --project tools
    for a in $(uv run --project tools --locked zetra-agents list | tr -d '[],"'); do uv sync --locked --project agents/$a; done

# Lint, test and layout-check the tools and every agent.
check: check-tools
    for a in $(uv run --project tools --locked zetra-agents list | tr -d '[],"'); do just check-agent $a; done

check-tools:
    cd tools && uv run --locked ruff check . && uv run --locked ruff format --check . && uv run --locked pytest -q
    uv run --project tools --locked zetra-agents check

# Lint and test one agent.
check-agent agent:
    cd agents/{{agent}} && uv run --locked ruff check . && uv run --locked ruff format --check . && uv run --locked pytest -q

# Build one agent's image locally (not pushed).
build agent:
    docker build --platform linux/amd64 -t agent-{{agent}}:dev agents/{{agent}}

# Build, push, sign, attest and write dist/<agent>; see scripts/release.sh for the environment.
release agent:
    scripts/release.sh {{agent}}

# Print the compiled policy bundle and digest for a release file, as the controller computes it.
policy-digest agent release:
    uv run --project tools --locked agentctl policy-digest --agent agents/{{agent}}/deploy/agent.yaml --release {{release}} --mcp-resource-base https://mcp.almckay.io --print-bundle

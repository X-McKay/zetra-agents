# Build the same installed package used by local checks and core platform sessions.
FROM ghcr.io/astral-sh/uv:0.13.1 AS uv
FROM python:3.12.14-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --compile-bytecode
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --compile-bytecode
# Agent-authored checks run only here, without release-host credentials or mounts.
FROM build AS validation
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen
COPY deploy ./deploy
COPY tests ./tests
COPY evals ./evals
COPY scripts ./scripts
COPY agent.yaml ./agent.yaml
CMD ["bash", "/app/scripts/check.sh"]

FROM python:3.12.14-slim
COPY --from=build /app/.venv /app/.venv
COPY agent.yaml /app/agent.yaml
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1500:1500
ENTRYPOINT ["/app/.venv/bin/python", "-m", "agent_runtime.wait"]

# Agent image (spec 11.1, 14.1). Build from this directory:
#   docker build -t registry.almckay.io/agents/investigator .
# The pod template runs /app/.venv/bin/python -m agent_runtime.wait as UID 1500 with a
# read-only root filesystem; the Session Runner execs agent_runtime.step per boundary.
FROM ghcr.io/astral-sh/uv:0.13.1 AS uv

FROM python:3.12.14-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --compile-bytecode

FROM python:3.12.14-slim
COPY --from=build /app/.venv /app/.venv
COPY agent.yaml /app/agent.yaml
COPY src/investigator /app/investigator
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1500:1500
ENTRYPOINT ["/app/.venv/bin/python", "-m", "agent_runtime.wait"]

# Agent image (spec 11.1, 14.1). Build from this directory:
#   docker build -t registry.almckay.io/agents/conformance-performance .
# The pod template runs /app/.venv/bin/python -m agent_runtime.wait as UID 1500 with a
# read-only root filesystem; the Session Runner execs agent_runtime.step per boundary.
FROM ghcr.io/astral-sh/uv:0.13.1 AS uv

FROM python:3.12.16-slim@sha256:8523d6abeb48ceae0b7240d30c5808fc26cb79c1a635bacdf19cf3baecfbec07 AS build
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --compile-bytecode

# 3.12.16 fixes the interpreter's Critical CVE-2026-19445 and CVE-2026-115557; the
# upgrade takes Debian security fixes newer than the base image (openssl, pcre2), which
# Kubani's admission vuln check would otherwise reject.
FROM python:3.12.16-slim@sha256:8523d6abeb48ceae0b7240d30c5808fc26cb79c1a635bacdf19cf3baecfbec07
RUN apt-get update && apt-get -y upgrade --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/.venv /app/.venv
COPY agent.yaml /app/agent.yaml
COPY src/performance_fixture /app/performance_fixture
# Preserve the unmodified SDK's manifest/factory validators for normal image CI.
# Only this fixture's boundary driver is replaced; no validation is skipped.
RUN /app/.venv/bin/python -c "import agent_runtime.step, pathlib, shutil; installed = pathlib.Path(agent_runtime.step.__file__); shutil.copyfile(installed, installed.with_name('_performance_sdk_step.py')); shutil.copyfile('/app/performance_fixture/step.py', installed); shutil.rmtree(installed.parent / '__pycache__', ignore_errors=True)"
RUN /app/.venv/bin/python -I -c "import agent_runtime.step as step; assert step.PERFORMANCE_FIXTURE_OVERRIDE == 'conformance-performance-v1'; assert 'site-packages/agent_runtime/step.py' in step.__file__"
COPY verify_image.py /tmp/verify_performance_image.py
RUN /app/.venv/bin/python -I /tmp/verify_performance_image.py && rm /tmp/verify_performance_image.py
LABEL agentplatform.io.conformance-fixture="T29-performance-override"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1500:1500
ENTRYPOINT ["/app/.venv/bin/python", "-m", "agent_runtime.wait"]

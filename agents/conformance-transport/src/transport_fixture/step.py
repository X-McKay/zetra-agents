"""Installed signed T27 driver; normal SDK validators remain authoritative."""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

from agent_runtime.identity import write_private

TRANSPORT_FIXTURE_OVERRIDE = "conformance-transport-v1"


def load_manifest():
    from agent_runtime._transport_sdk_step import load_manifest as load

    return load()


def build_agent(manifest):
    from agent_runtime._transport_sdk_step import build_agent as build

    return build(manifest)


def execute(req, root, *, probe_fn=None):
    if (
        req.get("boundary") != 0
        or type(req.get("boundary")) is not int
        or req.get("task") != {"transport_case": "tls"}
    ):
        raise ValueError("invalid transport fixture boundary/task")
    if (root / "state/state.json").exists():
        raise ValueError("transport fixture must begin from empty state")
    if probe_fn is None:
        _, tools = build_agent(load_manifest())
        report = asyncio.run(tools["transport_probe"].fn())
    else:
        report = probe_fn()
    write_private(root / "workspace/transport.json", json.dumps(report, sort_keys=True))
    write_private(root / "state/state.json", json.dumps({"next": 1}))
    write_private(root / "state/0.done", str(time.time()))
    return {
        "boundary": 0,
        "kind": "tool",
        "tool": "transport_probe",
        "done": True,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "summary": "credential-free transport observations committed",
    }, 2


def main():
    try:
        header = sys.stdin.buffer.readline(16)
        if not re.fullmatch(rb"[0-9]{1,6}\n", header) or not 0 < int(header) <= 65536:
            return 5
        raw = sys.stdin.buffer.read(int(header))
        if len(raw) != int(header):
            return 5
        result, code = execute(
            json.loads(raw), Path(os.environ.get("AGENT_SANDBOX_DIR", "/sandbox"))
        )
        print(json.dumps(result))
        return code
    except Exception as exc:  # noqa: BLE001 - no raw exceptions or request data
        print(type(exc).__name__, file=sys.stderr)
        return 5


if __name__ == "__main__":
    sys.exit(main())

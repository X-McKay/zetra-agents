"""Signed T29 driver; actual ordinary SDK token/MCP paths, bounded metadata only."""

import asyncio
import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

from agent_runtime.identity import identity, write_private

PERFORMANCE_FIXTURE_OVERRIDE = "conformance-performance-v1"
MODES = {"pair", "snapshot", "recovery", "trial", "saturation"}
MAX_PAYLOAD = 64 << 20  # a literal payload this size must exceed the runner archive cap


def load_manifest():
    from agent_runtime._performance_sdk_step import load_manifest as load

    return load()


def build_agent(manifest):
    from agent_runtime._performance_sdk_step import build_agent as build

    return build(manifest)


def read():
    _, tools = build_agent(load_manifest())
    return asyncio.run(tools["performance_read"].fn())


def canonical_uuid(value):
    try:
        return (
            isinstance(value, str)
            and str(uuid.UUID(value)) == value
            and uuid.UUID(value).version == 4
        )
    except (ValueError, TypeError, AttributeError):
        return False


def execute(
    req,
    root,
    *,
    read_fn=read,
    token_fn=None,
    sleep_fn=time.sleep,
    session=None,
    generation=None,
    process_id=None,
    clock=time.monotonic_ns,
):
    if not isinstance(req, dict) or set(req) != {"task", "boundary"}:
        raise ValueError("invalid performance request")
    task, boundary = req["task"], req["boundary"]
    if not isinstance(task, dict) or set(task) != {"performance_mode", "run_id", "payload_bytes"}:
        raise ValueError("invalid performance task")
    mode, run_id, payload = task["performance_mode"], task["run_id"], task["payload_bytes"]
    if (
        mode not in MODES
        or not canonical_uuid(run_id)
        or type(boundary) is not int
        or boundary not in (0, 1)
        or (mode == "snapshot" and boundary != 0)
        or type(payload) is not int
        or not 0 <= payload <= MAX_PAYLOAD
        or (mode != "snapshot" and payload != 0)
    ):
        raise ValueError("unbounded or invalid performance task")
    session = session or os.environ["AGENT_SESSION_ID"]
    if not canonical_uuid(session):
        raise ValueError("invalid performance session")
    if generation is None:
        match = re.fullmatch(r"s-[a-f0-9]{16}-g([1-9][0-9]*)", os.environ["HOSTNAME"])
        if not match:
            raise ValueError("invalid performance Pod")
        generation = int(match[1])
    if type(generation) is not int or generation not in ((1, 2) if mode == "recovery" else (1,)):
        raise ValueError("unexpected performance generation")
    binding = {"run_id": run_id, "session_id": session, "mode": mode}
    state_file = root / "state/state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {**binding, "next": 0}
    if state != {**binding, "next": boundary}:
        raise ValueError("performance checkpoint identity/boundary mismatch")
    evidence_file = root / "workspace/performance.json"
    evidence = (
        json.loads(evidence_file.read_text())
        if evidence_file.exists()
        else {"schema": "t29-fixture-v1", **binding, "records": []}
    )
    if (
        set(evidence) != {"schema", *binding, "records"}
        or any(evidence.get(k) != v for k, v in binding.items())
        or evidence.get("schema") != "t29-fixture-v1"
        or not isinstance(evidence["records"], list)
        or len(evidence["records"]) != boundary
    ):
        raise ValueError("performance evidence identity/boundary mismatch")
    (root / "workspace").mkdir(parents=True, exist_ok=True)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    start = clock()
    token_ns = mcp_ns = 0
    fingerprint = None
    if mode == "snapshot":
        # Stream actual file bytes without allocating the entire payload in RAM.
        chunk = b"0" * (1 << 20)
        with (root / "workspace/payload.bin").open("wb") as target:
            remaining = payload
            while remaining:
                count = min(remaining, len(chunk))
                target.write(chunk[:count])
                remaining -= count
            target.flush()
            os.fsync(target.fileno())
        if (root / "workspace/payload.bin").stat().st_size != payload:
            raise ValueError("performance payload write incomplete")
    else:
        token_start = clock()
        token = (token_fn or identity().token)()
        if not isinstance(token, str) or not token:
            raise ValueError("ordinary SDK token missing")
        fingerprint = hashlib.sha256(token.encode()).hexdigest()
        del token
        token_ns = clock() - token_start
        mcp_start = clock()
        result = read_fn()
        if result != {"completed": True}:
            raise ValueError("ordinary SDK MCP completion missing")
        mcp_ns = clock() - mcp_start
        if mode in {"trial", "saturation"} and boundary == 0:
            sleep_fn(20)
    row = {
        "boundary": boundary,
        "generation": generation,
        "process_id": process_id if process_id is not None else os.getpid(),
        "token_ns": token_ns,
        "mcp_session_ns": mcp_ns,
        "guest_operation_ns": clock() - start,
        "token_sha256": fingerprint,
        "payload_bytes": payload,
    }
    evidence["records"].append(row)
    write_private(evidence_file, json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    write_private(state_file, json.dumps({**binding, "next": boundary + 1}))
    write_private(root / f"state/{boundary}.done", str(time.time()))
    done = mode == "snapshot" or boundary == 1
    return {
        "boundary": boundary,
        "kind": "tool",
        "done": done,
        "tool": "performance_read",
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "summary": "performance boundary completed",
    }, 2 if done else 0


def main():
    try:
        header = sys.stdin.buffer.readline(16)
        if not re.fullmatch(rb"[0-9]{1,6}\n", header) or not 0 < int(header) <= 65536:
            return 5
        body = sys.stdin.buffer.read(int(header))
        if len(body) != int(header):
            return 5
        result, rc = execute(
            json.loads(body), Path(os.environ.get("AGENT_SANDBOX_DIR", "/sandbox"))
        )
        print(json.dumps(result))
        return rc
    except Exception as exc:  # noqa: BLE001 - no arbitrary token/server/exception text
        print(type(exc).__name__, file=sys.stderr)
        return 5


if __name__ == "__main__":
    sys.exit(main())

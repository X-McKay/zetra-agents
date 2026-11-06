"""Signed T23 boundary driver. Only the fixture image replaces its SDK step.

The ordinary runner/workflow and SDK MCP client remain unchanged. Stage records
contain fixed metadata only; a successful remote read is never synthesized.
"""

import asyncio
import json
import os
import re
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from agent_runtime.identity import write_private

CHECKPOINT_FIXTURE_OVERRIDE = "conformance-checkpoint-v1"
CASES = {"control", "a", "b", "c", "d", "e"}
PREFIX = "checkpoint_stage "


def load_manifest():
    from agent_runtime._checkpoint_sdk_step import load_manifest as load

    return load()


def build_agent(manifest):
    from agent_runtime._checkpoint_sdk_step import build_agent as build

    return build(manifest)


def read():
    _, tools = build_agent(load_manifest())
    result = asyncio.run(tools["checkpoint_read"].fn())
    if result != {"completed": True}:
        raise ValueError("checkpoint read completion missing")


def emit_stage(event):
    print(PREFIX + json.dumps(event, sort_keys=True), file=sys.stderr, flush=True)


def hold_before_done():
    # Only g1/b1 in case b. The observed worker barrier must delete this Pod;
    # expiration is an error, never an invented successful boundary.
    time.sleep(120)
    raise TimeoutError("checkpoint kill was not observed")


def execute(
    req,
    root,
    *,
    read_fn=read,
    signal=emit_stage,
    pause=hold_before_done,
    session=None,
    generation=None,
):
    task, boundary = req["task"], req["boundary"]
    case, run_id = task.get("checkpoint_case"), task.get("run_id")
    if case not in CASES or type(boundary) is not int or not 0 <= boundary <= 2:
        raise ValueError("invalid checkpoint fixture task")
    if str(uuid.UUID(run_id)) != run_id:
        raise ValueError("invalid checkpoint run identity")
    session = session or os.environ["AGENT_SESSION_ID"]
    if str(uuid.UUID(session)) != session:
        raise ValueError("invalid checkpoint session identity")
    if generation is None:
        match = re.fullmatch(r"s-[a-f0-9]{16}-g([1-9][0-9]*)", os.environ["HOSTNAME"])
        if not match:
            raise ValueError("invalid checkpoint pod name")
        generation = int(match[1])
    if type(generation) is not int or generation not in (1, 2):
        raise ValueError("unexpected checkpoint generation")
    state_file = root / "state/state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {"next": 0}
    if state.get("next") != boundary:
        raise ValueError("checkpoint boundary mismatch")
    state_file.parent.mkdir(parents=True, exist_ok=True)
    (root / "workspace").mkdir(parents=True, exist_ok=True)

    def stage(name):
        signal(
            {
                "stage": name,
                "run_id": run_id,
                "session_id": session,
                "generation": generation,
                "boundary": boundary,
                "case": case,
                "time": datetime.now(UTC).isoformat(),
            }
        )

    stage("boundary_start")
    if boundary == 0:
        # Exceeds one artifact-store chunk so d pauses during a real partial copy.
        write_private(root / "workspace/upload-padding", "0" * (2 << 20))
    elif boundary == 1:
        read_fn()
        stage("read_complete")
        if case == "b" and generation == 1:
            pause()
    checkpoint = {
        "run_id": run_id,
        "session_id": session,
        "last_boundary": boundary,
        "generation": generation,
    }
    write_private(root / "workspace/checkpoint.json", json.dumps(checkpoint, sort_keys=True))
    write_private(state_file, json.dumps({"next": boundary + 1}))
    write_private(root / f"state/{boundary}.done", str(time.time()))
    stage("done")
    done = boundary == 2
    return {
        "boundary": boundary,
        "kind": "tool",
        "done": done,
        "tool": "checkpoint_read",
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "summary": "checkpoint boundary completed",
    }, 2 if done else 0


def main():
    try:
        header = sys.stdin.buffer.readline(16)
        if not re.fullmatch(rb"[0-9]{1,6}\n", header) or not 0 < int(header) <= 65536:
            return 5
        body = sys.stdin.buffer.read(int(header))
        if len(body) != int(header):
            return 5
        result, code = execute(
            json.loads(body), Path(os.environ.get("AGENT_SANDBOX_DIR", "/sandbox"))
        )
        print(json.dumps(result))
        return code
    except Exception as exc:  # noqa: BLE001 - never output arbitrary messages, tokens or read results
        print(type(exc).__name__, file=sys.stderr)
        return 5


if __name__ == "__main__":
    sys.exit(main())

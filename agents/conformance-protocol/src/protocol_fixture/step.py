"""Deliberate T25 wire faults; installed over agent_runtime.step only in this image.

This is an adversarial guest, not a production runtime fallback. It makes no
model/network calls and deliberately bypasses the SDK output normalizer.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

PROTOCOL_FIXTURE_OVERRIDE = "conformance-protocol-v1"
FAULTS = {"stdout_10mib", "invalid_json", "wrong_boundary", "done_true_rc0", "hang"}


def load_manifest():
    """Keep the normal image CI contract, using the unmodified installed SDK."""
    from agent_runtime._protocol_sdk_step import load_manifest as load

    return load()


def build_agent(manifest):
    """Validate the factory/tools without executing the SDK boundary driver."""
    from agent_runtime._protocol_sdk_step import build_agent as build

    return build(manifest)


def document(boundary, done=False, summary="checkpoint accepted"):
    return {
        "boundary": boundary,
        "kind": "tool",
        "done": done,
        "tool": "protocol_fixture",
        "usage": None,
        "summary": summary,
    }


def main():
    header = sys.stdin.buffer.readline(16)
    if not re.fullmatch(rb"[0-9]{1,6}\n", header) or not 0 < int(header) <= 65536:
        return 5
    body = sys.stdin.buffer.read(int(header))
    if len(body) != int(header):
        return 5
    req = json.loads(body)
    case, boundary = req["task"]["protocol_case"], req["boundary"]
    if case not in FAULTS | {"control"} or type(boundary) is not int:
        return 5
    root = Path(os.environ.get("AGENT_SANDBOX_DIR", "/sandbox"))
    state, workspace = root / "state", root / "workspace"
    state.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    if boundary == 0:
        # Snapshot/restore is the production runner's normal mechanism. Nothing in
        # this fixture signals or supplies a trusted acceptance decision.
        (state / "state.json").write_text(json.dumps({"next": 1, "case": case}))
        (workspace / "protocol-checkpoint").write_text(case)
        print(
            json.dumps(
                document(
                    0,
                    case == "control",
                    "healthy control" if case == "control" else "checkpoint accepted",
                )
            )
        )
        return 2 if case == "control" else 0
    if boundary != 1 or not (state / "state.json").is_file():
        return 5
    if json.loads((state / "state.json").read_text()) != {"next": 1, "case": case}:
        return 5
    if (workspace / "protocol-checkpoint").read_text() != case:
        return 5
    if case == "stdout_10mib":
        for _ in range(320):
            sys.stdout.buffer.write(b"x" * 32768)
            sys.stdout.buffer.flush()
    elif case == "invalid_json":
        print("{invalid JSON")
    elif case == "wrong_boundary":
        print(json.dumps(document(2)))
    elif case == "done_true_rc0":
        print(json.dumps(document(1, True)))
    elif case == "hang":
        while True:
            time.sleep(60)
    else:
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())

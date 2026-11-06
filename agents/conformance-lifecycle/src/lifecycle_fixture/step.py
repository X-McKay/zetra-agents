"""Deterministic T24 guest: checkpoint then finish, or repeat one invalid wire.

Installed only in the signed lifecycle fixture; no model, network, grant or
control-object access. All external faults and acceptance remain with trusted
runner/operator components.
"""

import json
import os
import re
import sys
from pathlib import Path

LIFECYCLE_FIXTURE_OVERRIDE = "conformance-lifecycle-v1"
CASES = {
    "success",
    "cancel",
    "aps_down",
    "finalizer",
    "worker_kill",
    "terminate",
    "activity_crash",
    "retry_exhaustion",
}


def load_manifest():
    """Keep the normal image CI contract, using the unmodified installed SDK."""
    from agent_runtime._lifecycle_sdk_step import load_manifest as load

    return load()


def build_agent(manifest):
    """Validate the factory/tools without executing the SDK boundary driver."""
    from agent_runtime._lifecycle_sdk_step import build_agent as build

    return build(manifest)


def document(boundary, done=False, summary="checkpoint accepted"):
    return {
        "boundary": boundary,
        "kind": "tool",
        "done": done,
        "tool": "lifecycle_fixture",
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
    case, boundary = req["task"]["lifecycle_case"], req["boundary"]
    if case not in CASES or type(boundary) is not int:
        return 5
    root = Path(os.environ.get("AGENT_SANDBOX_DIR", "/sandbox"))
    state, workspace = root / "state", root / "workspace"
    state.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    if boundary == 0:
        # Snapshot/restore is the production runner's normal mechanism. Nothing in
        # this fixture signals or supplies a trusted acceptance decision.
        (state / "state.json").write_text(json.dumps({"next": 1, "case": case}))
        (workspace / "lifecycle-checkpoint").write_text(case)
        print(json.dumps(document(0)))
        return 0
    if boundary != 1 or not (state / "state.json").is_file():
        return 5
    if json.loads((state / "state.json").read_text()) != {"next": 1, "case": case}:
        return 5
    if (workspace / "lifecycle-checkpoint").read_text() != case:
        return 5
    if case == "retry_exhaustion":
        print("{invalid JSON")
        return 0
    print(json.dumps(document(1, True, "lifecycle fixture complete")))
    return 2


if __name__ == "__main__":
    sys.exit(main())

"""Verify the actual installed driver and the ordinary SDK manifest validators."""

import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_runtime import step

assert step.CHECKPOINT_FIXTURE_OVERRIDE == "conformance-checkpoint-v1"
assert "site-packages/agent_runtime/step.py" in step.__file__
manifest = step.load_manifest()
assert set(step.build_agent(manifest)[1]) == {"checkpoint_read"}
bad = copy.deepcopy(manifest)
bad["tools"][0]["effect"] = "workspace_read"
try:
    step.build_agent(bad)
except ValueError:
    pass
else:
    raise AssertionError("SDK manifest effect validation was bypassed")
with tempfile.TemporaryDirectory() as root:
    payload = json.dumps(
        {
            "boundary": 0,
            "task": {
                "checkpoint_case": "control",
                "run_id": "4bc9beea-e690-43eb-bf58-211044970094",
            },
        }
    ).encode()
    result = subprocess.run(
        [sys.executable, "-I", "-m", "agent_runtime.step"],
        input=str(len(payload)).encode() + b"\n" + payload,
        env={
            **os.environ,
            "AGENT_SANDBOX_DIR": root,
            "AGENT_SESSION_ID": "5de29de8-0566-42a7-a169-ec41cab71691",
            "HOSTNAME": "s-5de29de8056642a7-g1",
        },
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0 and json.loads(result.stdout)["tool"] == "checkpoint_read"
    assert (Path(root) / "state/0.done").is_file()
    assert json.loads((Path(root) / "state/state.json").read_text()) == {"next": 1}
    assert (Path(root) / "workspace/upload-padding").stat().st_size == 2 << 20
    stages = [
        json.loads(line.removeprefix("checkpoint_stage "))
        for line in result.stderr.decode().splitlines()
    ]
    assert [s["stage"] for s in stages] == ["boundary_start", "done"]
print("installed checkpoint driver baseline and ordinary SDK validators verified")

"""Check the installed image driver and unchanged ordinary SDK effect validators."""

import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_runtime import step

assert step.PERFORMANCE_FIXTURE_OVERRIDE == "conformance-performance-v1"
assert "site-packages/agent_runtime/step.py" in step.__file__
manifest = step.load_manifest()
assert "model" in manifest and manifest["model"] is None
assert set(step.build_agent(manifest)[1]) == {"performance_read"}
bad = copy.deepcopy(manifest)
bad["tools"][0]["effect"] = "workspace_read"
try:
    step.build_agent(bad)
except ValueError:
    pass
else:
    raise AssertionError("ordinary SDK effect validation was bypassed")
with tempfile.TemporaryDirectory() as root:
    request = {
        "boundary": 0,
        "task": {
            "performance_mode": "snapshot",
            "payload_bytes": 1024,
            "run_id": "4bc9beea-e690-43eb-bf58-211044970094",
        },
    }
    body = json.dumps(request).encode()
    result = subprocess.run(
        [sys.executable, "-I", "-m", "agent_runtime.step"],
        input=str(len(body)).encode() + b"\n" + body,
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
    assert result.returncode == 2 and json.loads(result.stdout)["done"] is True
    assert result.stderr == b""
    assert (Path(root) / "workspace/payload.bin").stat().st_size == 1024
    assert (Path(root) / "state/0.done").is_file()
    record = json.loads((Path(root) / "workspace/performance.json").read_text())["records"][0]
    assert record["payload_bytes"] == 1024 and record["token_sha256"] is None
print("installed performance driver and ordinary SDK validators verified")

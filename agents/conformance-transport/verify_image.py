"""Exercise installed fixture wire driver and unmodified SDK validation, offline."""

import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_runtime import step

assert step.TRANSPORT_FIXTURE_OVERRIDE == "conformance-transport-v1"
assert "site-packages/agent_runtime/step.py" in step.__file__
manifest = step.load_manifest()
assert set(step.build_agent(manifest)[1]) == {"transport_probe"}
bad = copy.deepcopy(manifest)
bad["tools"][0]["effect"] = "workspace_read"
try:
    step.build_agent(bad)
except ValueError:
    pass
else:
    raise AssertionError("SDK manifest validation was bypassed")
with tempfile.TemporaryDirectory() as root:
    payload = json.dumps({"boundary": 0, "task": {"transport_case": "tls"}}).encode()
    # Inject only the local network result for this image-build wire check. The
    # installed module and its main/execute functions are the actual image code.
    code = "from agent_runtime import step; step.build_agent(step.load_manifest()); from transport_fixture import probe; probe.run=lambda: {'version': 1}; raise SystemExit(step.main())"
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        input=str(len(payload)).encode() + b"\n" + payload,
        capture_output=True,
        check=False,
        env={**os.environ, "AGENT_SANDBOX_DIR": root},
        timeout=10,
    )
    assert result.returncode == 2 and json.loads(result.stdout)["done"] is True
    assert json.loads((Path(root) / "workspace/transport.json").read_text()) == {"version": 1}
print("installed transport driver and ordinary SDK validators verified")

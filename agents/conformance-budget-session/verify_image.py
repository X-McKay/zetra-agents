"""Verify the installed fixture driver and retain the unmodified SDK's CI validators."""

import copy
import json
import os
import subprocess
import sys
import tempfile

from agent_runtime import step

assert step.BUDGET_FIXTURE_OVERRIDE == "budget-conformance-v1"
assert "site-packages/agent_runtime/step.py" in step.__file__
manifest = step.load_manifest()
assert set(step.build_agent(manifest)[1]) == {"budget_fixture"}
bad = copy.deepcopy(manifest)
bad["tools"][0]["name"] = "wrong"
try:
    step.build_agent(bad)
except ValueError:
    pass
else:
    raise AssertionError("manifest validation was bypassed")
with tempfile.TemporaryDirectory() as root:
    payload = json.dumps({"boundary": 0, "task": {"budget_case": "image_check"}}).encode()
    result = subprocess.run(
        [sys.executable, "-I", "-m", "agent_runtime.step"],
        input=str(len(payload)).encode() + b"\n" + payload,
        env={**os.environ, "AGENT_SANDBOX_DIR": root},
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2 and json.loads(result.stdout)["tool"] == "budget_fixture"
print("installed budget fixture and standard manifest validation verified")

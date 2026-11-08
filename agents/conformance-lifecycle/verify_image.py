"""Build-time verification of the intentionally patched installed SDK module.

Run with the image interpreter. No pytest/dev packages, model, registry or cluster
are needed. A normal SDK step cannot satisfy these wire-level assertions.
"""

import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_runtime import step

assert step.LIFECYCLE_FIXTURE_OVERRIDE == "conformance-lifecycle-v1"
assert "site-packages/agent_runtime/step.py" in step.__file__
manifest = step.load_manifest()
assert "model" in manifest and manifest["model"] is None
assert set(step.build_agent(manifest)[1]) == {"lifecycle_fixture"}
mismatch = copy.deepcopy(manifest)
mismatch["tools"][0]["name"] = "unrelated"
try:
    step.build_agent(mismatch)
except ValueError as error:
    assert "do not match" in str(error)
else:
    raise AssertionError("SDK manifest mismatch validation was bypassed")

with tempfile.TemporaryDirectory() as root:
    for case in sorted(step.CASES):
        sandbox = Path(root) / case
        env = {**os.environ, "AGENT_SANDBOX_DIR": str(sandbox)}

        def run(boundary, timeout=5, case=case, env=env):
            body = json.dumps({"boundary": boundary, "task": {"lifecycle_case": case}}).encode()
            return subprocess.run(
                [sys.executable, "-I", "-m", "agent_runtime.step"],
                check=False,
                input=str(len(body)).encode() + b"\n" + body,
                env=env,
                timeout=timeout,
                capture_output=True,
            )

        first = run(0)
        assert first.returncode == 0, first.stderr
        assert json.loads(first.stdout)["done"] is False
        last = run(1)
        if case == "retry_exhaustion":
            assert last.returncode == 0
            try:
                json.loads(last.stdout)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid wire was normalized")
        else:
            assert last.returncode == 2, last.stderr
            assert json.loads(last.stdout)["done"] is True
print("installed lifecycle fixture: all eight cases and standard SDK validators verified")

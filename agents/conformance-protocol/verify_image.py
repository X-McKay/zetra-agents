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

assert step.PROTOCOL_FIXTURE_OVERRIDE == "conformance-protocol-v1"
assert "site-packages/agent_runtime/step.py" in step.__file__
manifest = step.load_manifest()
assert set(step.build_agent(manifest)[1]) == {"protocol_fixture"}
mismatch = copy.deepcopy(manifest)
mismatch["tools"][0]["name"] = "unrelated"
try:
    step.build_agent(mismatch)
except ValueError as error:
    assert "do not match" in str(error)
else:
    raise AssertionError("SDK manifest mismatch validation was bypassed")

with tempfile.TemporaryDirectory() as root:
    for case in ("control", *sorted(step.FAULTS)):
        sandbox = Path(root) / case
        env = {**os.environ, "AGENT_SANDBOX_DIR": str(sandbox)}

        def run(boundary, timeout=5, case=case, env=env):
            body = json.dumps({"boundary": boundary, "task": {"protocol_case": case}}).encode()
            return subprocess.run(
                [sys.executable, "-I", "-m", "agent_runtime.step"],
                check=False,
                input=str(len(body)).encode() + b"\n" + body,
                env=env,
                timeout=timeout,
                capture_output=True,
            )

        first = run(0)
        assert first.returncode == (2 if case == "control" else 0), first.stderr
        assert json.loads(first.stdout)["done"] is (case == "control")
        if case == "control":
            continue
        if case == "hang":
            try:
                run(1, timeout=0.25)
            except subprocess.TimeoutExpired as exc:
                assert not exc.output
            else:
                raise AssertionError("hang returned")
            continue
        fault = run(1)
        assert fault.returncode == 0, fault.stderr
        if case == "stdout_10mib":
            assert len(fault.stdout) == 10 * 1024 * 1024
        elif case == "invalid_json":
            try:
                json.loads(fault.stdout)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid JSON normalized")
        else:
            response = json.loads(fault.stdout)
            assert response["boundary"] == (2 if case == "wrong_boundary" else 1)
            assert response["done"] is (case == "done_true_rc0")
print("installed protocol fixture: control and all five wire faults verified")

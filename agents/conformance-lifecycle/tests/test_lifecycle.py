"""Exercise actual subprocess stdout/exit faults, never SDK-normalized tool output."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

STEP = Path(__file__).resolve().parents[1] / "src/lifecycle_fixture/step.py"


def frame(case, boundary):
    body = json.dumps({"boundary": boundary, "task": {"lifecycle_case": case}}).encode()
    return str(len(body)).encode() + b"\n" + body


def execute(tmp_path, case, boundary):
    return subprocess.run(
        [sys.executable, "-u", str(STEP)],
        check=False,
        input=frame(case, boundary),
        capture_output=True,
        timeout=5,
        env={**os.environ, "AGENT_SANDBOX_DIR": str(tmp_path)},
    )


@pytest.mark.parametrize(
    "case",
    ["success", "cancel", "aps_down", "finalizer", "worker_kill", "terminate", "activity_crash"],
)
def test_two_real_boundaries_without_model_network_or_grant_access(tmp_path, case):
    first = execute(tmp_path, case, 0)
    assert first.returncode == 0
    assert json.loads(first.stdout)["done"] is False
    original = (tmp_path / "state/state.json").read_bytes()
    last = execute(tmp_path, case, 1)
    assert last.returncode == 2
    assert json.loads(last.stdout)["done"] is True
    assert (tmp_path / "state/state.json").read_bytes() == original


def test_retry_exhaustion_repeats_actual_invalid_wire_after_checkpoint(tmp_path):
    assert execute(tmp_path, "retry_exhaustion", 0).returncode == 0
    for _ in range(3):
        failed = execute(tmp_path, "retry_exhaustion", 1)
        assert failed.returncode == 0
        with pytest.raises(ValueError):
            json.loads(failed.stdout)


def test_unknown_case_and_missing_checkpoint_fail_closed(tmp_path):
    assert execute(tmp_path, "unbound", 0).returncode == 5
    assert execute(tmp_path, "success", 1).returncode == 5


def test_dockerfile_explicitly_installs_and_checks_override():
    dockerfile = STEP.parents[2] / "Dockerfile"
    text = dockerfile.read_text()
    assert "LIFECYCLE_FIXTURE_OVERRIDE" in text
    assert "agent_runtime.step" in text and "agent_runtime.wait" in text
    assert "RUN /app/.venv/bin/python -I /tmp/verify_lifecycle_image.py" in text


def test_factory_refuses_unpatched_sdk_and_declares_exact_manifest_tools(monkeypatch):
    import yaml
    from agent_runtime import step

    from lifecycle_fixture.agent import create_agent

    monkeypatch.delattr(step, "LIFECYCLE_FIXTURE_OVERRIDE", raising=False)
    with pytest.raises(RuntimeError, match="installed step override"):
        create_agent(None)
    monkeypatch.setattr(
        step, "LIFECYCLE_FIXTURE_OVERRIDE", "conformance-lifecycle-v1", raising=False
    )
    manifest = yaml.safe_load((STEP.parents[2] / "agent.yaml").read_text())
    assert {t.fn.__name__: t.effect for t in create_agent(None)["tools"]} == {
        t["name"]: t["effect"] for t in manifest["tools"]
    }


def test_override_keeps_real_sdk_manifest_validation(monkeypatch, tmp_path):
    import copy

    import agent_runtime
    from agent_runtime import step as sdk_step

    from lifecycle_fixture import step as fixture_step

    monkeypatch.setitem(sys.modules, "agent_runtime._lifecycle_sdk_step", sdk_step)
    monkeypatch.setattr(agent_runtime, "step", fixture_step)
    monkeypatch.setenv("AGENT_APP_DIR", str(tmp_path))
    (tmp_path / "agent.yaml").write_text((STEP.parents[2] / "agent.yaml").read_text())
    (tmp_path / "lifecycle_fixture").mkdir()
    (tmp_path / "lifecycle_fixture/instructions.md").write_text("Lifecycle fixture")
    manifest = fixture_step.load_manifest()
    _, tools = fixture_step.build_agent(manifest)
    assert set(tools) == {"lifecycle_fixture"}
    for invalid in (
        [{"name": "unrelated", "effect": "workspace_read"}],
        [{"name": "lifecycle_fixture", "effect": "workspace_write"}],
    ):
        mismatch = copy.deepcopy(manifest)
        mismatch["tools"] = invalid
        with pytest.raises(ValueError, match="do not match"):
            fixture_step.build_agent(mismatch)

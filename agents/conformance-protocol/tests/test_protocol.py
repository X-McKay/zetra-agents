"""Exercise actual subprocess stdout/exit faults, never SDK-normalized tool output."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

STEP = Path(__file__).resolve().parents[1] / "src/protocol_fixture/step.py"


def frame(case, boundary):
    body = json.dumps({"boundary": boundary, "task": {"protocol_case": case}}).encode()
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


def test_control_completes_without_model_or_network(tmp_path):
    result = execute(tmp_path, "control", 0)
    assert result.returncode == 2, result.stderr
    assert json.loads(result.stdout) == {
        "boundary": 0,
        "kind": "tool",
        "done": True,
        "tool": "protocol_fixture",
        "usage": None,
        "summary": "healthy control",
    }


@pytest.mark.parametrize(
    "case", ["stdout_10mib", "invalid_json", "wrong_boundary", "done_true_rc0"]
)
def test_faults_follow_one_durable_checkpoint_and_do_not_advance_it(tmp_path, case):
    checkpoint = execute(tmp_path, case, 0)
    assert checkpoint.returncode == 0
    assert json.loads(checkpoint.stdout)["done"] is False
    original = (tmp_path / "state/state.json").read_bytes()
    for _ in range(3):  # the restored committed checkpoint reproduces the same fault
        result = execute(tmp_path, case, 1)
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "state/state.json").read_bytes() == original
        if case == "stdout_10mib":
            assert len(result.stdout) == 10 * 1024 * 1024
        elif case == "invalid_json":
            with pytest.raises(ValueError):
                json.loads(result.stdout)
        else:
            doc = json.loads(result.stdout)
            assert doc["boundary"] == (2 if case == "wrong_boundary" else 1)
            assert doc["done"] is (case == "done_true_rc0")


def test_hang_never_returns_or_prints_before_external_timeout(tmp_path):
    assert execute(tmp_path, "hang", 0).returncode == 0
    with pytest.raises(subprocess.TimeoutExpired) as exc:
        subprocess.run(
            [sys.executable, "-u", str(STEP)],
            input=frame("hang", 1),
            check=False,
            capture_output=True,
            timeout=0.25,
            env={**os.environ, "AGENT_SANDBOX_DIR": str(tmp_path)},
        )
    assert not exc.value.output


def test_unknown_case_and_missing_checkpoint_are_not_normalized_into_a_fault(tmp_path):
    assert execute(tmp_path, "not-a-case", 0).returncode == 5
    assert execute(tmp_path, "invalid_json", 1).returncode == 5


def test_dockerfile_explicitly_installs_and_checks_override():
    dockerfile = STEP.parents[2] / "Dockerfile"
    text = dockerfile.read_text()
    assert "PROTOCOL_FIXTURE_OVERRIDE" in text
    assert "agent_runtime.step" in text and "agent_runtime.wait" in text
    assert "RUN /app/.venv/bin/python -I /tmp/verify_protocol_image.py" in text


def test_factory_refuses_unpatched_sdk_and_declares_exact_manifest_tools(monkeypatch):
    import yaml
    from agent_runtime import step

    from protocol_fixture.agent import create_agent

    monkeypatch.delattr(step, "PROTOCOL_FIXTURE_OVERRIDE", raising=False)
    with pytest.raises(RuntimeError, match="installed step override"):
        create_agent(None)
    monkeypatch.setattr(step, "PROTOCOL_FIXTURE_OVERRIDE", "conformance-protocol-v1", raising=False)
    manifest = yaml.safe_load((STEP.parents[2] / "agent.yaml").read_text())
    assert {t.fn.__name__: t.effect for t in create_agent(None)["tools"]} == {
        t["name"]: t["effect"] for t in manifest["tools"]
    }


def test_override_keeps_real_sdk_manifest_validation(monkeypatch, tmp_path):
    import copy

    import agent_runtime
    from agent_runtime import step as sdk_step

    from protocol_fixture import step as fixture_step

    monkeypatch.setitem(sys.modules, "agent_runtime._protocol_sdk_step", sdk_step)
    monkeypatch.setattr(agent_runtime, "step", fixture_step)
    monkeypatch.setenv("AGENT_APP_DIR", str(tmp_path))
    (tmp_path / "agent.yaml").write_text((STEP.parents[2] / "agent.yaml").read_text())
    (tmp_path / "protocol_fixture").mkdir()
    (tmp_path / "protocol_fixture/instructions.md").write_text("Protocol fixture")
    manifest = fixture_step.load_manifest()
    _, tools = fixture_step.build_agent(manifest)
    assert set(tools) == {"protocol_fixture"}
    for invalid in (
        [{"name": "unrelated", "effect": "workspace_read"}],
        [{"name": "protocol_fixture", "effect": "workspace_write"}],
    ):
        mismatch = copy.deepcopy(manifest)
        mismatch["tools"] = invalid
        with pytest.raises(ValueError, match="do not match"):
            fixture_step.build_agent(mismatch)

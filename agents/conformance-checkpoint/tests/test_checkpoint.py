import json

import pytest

from checkpoint_fixture import step

RUN = "4bc9beea-e690-43eb-bf58-211044970094"
SESSION = "5de29de8-0566-42a7-a169-ec41cab71691"


def request(boundary, case="b"):
    return {"boundary": boundary, "task": {"checkpoint_case": case, "run_id": RUN}}


def test_read_completion_signal_is_before_done_and_workspace_commit(tmp_path):
    signals = []
    reads = []

    def completed():
        reads.append("real read returned")

    def signal(event):
        signals.append(event)
        if event["stage"] == "read_complete":
            assert reads == ["real read returned"]
            assert not (tmp_path / "state/1.done").exists()
            assert json.loads((tmp_path / "state/state.json").read_text())["next"] == 1

    step.execute(
        request(0), tmp_path, read_fn=completed, signal=signal, session=SESSION, generation=1
    )
    baseline = (tmp_path / "workspace/checkpoint.json").read_bytes()
    step.execute(
        request(1),
        tmp_path,
        read_fn=completed,
        signal=signal,
        session=SESSION,
        generation=1,
        pause=lambda: None,
    )
    assert [e["stage"] for e in signals] == [
        "boundary_start",
        "done",
        "boundary_start",
        "read_complete",
        "done",
    ]
    assert (tmp_path / "state/1.done").exists()
    assert (tmp_path / "workspace/checkpoint.json").read_bytes() != baseline
    assert json.loads((tmp_path / "state/state.json").read_text())["next"] == 2
    assert all(e["session_id"] == SESSION and e["run_id"] == RUN for e in signals)


def test_kill_before_done_leaves_prior_committed_state(tmp_path):
    step.execute(
        request(0),
        tmp_path,
        read_fn=lambda: None,
        signal=lambda _: None,
        session=SESSION,
        generation=1,
    )
    original = (tmp_path / "state/state.json").read_bytes()

    def kill():
        raise InterruptedError("test process killed")

    with pytest.raises(InterruptedError):
        step.execute(
            request(1),
            tmp_path,
            read_fn=lambda: None,
            signal=lambda _: None,
            session=SESSION,
            generation=1,
            pause=kill,
        )
    assert (tmp_path / "state/state.json").read_bytes() == original
    assert not (tmp_path / "state/1.done").exists()
    # A genuine restored generation resumes at the old checkpoint and reads once.
    calls = []
    step.execute(
        request(1),
        tmp_path,
        read_fn=lambda: calls.append(1),
        signal=lambda _: None,
        session=SESSION,
        generation=2,
        pause=lambda: pytest.fail("no second hold"),
    )
    assert calls == [1]


def test_finished_boundary_cannot_execute_again(tmp_path):
    for n in range(3):
        out, rc = step.execute(
            request(n, "control"),
            tmp_path,
            read_fn=lambda: None,
            signal=lambda _: None,
            session=SESSION,
            generation=1,
        )
        assert out["boundary"] == n and out["done"] == (n == 2)
        assert rc == (2 if n == 2 else 0)
    with pytest.raises(ValueError, match="checkpoint boundary mismatch"):
        step.execute(
            request(1, "control"),
            tmp_path,
            read_fn=lambda: pytest.fail("duplicate read"),
            signal=lambda _: None,
            session=SESSION,
            generation=2,
        )


def test_failed_read_never_emits_completion_or_done(tmp_path):
    signals = []
    step.execute(
        request(0),
        tmp_path,
        read_fn=lambda: None,
        signal=lambda _: None,
        session=SESSION,
        generation=1,
    )

    def failed():
        raise RuntimeError("not evidence")

    with pytest.raises(RuntimeError):
        step.execute(
            request(1),
            tmp_path,
            read_fn=failed,
            signal=signals.append,
            session=SESSION,
            generation=1,
        )
    assert [e["stage"] for e in signals] == ["boundary_start"]
    assert not (tmp_path / "state/1.done").exists()


async def test_registered_read_uses_ordinary_context_and_never_returns_tool_content(monkeypatch):
    from types import SimpleNamespace

    from agent_runtime import step as installed

    from checkpoint_fixture.agent import create_agent

    monkeypatch.setattr(
        installed, "CHECKPOINT_FIXTURE_OVERRIDE", step.CHECKPOINT_FIXTURE_OVERRIDE, raising=False
    )
    calls = []

    async def mcp(backend, tool, arguments):
        calls.append((backend, tool, arguments))
        return {"text": "sensitive cluster contents are not evidence"}

    tool = create_agent(SimpleNamespace(mcp=mcp))["tools"][0]
    assert tool.effect == "remote_read"
    assert await tool.fn() == {"completed": True}
    assert calls == [("kubernetes", "pods_list_in_namespace", {"namespace": "tenant-test"})]


def test_metadata_rejects_wrong_run_generation_and_boundary_before_read(tmp_path):
    for req, gen in [
        (request(3), 1),
        (request(0, "unknown"), 1),
        (request(0), 3),
        ({"boundary": 0, "task": {"checkpoint_case": "a", "run_id": "bad"}}, 1),
    ]:
        with pytest.raises((ValueError, TypeError)):
            step.execute(
                req,
                tmp_path,
                read_fn=lambda: pytest.fail("unexpected read"),
                signal=lambda _: None,
                session=SESSION,
                generation=gen,
            )

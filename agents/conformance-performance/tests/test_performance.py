import hashlib
import json

import pytest

from performance_fixture.step import execute

RUN = "4bc9beea-e690-43eb-bf58-211044970094"
SESSION = "5de29de8-0566-42a7-a169-ec41cab71691"
TOKEN = "test-opaque-credential-never-output"


def invoke(root, *, mode="pair", boundary=0, payload=0, read=None, token=None, sleep=None):
    return execute(
        {
            "boundary": boundary,
            "task": {"performance_mode": mode, "run_id": RUN, "payload_bytes": payload},
        },
        root,
        read_fn=read or (lambda: {"completed": True}),
        token_fn=token or (lambda: TOKEN),
        sleep_fn=sleep or (lambda _: None),
        session=SESSION,
        generation=1,
        process_id=100 + boundary,
    )


def test_two_fresh_process_boundaries_reuse_only_token_fingerprint(tmp_path):
    calls = []
    for boundary in (0, 1):
        out, rc = invoke(
            tmp_path, boundary=boundary, read=lambda: calls.append(1) or {"completed": True}
        )
        assert out["done"] == (boundary == 1) and rc == (2 if boundary else 0)
    assert calls == [1, 1]
    records = json.loads((tmp_path / "workspace/performance.json").read_text())["records"]
    assert [r["process_id"] for r in records] == [100, 101]
    assert {r["token_sha256"] for r in records} == {hashlib.sha256(TOKEN.encode()).hexdigest()}
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert TOKEN not in path.read_text()


def test_missing_real_mcp_completion_cannot_create_done_or_record(tmp_path):
    with pytest.raises(ValueError):
        invoke(tmp_path, read=lambda: {"completed": False})
    assert not (tmp_path / "state/0.done").exists()
    assert not (tmp_path / "workspace/performance.json").exists()


def test_real_sdk_failure_propagates_without_checkpoint(tmp_path):
    def fail():
        raise RuntimeError("private-server-response")

    with pytest.raises(RuntimeError):
        invoke(tmp_path, read=fail)
    assert not (tmp_path / "state/0.done").exists()


@pytest.mark.parametrize("size", [0, 1 << 20, 64 << 20])
def test_exact_payload_bytes_are_distinct_from_metadata_and_archive(tmp_path, size):
    out, rc = invoke(
        tmp_path,
        mode="snapshot",
        payload=size,
        read=lambda: pytest.fail("snapshot fixture must not issue MCP"),
        token=lambda: pytest.fail("snapshot fixture must not request a token"),
    )
    assert out["done"] and rc == 2
    assert (tmp_path / "workspace/payload.bin").stat().st_size == size
    result = json.loads((tmp_path / "workspace/performance.json").read_text())
    assert result["records"][0]["payload_bytes"] == size
    assert result["records"][0]["token_sha256"] is None


@pytest.mark.parametrize(
    "mode,boundary,payload",
    [
        ("other", 0, 0),
        ("pair", 2, 0),
        ("pair", 0, 1),
        ("snapshot", 0, 65 << 20),
        ("snapshot", 0, True),
    ],
)
def test_unbounded_or_wrong_tasks_rejected_before_writes(tmp_path, mode, boundary, payload):
    with pytest.raises(ValueError):
        invoke(tmp_path, mode=mode, boundary=boundary, payload=payload)
    assert list(tmp_path.iterdir()) == []


def test_state_must_match_exact_boundary_and_run(tmp_path):
    invoke(tmp_path)
    with pytest.raises(ValueError):
        invoke(tmp_path)
    state = json.loads((tmp_path / "state/state.json").read_text())
    state["run_id"] = "another-run"
    (tmp_path / "state/state.json").write_text(json.dumps(state))
    with pytest.raises(ValueError):
        invoke(tmp_path, boundary=1)


def test_saturation_hold_is_fixed_and_bounded_not_task_controlled(tmp_path):
    sleeps = []
    invoke(tmp_path, mode="saturation", sleep=sleeps.append)
    invoke(tmp_path, mode="saturation", boundary=1, sleep=sleeps.append)
    assert sleeps == [20]

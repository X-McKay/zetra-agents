"""Real scheduling and responses, never normalization of transport failures into 403."""

import asyncio
import json
import time
from itertools import pairwise

import httpx
import pytest


def test_five_independent_requests_do_not_wait_for_slow_responses():
    from conformance.fail_closed import poll

    seen = []

    async def answer(request):
        seen.append((time.monotonic(), request))
        await asyncio.sleep(0.3)
        return httpx.Response(403 if len(seen) == 2 else 200, text="private-body")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            return await poll(
                client, "https://gateway", "mcp.internal", "private-token", "a" * 16, 1
            )

    result = asyncio.run(run())
    assert len(seen) == len(result["requests"]) == 5
    assert max(b[0] - a[0] for a, b in pairwise(seen)) < 0.28
    assert {r.headers["authorization"] for _, r in seen} == {"Bearer private-token"}
    assert [r["sequence"] for r in result["requests"]] == list(range(1, 6))
    assert len({r["trace_id"] for r in result["requests"]}) == 5
    assert all(r["finished_ns"] >= r["started_ns"] for r in result["requests"])
    assert "private" not in json.dumps(result)


def test_transport_failure_remains_failure_with_sequence_and_timing():
    from conformance.fail_closed import poll

    async def answer(request):
        raise httpx.ReadTimeout("private-token", request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            return await poll(
                client, "https://gateway", "mcp.internal", "private-token", "a" * 16, 1
            )

    result = asyncio.run(run())
    assert len(result["requests"]) == 5
    assert all(r["status"] is None and r["error"] == "ReadTimeout" for r in result["requests"])
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize(
    "duration,marker", [(0, "a" * 16), (241, "a" * 16), (1.5, "a" * 16), (1, "bad")]
)
def test_invalid_schedule_never_calls_network(duration, marker):
    from conformance.fail_closed import poll

    with pytest.raises(ValueError):
        asyncio.run(poll(None, "https://gateway", "host", "token", marker, duration))


def test_expired_token_is_refreshed_once_then_refused_before_traffic(monkeypatch):
    from agent_runtime import identity as identity_module

    from conformance import agent, fail_closed

    invalidated = []
    who = type(
        "Identity",
        (),
        {
            "token": lambda self: "private-token",
            "invalidate": lambda self, token: invalidated.append(token),
        },
    )()
    monkeypatch.setattr(identity_module, "identity", lambda: who)
    monkeypatch.setattr(agent, "claims_of", lambda _: {"exp": time.time() + 10})
    with pytest.raises(ValueError, match="lifetime"):
        asyncio.run(fail_closed.probe_fail_closed("a" * 16, "60"))
    assert invalidated == ["private-token"]


def test_only_compact_summary_reaches_model_raw_safe_evidence_is_saved(monkeypatch, tmp_path):
    from agent_runtime import identity as identity_module

    from conformance import agent, fail_closed

    who = type("Identity", (), {"token": lambda self: "private-token"})()
    monkeypatch.setattr(identity_module, "identity", lambda: who)
    monkeypatch.setattr(identity_module, "gateway_url", lambda: "https://gateway")
    monkeypatch.setattr(identity_module, "env", lambda _: "mcp.internal")
    monkeypatch.setattr(identity_module, "tls_verify", lambda: True)
    monkeypatch.setattr(agent, "claims_of", lambda _: {"exp": time.time() + 300})
    path = tmp_path / "requests.json"
    monkeypatch.setattr(fail_closed, "EVIDENCE", path)

    async def poll(*args):
        return {"requests": [{"sequence": i, "status": 200} for i in range(300)]}

    monkeypatch.setattr(fail_closed, "poll", poll)
    summary = asyncio.run(fail_closed.probe_fail_closed("a" * 16, "60"))
    assert len(json.dumps(summary)) < 200 and summary["requests"] == 300
    assert len(json.loads(path.read_text())["requests"]) == 300
    assert path.stat().st_mode & 0o777 == 0o600
    assert "private-token" not in path.read_text()

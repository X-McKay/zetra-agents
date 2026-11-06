"""The live probe keeps issuing real requests after denials, without exporting a token."""

import asyncio
import json

import httpx
import pytest


def test_probe_keeps_one_token_and_continues_after_denial():
    from conformance import revocation

    requests = []

    def answer(request):
        requests.append(request)
        return httpx.Response(403 if len(requests) == 2 else 200, text="private response")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            return await revocation.poll_gateway(
                client,
                "https://gateway.test",
                "mcp.agents.internal",
                "private-token",
                "1234567890abcdef",
                duration=0.04,
                interval=0.005,
            )

    result = asyncio.run(run())
    assert len(requests) >= 3
    assert all(r.headers["authorization"] == "Bearer private-token" for r in requests)
    assert all(r.url.path == "/kubernetes/mcp" for r in requests)
    traces = [r.headers["traceparent"].split("-")[1] for r in requests]
    assert len(set(traces)) == len(traces)
    assert all(t.startswith("1234567890abcdef") for t in traces)
    assert result["statuses"]["403"] == 1 and result["statuses"]["200"] >= 2
    assert "private" not in json.dumps(result)


def test_transport_failure_is_not_a_denial():
    from conformance import revocation

    def answer(request):
        raise httpx.ConnectError("private-token", request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            return await revocation.poll_gateway(
                client,
                "https://gateway.test",
                "mcp.agents.internal",
                "private-token",
                "1234567890abcdef",
                duration=0.02,
                interval=0.005,
            )

    result = asyncio.run(run())
    assert result["errors"] > 0 and result["statuses"] == {}
    assert "private-token" not in json.dumps(result)


@pytest.mark.parametrize(
    "duration,marker", [(0, "1234567890abcdef"), (241, "1234567890abcdef"), (30, "bad")]
)
def test_invalid_probe_input_is_rejected_before_network(duration, marker):
    from conformance import revocation

    with pytest.raises(ValueError):
        asyncio.run(
            revocation.poll_gateway(
                None, "https://gateway", "host", "key", marker, duration=duration
            )
        )

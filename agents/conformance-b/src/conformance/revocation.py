"""Bounded T15/T20 traffic; the harness observes gateway/APS logs while this tool runs."""

import asyncio
import re
import time

import httpx


async def poll_gateway(client, url, host, token, marker, *, duration=180.0, interval=0.1):
    if not 0 < duration <= 240 or not re.fullmatch(r"[0-9a-f]{16}", marker):
        raise ValueError("invalid revocation probe duration or marker")
    if not 0.001 <= interval <= 1:
        raise ValueError("invalid revocation probe interval")
    started, sequence = time.monotonic(), 0
    result = {"statuses": {}, "errors": 0, "marker": marker}
    try:
        async with asyncio.timeout(duration):
            while True:
                sequence += 1
                trace = marker + f"{sequence:016x}"
                try:
                    # initialize is side-effect-free and needs no existing MCP session. A
                    # fresh request still traverses the complete identity and release checks.
                    response = await client.post(
                        url + "/kubernetes/mcp",
                        headers={
                            "Host": host,
                            "Authorization": "Bearer " + token,
                            "Accept": "application/json, text/event-stream",
                            "traceparent": f"00-{trace}-0000000000000001-01",
                        },
                        json={
                            "jsonrpc": "2.0",
                            "id": sequence,
                            "method": "initialize",
                            "params": {
                                "protocolVersion": "2025-03-26",
                                "capabilities": {},
                                "clientInfo": {"name": "conformance-revocation", "version": "1"},
                            },
                        },
                    )
                    key = str(response.status_code)
                    result["statuses"][key] = result["statuses"].get(key, 0) + 1
                except httpx.HTTPError:
                    result["errors"] += 1  # never body, headers, token, or exception message
                await asyncio.sleep(interval)
    except TimeoutError:
        pass
    result["elapsed_ms"] = (time.monotonic() - started) * 1000
    return result


async def probe_revocation(marker: str, duration: str = "180") -> dict:
    """Keep bounded MCP requests active for T15/T20; continue after 403 and never return a token."""
    from agent_runtime.identity import env, gateway_url, identity, tls_verify

    from conformance.agent import claims_of

    seconds = float(duration)
    if not 0 < seconds <= 240 or not re.fullmatch(r"[0-9a-f]{16}", marker):
        raise ValueError("invalid revocation probe input")
    who = identity()
    token = who.token()
    if claims_of(token).get("exp", 0) - time.time() < seconds + 15:
        who.invalidate(token)
        token = who.token()
    if claims_of(token).get("exp", 0) - time.time() < seconds + 15:
        raise ValueError("token lifetime is too short for the bounded probe")
    async with httpx.AsyncClient(
        verify=tls_verify(),
        timeout=2.0,
        follow_redirects=False,
    ) as client:
        return await poll_gateway(
            client,
            gateway_url(),
            env("AGENT_MCP_HOST"),
            token,
            marker,
            duration=seconds,
        )

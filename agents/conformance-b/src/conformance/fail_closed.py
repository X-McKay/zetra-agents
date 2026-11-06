"""T17: absolute 5 Hz request scheduling, with bounded token-free workspace evidence."""

import asyncio
import json
import pathlib
import re
import time

import httpx

EVIDENCE = pathlib.Path("/sandbox/workspace/t17/requests.json")


async def poll(client, url, host, token, marker, duration):
    if (
        type(duration) is not int
        or not 1 <= duration <= 240
        or not re.fullmatch(r"[0-9a-f]{16}", marker)
    ):
        raise ValueError("invalid fail-closed probe schedule")
    origin = time.monotonic_ns()
    epoch = time.time_ns()

    async def request(sequence):
        trace = marker + f"{sequence:016x}"
        started = time.time_ns()
        row = {
            "sequence": sequence,
            "trace_id": trace,
            "started_ns": started,
            "offset_ns": time.monotonic_ns() - origin,
            "status": None,
            "error": None,
        }
        try:
            # Each independent request traverses ext_authz. A timeout is never retried.
            # Read status only, bounding memory even if a backend returns a huge body.
            async with client.stream(
                "POST",
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
                        "clientInfo": {"name": "conformance-fail-closed", "version": "1"},
                    },
                },
            ) as response:
                row["status"] = response.status_code
        except httpx.HTTPError as exc:
            row["error"] = type(exc).__name__
        row["finished_ns"] = time.time_ns()
        return row

    tasks = []
    try:
        for index in range(duration * 5):
            await asyncio.sleep(max(0, (origin + index * 200_000_000 - time.monotonic_ns()) / 1e9))
            tasks.append(asyncio.create_task(request(index + 1)))
        rows = await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return {
        "schema": "t17-v1",
        "marker": marker,
        "duration_seconds": duration,
        "rate": 5,
        "origin_ns": epoch,
        "requests": rows,
    }


async def probe_fail_closed(marker: str, duration: str = "180") -> dict:
    """Send exactly five real gateway requests each second and save complete T17 evidence."""
    from agent_runtime.identity import env, gateway_url, identity, tls_verify

    from conformance.agent import claims_of

    seconds = int(duration)
    if not 60 <= seconds <= 240 or not re.fullmatch(r"[0-9a-f]{16}", marker):
        raise ValueError("invalid fail-closed probe input")
    who = identity()
    token = who.token()
    if claims_of(token).get("exp", 0) - time.time() < seconds + 15:
        who.invalidate(token)
        token = who.token()
    expires = claims_of(token).get("exp", 0)
    if expires - time.time() < seconds + 15:
        raise ValueError("token lifetime is too short for the bounded probe")
    async with httpx.AsyncClient(
        verify=tls_verify(),
        timeout=3.0,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=20),
    ) as client:
        result = await poll(client, gateway_url(), env("AGENT_MCP_HOST"), token, marker, seconds)
    result["token_expires_ns"] = int(expires * 1e9)
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    EVIDENCE.chmod(0o600)
    return {"marker": marker, "requests": len(result["requests"]), "evidence": "t17/requests.json"}

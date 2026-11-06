import asyncio
import base64
import json
import os
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def jwt(claims: dict) -> str:
    def seg(obj) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return ".".join((seg({"alg": "none"}), seg(claims), "c" * 20))


def tools(tmp_path):
    from conformance.agent import create_agent

    ctx = types.SimpleNamespace(workspace=tmp_path, instructions="", mcp=None)
    return create_agent(ctx)["tools"]


def test_tools_match_the_manifest(tmp_path):
    manifest = yaml.safe_load((ROOT / "agent.yaml").read_text())
    declared = {t["name"]: t["effect"] for t in manifest["tools"]}
    assert {t.fn.__name__: t.effect for t in tools(tmp_path)} == declared


def test_redact_keeps_claims_and_removes_the_token():
    from conformance.agent import redact

    token = jwt({"sub": "x", "aud": "agent-gateway"})
    text, claims = redact(f"before {token} after")
    assert token not in text and text == "before [jwt] after"
    assert claims == [{"sub": "x", "aud": "agent-gateway"}]


def test_probe_connect_reports_a_refused_port(tmp_path):
    probe = next(t.fn for t in tools(tmp_path) if t.fn.__name__ == "probe_connect")
    result = asyncio.run(probe("127.0.0.1", "1"))
    assert result["connected"] is False and result["error"]


def test_probe_env_names_a_variable_holding_a_jwt(tmp_path, monkeypatch):
    from conformance.agent import JWT

    # The release runner's own environment holds a JWT (ACTIONS_ID_TOKEN_REQUEST_TOKEN);
    # the probe is right to report it, so start from an environment without any.
    for name, value in list(os.environ.items()):
        if JWT.search(value):
            monkeypatch.delenv(name)
    monkeypatch.setenv("SMUGGLED", jwt({"sub": "x"}))
    probe = next(t.fn for t in tools(tmp_path) if t.fn.__name__ == "probe_env")
    result = asyncio.run(probe())
    assert result["jwt_in"] == ["SMUGGLED"]
    assert jwt({"sub": "x"}) not in json.dumps(result)


def test_audiences_flattens_and_sorts_string_and_list_aud():
    from conformance.agent import audiences

    claims = [{"aud": "agent-gateway"}, {"aud": ["b", "agent-gateway", ""]}, {"aud": None}, {}]
    assert audiences(claims) == ["agent-gateway", "b"]


def test_mcp_outcome_is_one_word_per_call():
    from conformance.agent import outcome

    assert outcome(403, failed=True) == "deny"
    assert outcome(429, failed=True) == "budget"
    assert outcome(502, failed=True) == "http:502"
    assert outcome(None, failed=True) == "error"
    assert outcome(200, failed=False) == "ok"
    assert outcome(200, failed=False, is_error=True) == "error"


def test_probe_mcp_alternates_tools_and_passes_forged_headers(tmp_path, monkeypatch):
    from conformance import agent

    seen: list[tuple[str, dict]] = []

    async def fake_call(backend, tool, arguments, extra_headers, **_):
        seen.append((tool, extra_headers))
        return "ok" if tool == "pods_list_in_namespace" else "deny"

    monkeypatch.setattr(agent, "mcp_call", fake_call)
    monkeypatch.setattr(
        agent, "identity", lambda: types.SimpleNamespace(token=lambda: jwt({"jti": "j1"}))
    )
    probe = next(t.fn for t in tools(tmp_path) if t.fn.__name__ == "probe_mcp")
    result = asyncio.run(
        probe(
            "pods_list_in_namespace",
            args='{"namespace": "tenant-test"}',
            alt_tool="pods_get",
            rounds="2",
            headers='{"x-agent-principal": "mallory"}',
        )
    )
    assert result["calls"] == ["ok", "deny", "ok", "deny"]
    assert [t for t, _ in seen] == ["pods_list_in_namespace", "pods_get"] * 2
    assert all(h["x-agent-principal"] == "mallory" for _, h in seen)


def test_probe_token_stash_writes_the_token_to_the_workspace_and_reports_no_token(
    tmp_path, monkeypatch
):
    from conformance import agent

    token = jwt({"sub": "x", "aud": ["agent-gateway", "agent-policy-service"]})
    monkeypatch.setattr(agent, "TOKEN_STASH", tmp_path / "t26" / "token")
    monkeypatch.setattr(agent, "identity", lambda: types.SimpleNamespace(token=lambda: token))
    probe = next(t.fn for t in tools(tmp_path) if t.fn.__name__ == "probe_token_stash")
    result = asyncio.run(probe())
    assert (tmp_path / "t26" / "token").read_text() == token
    assert result["mode"] == "0o600" and result["aud"] == ["agent-gateway", "agent-policy-service"]
    assert token not in json.dumps(result)


def test_probe_http_can_present_the_stashed_token(tmp_path, monkeypatch):
    from conformance import agent

    stash = tmp_path / "t26" / "token"
    stash.parent.mkdir()
    stash.write_text("stashed-token\n")
    monkeypatch.setattr(agent, "TOKEN_STASH", stash)
    monkeypatch.setattr(agent, "gateway_url", lambda: "https://gateway.test")
    monkeypatch.setattr(agent, "tls_verify", lambda: False)
    seen = {}

    class Client:
        def __init__(self, **kw):
            seen.update(kw)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, method, path, **kw):
            seen["request"] = (method, path, kw)
            return types.SimpleNamespace(status_code=403, text='{"error":"forbidden"}')

    monkeypatch.setattr(agent.httpx, "Client", Client)
    probe = next(t.fn for t in tools(tmp_path) if t.fn.__name__ == "probe_http")
    result = asyncio.run(probe("mcp.agents.internal", "/kubernetes/mcp", body="{}", auth="stash"))
    assert result["status"] == 403 and seen["auth"] is None
    assert seen["request"][2]["headers"]["Authorization"] == "Bearer stashed-token"


def mock_gateway(seen):
    import httpx

    async def respond(request):
        body = json.loads(request.content) if request.content else {}
        seen.append((request.url.path, request.headers.get("authorization"), body))
        method = body.get("method")
        if request.method == "GET":
            return httpx.Response(405)
        if request.method == "DELETE":
            return httpx.Response(204)
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "initialize":
            result = {
                "protocolVersion": body["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [{"name": "pods_list_in_namespace", "inputSchema": {"type": "object"}}]
            }
        elif body.get("params", {}).get("name") == "pods_get":
            return httpx.Response(403, json={"reason": "deny.route_not_permitted"})
        else:
            result = {"content": [], "isError": False}
        return httpx.Response(
            200,
            headers={"mcp-session-id": "test-session"},
            json={"jsonrpc": "2.0", "id": body.get("id"), "result": result},
        )

    return httpx.MockTransport(respond)


def test_mcp_call_records_tools_http_status_after_403_teardown(monkeypatch, caplog):
    from conformance import agent

    seen, observations = [], []
    token = jwt({"jti": "one-agent-token"})
    monkeypatch.setattr(agent, "tls_verify", lambda: False)
    monkeypatch.setattr(agent, "env", lambda name: "mcp.agents.internal")
    monkeypatch.setattr(agent, "gateway_url", lambda: "https://gateway.test")
    result = asyncio.run(
        agent.mcp_call(
            "kubernetes",
            "pods_get",
            {},
            {"traceparent": "00-" + "1" * 32 + "-" + "2" * 16 + "-01"},
            token=token,
            observations=observations,
            transport=mock_gateway(seen),
        )
    )
    assert result == "deny"
    assert observations == [{"tool": "pods_get", "status": 403, "trace_id": "1" * 32}]
    assert all(auth == "Bearer " + token for _, auth, _ in seen)
    assert token not in json.dumps(observations) + caplog.text


def test_probe_mcp_pins_one_token_for_100_calls_and_measures_only_mcp(tmp_path, monkeypatch):
    from conformance import agent

    token = jwt({"jti": "one-agent-token"})
    identity_calls = []

    def get_token():
        identity_calls.append(1)
        return token

    monkeypatch.setattr(agent, "identity", lambda: types.SimpleNamespace(token=get_token))
    clock = [10.0]
    monkeypatch.setattr(agent, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))

    async def call(backend, tool, arguments, extra_headers, *, token, observations):
        assert token == get_token_value
        clock[0] += 0.03
        observations.append(
            {
                "tool": tool,
                "status": 200 if tool == "pods_list_in_namespace" else 403,
                "trace_id": extra_headers["traceparent"].split("-")[1],
            }
        )
        return "ok" if tool == "pods_list_in_namespace" else "deny"

    async def models(token):
        clock[0] += 18.0  # settlement pauses are outside the MCP time window
        return []

    monkeypatch.setattr(agent, "model_route_calls", models)
    get_token_value = token
    monkeypatch.setattr(agent, "mcp_call", call)
    probe = next(t.fn for t in tools(tmp_path) if t.fn.__name__ == "probe_mcp")
    out = asyncio.run(
        probe("pods_list_in_namespace", alt_tool="pods_get", rounds="50", model_routes="true")
    )
    assert len(identity_calls) == 1 and out["token_jti"] == "one-agent-token"
    assert [r["status"] for r in out["requests"]] == [200, 403] * 50
    assert len({r["trace_id"] for r in out["requests"]}) == 100
    assert out["elapsed_ms"] == pytest.approx(3000) and token not in json.dumps(out)


@pytest.mark.parametrize("main_status", [200, 429])
def test_model_probe_records_status_and_uses_one_token_without_retry(monkeypatch, main_status):
    import httpx

    from conformance import agent

    token = jwt({"jti": "one-agent-token"})
    seen, pauses = [], []

    async def respond(request):
        seen.append((request.url.path, request.headers.get("authorization")))
        body = json.loads(request.content)
        expected_model = (
            "Qwen3.6-35B-A3B-NVFP4" if "llm-main" in request.url.path else "Qwen/Qwen3.5-0.8B"
        )
        assert body["model"] == expected_model and body["max_tokens"] == 1
        assert request.headers["Host"] == "inference.agents.internal"
        return httpx.Response(
            main_status if "llm-main" in request.url.path else 403,
            json={"reason": "deny.budget_exhausted"},
        )

    async def sleep(delay):
        pauses.append(delay)

    monkeypatch.setattr(agent.asyncio, "sleep", sleep)
    monkeypatch.setattr(agent, "tls_verify", lambda: False)
    monkeypatch.setattr(agent, "env", lambda name: "inference.agents.internal")
    monkeypatch.setattr(agent, "gateway_url", lambda: "https://gateway.test")
    out = asyncio.run(agent.model_route_calls(token, transport=httpx.MockTransport(respond)))
    assert [r["status"] for r in out] == [main_status, 403, main_status, 403]
    assert [r["backend"] for r in out] == ["llm-main", "llm-fast"] * 2
    assert len(seen) == 4 and all(auth == "Bearer " + token for _, auth in seen)
    assert pauses == [6.0, 6.0, 6.0]
    assert token not in json.dumps(out)

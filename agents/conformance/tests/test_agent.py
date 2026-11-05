import asyncio
import base64
import json
import os
import types
from pathlib import Path

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
    assert result == {"calls": ["ok", "deny", "ok", "deny"]}
    assert [t for t, _ in seen] == ["pods_list_in_namespace", "pods_get"] * 2
    assert all(h == {"x-agent-principal": "mallory"} for _, h in seen)

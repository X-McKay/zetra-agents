import json
import ssl

import httpx
import pytest

from transport_fixture import probe, step


@pytest.fixture(autouse=True)
def fixed_gateway(monkeypatch):
    monkeypatch.setenv("AGENT_GATEWAY_URL", "https://10.43.250.10:443")


def test_wrong_ca_uses_real_sdk_client_and_requires_no_application_request():
    result = probe.foreign_ca()
    assert result == {
        "positive_status": 200,
        "positive_requests": 1,
        "negative_requests": 0,
        "verify_code": 20,
        "rejected": True,
        "credential_free": True,
    }


def test_disabled_verification_is_not_a_successful_wrong_ca_test(monkeypatch):
    from agent_runtime import identity

    monkeypatch.setattr(identity, "tls_verify", lambda: ssl._create_unverified_context())
    result = probe.foreign_ca()
    assert result["negative_requests"] == 1
    assert result["rejected"] is False


def test_plaintext_timeout_is_missing_evidence_not_rejection(monkeypatch):
    def timeout(*args, **kwargs):
        raise TimeoutError("do not report arbitrary network text")

    monkeypatch.setattr(probe.socket, "create_connection", timeout)
    assert probe.plaintext("10.43.250.10", 443)["result"] == "error"


def test_plaintext_target_is_fixed_and_request_has_no_credentials():
    assert (
        probe.plaintext_request()
        == b"GET /v1/token HTTP/1.1\r\nHost: token.agents.internal\r\nConnection: close\r\n\r\n"
    )
    for host, port in [("example.org", 443), ("10.43.250.10", 80), ("127.0.0.1", 443)]:
        with pytest.raises(ValueError):
            probe.plaintext(host, port)


def test_refusal_classifier_never_accepts_http_success_or_unrelated_error():
    assert probe.classify_plaintext(b"", reset=False) == "closed_without_http"
    assert probe.classify_plaintext(b"", reset=True) == "connection_reset"
    assert probe.classify_plaintext(b"HTTP/1.1 200 OK\r\n\r\n", reset=False) == "unexpected_http"
    assert (
        probe.classify_plaintext(b"HTTP/1.1 403 Forbidden\r\n\r\n", reset=False)
        == "unexpected_http"
    )


def test_gateway_positive_uses_same_sdk_tls_and_no_bearer(monkeypatch):
    requests = []

    def respond(req):
        requests.append(req)
        return httpx.Response(400)

    monkeypatch.setenv("AGENT_GATEWAY_URL", "https://10.43.250.10:443")
    from agent_runtime.identity import AgentIdentity

    client = AgentIdentity(transport=httpx.MockTransport(respond))._client()
    result = probe.gateway_positive(client)
    assert result["status"] == 400 and result["tls_url"] is True
    assert "authorization" not in requests[0].headers
    assert requests[0].headers["host"] == "token.agents.internal"
    assert requests[0].content == b""


def test_driver_commits_only_sanitized_probe_metadata(tmp_path):
    report = {
        "version": 1,
        "positive": {"status": 400},
        "plaintext": {"result": "closed_without_http"},
        "foreign_ca": {"rejected": True},
    }
    request = {"boundary": 0, "task": {"transport_case": "tls"}}
    response, code = step.execute(request, tmp_path, probe_fn=lambda: report)
    assert code == 2 and response["done"] is True
    assert json.loads((tmp_path / "workspace/transport.json").read_text()) == report
    assert json.loads((tmp_path / "state/state.json").read_text())["next"] == 1
    assert (tmp_path / "state/0.done").is_file()
    assert "Bearer" not in json.dumps(response)


def test_driver_rejects_extra_task_and_wrong_boundary(tmp_path):
    for req in [
        {"boundary": 1, "task": {"transport_case": "tls"}},
        {"boundary": 0, "task": {"transport_case": "tls", "target": "evil"}},
    ]:
        with pytest.raises(ValueError):
            step.execute(req, tmp_path, probe_fn=lambda: pytest.fail("must not call"))


def test_factory_keeps_standard_sdk_tool_contract(monkeypatch):
    import inspect

    from agent_runtime import step as sdk_step

    from transport_fixture.agent import create_agent

    monkeypatch.setattr(
        sdk_step, "TRANSPORT_FIXTURE_OVERRIDE", "conformance-transport-v1", raising=False
    )
    tool = create_agent(None)["tools"][0]
    assert inspect.iscoroutinefunction(tool.fn) and inspect.getdoc(tool.fn)


def test_real_driver_uses_sdk_manifest_factory_before_importing_probe(tmp_path, monkeypatch):
    from types import SimpleNamespace

    calls = []
    monkeypatch.setattr(probe, "run", lambda: pytest.fail("must use validated tool factory"))

    async def run_probe():
        calls.append("probe")
        return {"version": 1}

    monkeypatch.setattr(
        step, "load_manifest", lambda: calls.append("manifest") or {"name": "fixture"}
    )
    monkeypatch.setattr(
        step,
        "build_agent",
        lambda m: (calls.append("factory"), {"transport_probe": SimpleNamespace(fn=run_probe)}),
    )
    step.execute({"boundary": 0, "task": {"transport_case": "tls"}}, tmp_path)
    assert calls == ["manifest", "factory", "probe"]

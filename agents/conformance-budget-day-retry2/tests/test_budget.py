import json
from pathlib import Path

import httpx

from budget_fixture import step


def test_real_http_status_usage_and_no_body_or_bearer_leak():
    def respond(request):
        assert request.headers["Authorization"] == "Bearer private-token"
        assert json.loads(request.content)["messages"][0]["content"] == "x" * 46
        return httpx.Response(
            429,
            json={
                "reason": "deny.budget_exhausted",
                "decision_id": "6f1d2c3e-0000-4000-8000-000000000002",
                "body": "private-token",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond), base_url="https://gateway") as client:
        result = step.call("denied", client=client, token="private-token")
    assert result["status"] == 429
    assert result["reason"] == "deny.budget_exhausted"
    assert "private-token" not in json.dumps(result)


def test_http_errors_are_not_retried_or_replaced():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(429, text="arbitrary bearer material")

    with httpx.Client(transport=httpx.MockTransport(respond), base_url="https://gateway") as client:
        result = step.call("unexpected", client=client, token="private")
    assert len(requests) == 1 and result["status"] == 429
    assert result.get("reason") is None
    assert "bearer" not in json.dumps(result)


def fake_call(label, hold_ms=0):
    return {
        "label": label,
        "status": 429
        if label in {"exhausted", "tampered", "restored", "after_restart"}
        or label.startswith("concurrent-")
        and int(label.split("-")[1]) >= 3
        else 200,
        "input_tokens": 50,
        "output_tokens": 50,
        "total_tokens": 100,
        "hold_ms": hold_ms,
    }


def test_session_tamper_is_real_and_restore_requires_zeroed_checkpoint(tmp_path):
    req = lambda n: {"boundary": n, "task": {"budget_case": "session"}}
    for n in range(5):
        result, rc = step.execute(
            req(n), tmp_path, call_fn=fake_call, sleep=lambda _: None, hostname="s-g1"
        )
        assert rc == 0
    saved = json.loads((tmp_path / "state/state.json").read_text())
    assert saved["usage"] == 0
    assert saved["budget"]["tamper_before"] == 800
    assert saved["budget"]["tamper_after"] == 0
    result, rc = step.execute(
        req(5), tmp_path, call_fn=fake_call, sleep=lambda _: None, hostname="s-g1"
    )
    assert result is None and rc == 0
    restored, rc = step.execute(
        req(5), tmp_path, call_fn=fake_call, sleep=lambda _: None, hostname="s-g2"
    )
    assert rc == 2 and restored["done"]
    saved = json.loads((tmp_path / "state/state.json").read_text())
    assert saved["budget"]["restored_usage"] == 0
    assert saved["budget"]["calls"][-1]["label"] == "restored"


def test_daily_calls_are_exact_and_restart_wait_precedes_final_retry(tmp_path):
    delays = []
    for n in range(3):
        _result, rc = step.execute(
            {"boundary": n, "task": {"budget_case": "day"}},
            tmp_path,
            call_fn=fake_call,
            sleep=delays.append,
            hostname="s-g1",
        )
    saved = json.loads((tmp_path / "state/state.json").read_text())
    assert [c["label"] for c in saved["budget"]["calls"]] == [f"spend-{n}" for n in range(18)] + [
        "exhausted",
        "after_restart",
    ]
    assert 120 in delays and saved["usage"] == 1800 and rc == 2


def test_budget_identity_source_parity():
    own = Path(__file__).parents[1]
    for name in (
        "conformance-budget-day",
        "conformance-budget-day-retry",
        "conformance-budget-day-retry2",
        "conformance-budget-session",
    ):
        peer = own.parent / name
        for f in ("src/budget_fixture/step.py", "src/budget_fixture/agent.py", "verify_image.py"):
            assert (own / f).read_bytes() == (peer / f).read_bytes()

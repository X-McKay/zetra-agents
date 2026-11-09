"""A daily-retry identity reuses the budget fixture byte for byte with its exact limits."""

from pathlib import Path

from zetra_agents import layout

AGENT = layout.AgentDir(Path(__file__).resolve().parents[1])
ORIGINAL = layout.AgentDir(AGENT.root.parent / "conformance-budget-day")


def test_retry_identity_preserves_exact_limits_and_shared_driver():
    assert layout.check(AGENT) == []
    assert AGENT.agent_cr()["spec"] == ORIGINAL.agent_cr()["spec"]
    assert AGENT.manifest()["model"] == ORIGINAL.manifest()["model"]
    assert AGENT.agent_cr()["spec"]["capabilities"]["models"][0]["budget"] == {
        "tokensPerDay": 2000,
        "tokensPerSession": 200000,
    }
    for filename in (
        "src/budget_fixture/step.py",
        "src/budget_fixture/agent.py",
        "verify_image.py",
    ):
        assert (AGENT.root / filename).read_bytes() == (ORIGINAL.root / filename).read_bytes()
    assert AGENT.name in layout.NETWORK_ALLOWED and AGENT.name in layout.FIXTURES
    assert "conformance-budget-day-arbitrary" not in layout.NETWORK_ALLOWED

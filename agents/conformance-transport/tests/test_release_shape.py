"""The T27 fixture: no inference route, and its network exception is exactly scoped."""

from pathlib import Path

from zetra_agents import layout, release

AGENT = layout.AgentDir(Path(__file__).resolve().parents[1])


def test_deterministic_fixture_has_no_inference_access():
    assert "model" in AGENT.manifest() and AGENT.manifest()["model"] is None
    assert AGENT.agent_cr()["spec"]["capabilities"]["models"] == []
    artifacts = release.build(
        AGENT,
        image=f"registry.almckay.io/agents/{AGENT.name}@sha256:" + "a9" * 32,
        revision="0" * 40,
        mcp_resource_base="https://mcp.almckay.io",
        trust_domain="agents.internal",
    )
    assert artifacts["bundle"]["models"] == {}
    assert "inference.agents.internal" not in artifacts["bundle"]["routes"]


def test_network_exception_is_exactly_this_fixture():
    # T27 credential-free wire and foreign-CA negatives need the raw network modules.
    assert AGENT.name in layout.NETWORK_ALLOWED
    assert "conformance-transport-prod" not in layout.NETWORK_ALLOWED
    assert "investigator" not in layout.NETWORK_ALLOWED
    assert layout.image_target(AGENT) == "fixture"

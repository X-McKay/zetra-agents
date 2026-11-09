"""The T29 fixture keeps normal resources, narrow capabilities and no inference route."""

import datetime as dt
from pathlib import Path

from zetra_agents import layout, release

AGENT = layout.AgentDir(Path(__file__).resolve().parents[1])
BASE = "https://mcp.almckay.io"


def test_fixture_preserves_normal_resources_and_narrow_capabilities():
    spec = AGENT.agent_cr()["spec"]
    assert spec["runtime"] == {"cpu": "1", "memory": "1Gi", "ttlSeconds": 3600}
    assert spec["identity"] == {"mode": "agent"}
    assert spec["capabilities"]["models"] == []
    assert spec["capabilities"]["mcp"] == [
        {
            "backend": "kubernetes",
            "effect": "remote_read",
            "delegation": "inherit",
            "tools": ["pods_list_in_namespace"],
        }
    ]


def test_release_compiles_the_deployment_policy_without_inference():
    assert "model" in AGENT.manifest() and AGENT.manifest()["model"] is None
    artifacts = release.build(
        AGENT,
        image=f"registry.almckay.io/agents/{AGENT.name}@sha256:" + "a9" * 32,
        revision="0" * 40,
        mcp_resource_base=BASE,
        trust_domain="agents.internal",
        date=dt.date(2026, 11, 6),
    )
    assert artifacts["release"]["spec"]["approval"] == {"approved": False}
    assert artifacts["bundle"]["models"] == {}
    assert "inference.agents.internal" not in artifacts["bundle"]["routes"]
    assert artifacts["bundle"]["mcp"] == {
        "kubernetes": {
            "effect": "remote_read",
            "tools": ["pods_list_in_namespace"],
            "delegation": "agent",
            "resource": BASE + "/kubernetes/mcp",
        }
    }
    assert layout.image_target(AGENT) == "fixture"

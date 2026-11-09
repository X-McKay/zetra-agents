"""The T23 fixture's release compiles the one pods_list_in_namespace grant and nothing else."""

import datetime as dt
from pathlib import Path

from zetra_agents import layout, release

AGENT = layout.AgentDir(Path(__file__).resolve().parents[1])
BASE = "https://mcp.almckay.io"


def test_release_compiles_the_actual_deployment_policy():
    artifacts = release.build(
        AGENT,
        image=f"registry.almckay.io/agents/{AGENT.name}@sha256:" + "a9" * 32,
        revision="0" * 40,
        mcp_resource_base=BASE,
        trust_domain="cluster.local",
        date=dt.date(2026, 11, 6),
    )
    assert artifacts["release"]["spec"]["approval"] == {"approved": False}
    assert len(artifacts["release"]["spec"]["policySha256"]) == 64
    assert artifacts["bundle"]["mcp"] == {
        "kubernetes": {
            "effect": "remote_read",
            "tools": ["pods_list_in_namespace"],
            "delegation": "agent",
            "resource": BASE + "/kubernetes/mcp",
        }
    }
    assert layout.image_target(AGENT) == "fixture"

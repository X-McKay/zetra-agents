"""The release compiles exactly the postgres-admin/execute_sql grant, read-only."""

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
    assert all(entry["effect"] == "remote_read" for entry in artifacts["bundle"]["mcp"].values())
    assert artifacts["bundle"]["mcp"] == {
        "postgres-admin": {
            "effect": "remote_read",
            "tools": ["execute_sql"],
            "delegation": "agent",
            "resource": BASE + "/postgres-admin/mcp",
        }
    }
    assert layout.image_target(AGENT) == "runtime"

import datetime as dt
import json
import shutil
from pathlib import Path

import pytest
import yaml
from agent_platform import cli as agentctl

from zetra_agents import cli, layout, release

REPO = Path(__file__).resolve().parents[2]
IMAGE = "registry.almckay.io/agents/investigator@sha256:" + "a9" * 32
BASE = "https://mcp.almckay.io"


def test_every_agent_in_the_repository_passes_its_checks(capsys):
    assert cli.main(["--repo", str(REPO), "check"]) == 0
    assert "investigator" in capsys.readouterr().out


def test_list_is_json(capsys):
    cli.main(["--repo", str(REPO), "list"])
    assert "investigator" in json.loads(capsys.readouterr().out)


def test_release_digests_agree_with_agentctl(tmp_path, capsys):
    agent = layout.find(REPO, "investigator")
    out = tmp_path / "out"
    assert (
        cli.main(
            [
                "--repo",
                str(REPO),
                "release",
                "investigator",
                "--image",
                IMAGE,
                "--revision",
                "0" * 40,
                "--out",
                str(out),
            ]
        )
        == 0
    )
    rel = yaml.safe_load((out / "agentrelease.yaml").read_text())
    spec = rel["spec"]
    assert spec["approval"] == {"approved": False}
    assert spec["manifestSha256"] == release.file_sha256(agent.manifest_path)
    assert spec["lockSha256"] == release.file_sha256(agent.lock_path)
    assert rel["metadata"]["namespace"] == agent.agent_cr()["metadata"]["namespace"]
    predicate = json.loads((out / "predicate.json").read_text())
    assert predicate["policySha256"] == spec["policySha256"]
    capsys.readouterr()
    agentctl.main(
        [
            "policy-digest",
            "--agent",
            str(out / "agent.yaml"),
            "--release",
            str(out / "agentrelease.yaml"),
            "--mcp-resource-base",
            BASE,
        ]
    )
    assert capsys.readouterr().out.strip() == spec["policySha256"]


def test_approval_does_not_change_the_policy_digest():
    agent = layout.find(REPO, "investigator")
    a = release.build(
        agent,
        image=IMAGE,
        revision="abc",
        mcp_resource_base=BASE,
        trust_domain="cluster.local",
        date=dt.date(2026, 10, 30),
    )
    approved = {**a["release"], "spec": {**a["release"]["spec"], "approval": {"approved": True}}}
    from agent_platform.bundle import compile_bundle, digest_hex

    bundle = compile_bundle(
        a["agent"], approved, mcp_resource_base=BASE, trust_domain="cluster.local"
    )
    assert digest_hex(bundle) == a["release"]["spec"]["policySha256"]
    assert a["name"] == "investigator-2026-10-30-a9a9a9a9"


@pytest.mark.parametrize("image", ["registry.almckay.io/agents/investigator:latest", "x@sha256:ab"])
def test_release_requires_a_digest_pinned_image(image):
    with pytest.raises(ValueError):
        release.release_name("investigator", image, dt.date(2026, 10, 30))


def test_check_rejects_network_imports_and_mismatches(tmp_path):
    shutil.copytree(
        REPO / "agents" / "investigator",
        tmp_path / "agents" / "investigator",
        ignore=shutil.ignore_patterns(".venv"),
    )
    root = tmp_path / "agents" / "investigator"
    (root / "src" / "investigator" / "leak.py").write_text(
        "import httpx\nfrom socket import socket\n"
    )
    manifest = yaml.safe_load((root / "agent.yaml").read_text())
    manifest["model"]["name"] = "some-other-model"
    (root / "agent.yaml").write_text(yaml.safe_dump(manifest))
    problems = layout.check(layout.AgentDir(root))
    assert any("imports httpx" in p for p in problems)
    assert any("imports socket" in p for p in problems)
    assert any("model is not granted" in p for p in problems)


@pytest.mark.parametrize("agent", layout.all_agents(REPO), ids=lambda a: a.name)
def test_every_agent_release_compiles_the_actual_deployment_policy(agent):
    artifacts = release.build(
        agent,
        image=f"registry.almckay.io/agents/{agent.name}@sha256:" + "a9" * 32,
        revision="0" * 40,
        mcp_resource_base=BASE,
        trust_domain="cluster.local",
        date=dt.date(2026, 11, 6),
    )
    assert artifacts["release"]["spec"]["approval"] == {"approved": False}
    assert len(artifacts["release"]["spec"]["policySha256"]) == 64
    assert all(entry["effect"] == "remote_read" for entry in artifacts["bundle"]["mcp"].values())
    if agent.name in {"conformance-checkpoint", "conformance-performance"}:
        assert artifacts["bundle"]["mcp"] == {
            "kubernetes": {
                "effect": "remote_read",
                "tools": ["pods_list_in_namespace"],
                "delegation": "agent",
                "resource": BASE + "/kubernetes/mcp",
            }
        }


@pytest.mark.parametrize(
    "identity", ["conformance-budget-day-retry", "conformance-budget-day-retry2"]
)
def test_daily_retry_fixture_preserves_exact_limits_and_shared_driver(identity):
    original = layout.find(REPO, "conformance-budget-day")
    retry = layout.find(REPO, identity)
    assert not layout.check(retry)
    assert retry.agent_cr()["spec"] == original.agent_cr()["spec"]
    assert retry.manifest()["model"] == original.manifest()["model"]
    assert retry.agent_cr()["spec"]["capabilities"]["models"][0]["budget"] == {
        "tokensPerDay": 2000,
        "tokensPerSession": 200000,
    }
    for filename in (
        "src/budget_fixture/step.py",
        "src/budget_fixture/agent.py",
        "verify_image.py",
    ):
        assert (retry.root / filename).read_bytes() == (original.root / filename).read_bytes()
    assert identity in layout.NETWORK_ALLOWED
    assert "conformance-budget-day-arbitrary" not in layout.NETWORK_ALLOWED


def test_transport_network_exception_is_exactly_scoped():
    assert "conformance-transport" in layout.NETWORK_ALLOWED
    assert "conformance-transport-prod" not in layout.NETWORK_ALLOWED
    assert "investigator" not in layout.NETWORK_ALLOWED


def test_performance_fixture_preserves_normal_resources_and_narrow_capabilities():
    agent = layout.find(REPO, "conformance-performance")
    spec = agent.agent_cr()["spec"]
    assert spec["runtime"] == {"cpu": "1", "memory": "1Gi", "ttlSeconds": 3600}
    assert spec["identity"] == {"mode": "agent"}
    assert spec["capabilities"]["models"][0]["budget"] == {"tokensPerDay": 1, "tokensPerSession": 1}
    assert spec["capabilities"]["mcp"] == [
        {
            "backend": "kubernetes",
            "effect": "remote_read",
            "delegation": "inherit",
            "tools": ["pods_list_in_namespace"],
        }
    ]

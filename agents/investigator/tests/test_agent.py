import json
import shutil
import types
from pathlib import Path

import pytest
import yaml
from agent_runtime import step

ROOT = Path(__file__).resolve().parents[1]


class FakeMcp:
    def __init__(self, text="configmap demo-config not found"):
        self.calls = []
        self.text = text

    async def __call__(self, backend, tool, arguments):
        self.calls.append((backend, tool, arguments))
        text = self.text() if callable(self.text) else self.text
        return {"tool": tool, "backend": backend, "text": text}


def tools(tmp_path, mcp):
    from investigator.agent import create_agent

    ctx = types.SimpleNamespace(workspace=tmp_path, instructions="", mcp=mcp)
    return {t.fn.__name__: t.fn for t in create_agent(ctx)["tools"]}


@pytest.fixture
def app(tmp_path, monkeypatch):
    """The image's /app as the Dockerfile lays it out."""
    app = tmp_path / "app"
    app.mkdir()
    shutil.copy(ROOT / "agent.yaml", app / "agent.yaml")
    shutil.copytree(ROOT / "src" / "investigator", app / "investigator")
    monkeypatch.setenv("AGENT_APP_DIR", str(app))
    monkeypatch.setenv("AGENT_SANDBOX_DIR", str(tmp_path / "sandbox"))
    return app


def test_image_tools_match_the_manifest(app):
    instructions, built = step.build_agent(step.load_manifest())
    assert "zetra-poc-fixtures" in instructions
    assert set(built) == {"list_pods", "get_pod", "list_events", "write_report"}
    report = step.schema(built["write_report"])["function"]["parameters"]
    assert report["required"] == ["content"]


def test_manifest_model_and_tools_are_within_the_agent_capabilities():
    manifest = yaml.safe_load((ROOT / "agent.yaml").read_text())
    agent = yaml.safe_load((ROOT / "deploy" / "agent.yaml").read_text())
    models = {m["backend"]: m["models"] for m in agent["spec"]["capabilities"]["models"]}
    assert manifest["model"]["name"] in models[manifest["model"]["backend"]]
    assert manifest["name"] == agent["metadata"]["name"]


async def test_mcp_tools_stay_inside_the_reviewed_scope(tmp_path):
    mcp = FakeMcp()
    fns = tools(tmp_path, mcp)
    await fns["list_pods"]()
    await fns["get_pod"]()
    await fns["list_events"]()
    agent = yaml.safe_load((ROOT / "deploy" / "agent.yaml").read_text())
    allowed = set(agent["spec"]["capabilities"]["mcp"][0]["tools"])
    assert {backend for backend, _, _ in mcp.calls} == {"kubernetes"}
    assert {tool for _, tool, _ in mcp.calls} == allowed
    assert all(args["namespace"] == "zetra-poc-fixtures" for _, _, args in mcp.calls)


async def test_observation_is_saved_with_evidence_identity(tmp_path):
    result = await tools(tmp_path, FakeMcp())["get_pod"]("investigator-demo-broken")
    saved = json.loads((tmp_path / result["evidence"]).read_text())
    assert saved["tool"] == "pods_get"
    assert saved["namespace"] == "zetra-poc-fixtures"
    assert result["evidence"].startswith("evidence/pod-investigator-demo-broken-")
    assert "demo-config not found" in result["text"]


async def test_out_of_scope_pod_never_reaches_the_gateway(tmp_path):
    mcp = FakeMcp()
    result = await tools(tmp_path, mcp)["get_pod"]("authentik-server")
    assert "error" in result
    assert mcp.calls == []
    assert not (tmp_path / "evidence").exists()


async def test_oversized_observation_is_an_error(tmp_path):
    with pytest.raises(ValueError):
        await tools(tmp_path, FakeMcp("x" * 16_001))["list_pods"]()
    assert not (tmp_path / "evidence").exists()


async def test_changed_observation_preserves_prior_citation(tmp_path):
    count = iter(range(1, 10))
    fns = tools(tmp_path, FakeMcp(lambda: str(next(count))))
    first = await fns["list_pods"]()
    second = await fns["list_pods"]()
    assert first["evidence"] != second["evidence"]
    assert json.loads((tmp_path / first["evidence"]).read_text())["text"] == "1"
    assert json.loads((tmp_path / second["evidence"]).read_text())["text"] == "2"


async def test_report_appends_exact_links(tmp_path):
    fns = tools(tmp_path, FakeMcp())
    observation = await fns["list_pods"]()
    assert await fns["write_report"]("ConfigMap missing.") == {"path": "report.md"}
    report = (tmp_path / "report.md").read_text()
    assert report.startswith("ConfigMap missing.")
    assert f"]({observation['evidence']})" in report


@pytest.mark.parametrize("content", ["See evidence/pods-...json", "word " * 151, "x" * 8001, "   "])
async def test_report_rejects_bad_narratives(tmp_path, content):
    fns = tools(tmp_path, FakeMcp())
    await fns["list_pods"]()
    assert "error" in await fns["write_report"](content)
    assert not (tmp_path / "report.md").exists()


async def test_report_requires_evidence(tmp_path):
    assert "error" in await tools(tmp_path, FakeMcp())["write_report"]("Unobserved")

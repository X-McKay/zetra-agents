import json
from importlib.resources import files
from pathlib import Path

import pytest
import yaml
from google.adk.agents import LlmAgent
from zetra import AgentContext
from zetra._runtime.definition import Definition
from zetra.manifest import load_agent

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

    ctx = AgentContext(None, workspace=tmp_path, model="fixture", mcp_binding=mcp)
    ctx.seal(create_agent(ctx))
    executors = ctx.executors()

    def wrap(name, execute):
        async def call(*args, **kwargs):
            if args:
                kwargs["name" if name == "get_pod" else "content"] = args[0]
            return await execute(kwargs, {}, "test")

        return call

    return {name: wrap(name, execute) for name, execute in executors.items()}


def test_image_tools_match_the_manifest(tmp_path):
    spec = load_agent(ROOT)
    definition = Definition(
        spec.model_dump(),
        tmp_path,
        required_tools={
            "list_pods": "remote_read",
            "get_pod": "remote_read",
            "list_events": "remote_read",
            "write_report": "workspace_write",
        },
    )
    assert "zetra-poc-fixtures" in definition.instruction
    ctx = definition.context(None)
    assert isinstance(ctx.seal(definition.factory(ctx)), LlmAgent)
    assert files("investigator").joinpath("agent.yaml").is_file()


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


@pytest.mark.parametrize("tool", ["list_pods", "get_pod", "list_events"])
async def test_oversized_observation_is_an_error(tmp_path, tool):
    with pytest.raises(ValueError):
        await tools(tmp_path, FakeMcp("x" * 16_001))[tool]()
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


@pytest.mark.parametrize("tool", ["list_pods", "get_pod", "list_events"])
async def test_failed_read_does_not_publish_evidence_and_later_read_works(tmp_path, tool):
    attempts = 0

    async def flaky(backend, name, args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transport unavailable")
        return {"text": "Synthetic observation"}

    fns = tools(tmp_path, flaky)
    with pytest.raises(RuntimeError, match="unavailable"):
        await fns[tool]()
    assert attempts == 1 and not (tmp_path / "evidence").exists()
    result = await fns[tool]()
    assert attempts == 2 and (tmp_path / result["evidence"]).is_file()


async def test_report_rejection_preserves_prior_report_then_accepts_valid_input(tmp_path):
    fns = tools(tmp_path, FakeMcp())
    await fns["list_pods"]()
    await fns["write_report"]("Observed missing ConfigMap.")
    before = (tmp_path / "report.md").read_bytes()
    assert "error" in await fns["write_report"]("See evidence/invented.json")
    assert (tmp_path / "report.md").read_bytes() == before
    await fns["write_report"]("Updated observation.")
    assert (tmp_path / "report.md").read_text().startswith("Updated observation.")

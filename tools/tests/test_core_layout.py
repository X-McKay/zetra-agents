"""Static admission must neither import factories nor infer a legacy fallback."""

import datetime as dt
import json

import pytest
import yaml

from zetra_agents import layout, release


@pytest.fixture
def core(tmp_path):
    root = tmp_path / "agents" / "sample"
    package = root / "src" / "sample"
    package.mkdir(parents=True)
    (root / "deploy").mkdir()
    (root / "tests").mkdir()
    (root / "evals" / "sample").mkdir(parents=True)
    (package / "__init__.py").write_text('raise RuntimeError("static imported agent")\n')
    (package / "prompt.md").write_text("Answer from approved documents.")
    (package / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "sample",
                "owner": "test",
                "entrypoint": "sample.factory:create_agent",
                "instructions": "sample:prompt.md",
            }
        )
    )
    (root / "pyproject.toml").write_text('[tool.zetra.agents]\nsample="src/sample/agent.yaml"\n')
    (root / "uv.lock").write_text("version = 1\n")
    (root / "Dockerfile").write_text("FROM scratch\n")
    (root / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "name": "sample",
                "runtime_profile": "zetra-core-v1",
                "definition": "sample:agent.yaml",
                "model": {"backend": "llm-main", "name": "model"},
                "tools": [{"name": "read_document", "effect": "workspace_read"}],
            }
        )
    )
    (root / "deploy" / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "kind": "Agent",
                "metadata": {"name": "sample", "namespace": "tenant-test"},
                "spec": {
                    "identity": {"mode": "agent"},
                    "capabilities": {"models": [{"backend": "llm-main", "models": ["model"]}]},
                },
            }
        )
    )
    (root / "tests" / "test_contract.py").write_text("def test_contract(): pass\n")
    case = {
        "schema_version": 2,
        "id": "fixture",
        "input": "Read guide",
        "assertions": [
            {"type": "text_contains", "value": "Completed."},
            {"type": "tool_called", "tool": "read_document"},
            {"type": "max_steps", "maximum": 3},
        ],
    }
    (root / "evals" / "sample" / "cases.jsonl").write_text(json.dumps(case) + "\n")
    requirements = [
        {"id": k, "component": "agent", "kind": k, "cases": ["fixture"]}
        for k in ["outcome", "trajectory", "performance"]
    ]
    requirements += [
        {
            "id": k,
            "component": "tool:read_document",
            "kind": k,
            "tests": ["tests/test_contract.py::test_contract"],
        }
        for k in ["contract", "security", "recovery"]
    ]
    (root / "evals" / "sample" / "quality.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "agent": "sample",
                "tools": {"read_document": "workspace_read"},
                "skills": {},
                "live_model_required": False,
                "requirements": requirements,
            }
        )
    )
    return layout.AgentDir(root)


def artifacts(agent):
    return release.build(
        agent,
        image="registry.example/agent@sha256:" + "ab" * 32,
        revision="0" * 40,
        mcp_resource_base="https://mcp.example",
        trust_domain="cluster.local",
        date=dt.date(2026, 10, 31),
    )


def test_core_static_checks_do_not_import_factory(core):
    assert layout.check(core) == []
    result = artifacts(core)
    assert result["release"]["spec"]["runtimeProfile"] == "zetra-core-v1"
    assert result["bundle"]["runtime"]["execution_profile"] == "zetra-core-v1"
    assert result["release"]["spec"]["approval"] == {"approved": False}


@pytest.mark.parametrize(
    "change",
    [
        "missing-definition",
        "different-index",
        "definition-name",
        "missing-prompt",
        "tool-drift",
        "profile",
        "version",
        "unknown-field",
        "missing-quality",
        "duplicate-key",
        "symlink",
    ],
)
def test_malformed_core_cannot_pass_or_build_release(core, change):
    root = core.root
    manifest = core.manifest()
    if change == "missing-definition":
        manifest["definition"] = "sample:missing.yaml"
    elif change == "different-index":
        (root / "src/sample/other.yaml").write_bytes((root / "src/sample/agent.yaml").read_bytes())
        manifest["definition"] = "sample:other.yaml"
    elif change == "definition-name":
        p = root / "src/sample/agent.yaml"
        p.write_text(p.read_text().replace("name: sample", "name: different"))
    elif change == "missing-prompt":
        (root / "src/sample/prompt.md").unlink()
    elif change == "tool-drift":
        manifest["tools"][0]["name"] = "undeclared"
    elif change == "profile":
        manifest["runtime_profile"] = "future-core"
    elif change == "version":
        manifest["schema_version"] = 3
    elif change == "unknown-field":
        manifest["entrypoint"] = "sample:legacy"
    elif change == "missing-quality":
        (root / "evals/sample/quality.json").unlink()
    elif change == "symlink":
        p = root / "src/sample/agent.yaml"
        target = root / "outside.yaml"
        p.rename(target)
        p.symlink_to(target)
    core.manifest_path.write_text(yaml.safe_dump(manifest))
    if change == "duplicate-key":
        with core.manifest_path.open("a") as f:
            f.write("runtime_profile: zetra-core-v1\n")
    assert layout.check(core)
    with pytest.raises(ValueError):
        artifacts(core)


@pytest.mark.parametrize(
    "change", ["downgrade", "missing-entrypoint", "missing-instructions", "mixed-definition"]
)
def test_legacy_shape_cannot_bypass_core_admission(core, change):
    manifest = core.manifest()
    manifest["schema_version"] = 1
    manifest.pop("runtime_profile")
    if change != "downgrade":
        manifest.pop("definition")
        manifest.update(entrypoint="sample.factory:create_agent", instructions="sample/prompt.md")
        if change == "missing-entrypoint":
            manifest.pop("entrypoint")
        elif change == "missing-instructions":
            manifest.pop("instructions")
        else:
            manifest["definition"] = "sample:missing.yaml"
    core.manifest_path.write_text(yaml.safe_dump(manifest))
    assert layout.check(core)
    with pytest.raises(ValueError):
        artifacts(core)

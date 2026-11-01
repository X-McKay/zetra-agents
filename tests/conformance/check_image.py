"""Run inside a built image, without external network or checkout imports.

Compare an offline local run to fresh-process platform commands over a TLS gateway
fixture. This checks installed packages and transport parity, not cluster admission.
"""

import asyncio
import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
from importlib.resources import files
from pathlib import Path

from agent_runtime.core_protocol import (
    CoreBinding,
    CoreManifest,
    decode_frame,
    encode_frame,
    yaml_mapping,
)
from gateway_fixture import Gateway, make_ca, projected_token
from zetra._runtime.artifacts import FileStore, Tape
from zetra.local import local_run
from zetra.manifest import load_agent, resource_parts


def verify(project, scratch):
    raw = Path("/app/agent.yaml").read_bytes()
    envelope = CoreManifest.model_validate(yaml_mapping(raw))
    assert raw == (project / "agent.yaml").read_bytes()
    spec = load_agent(project)
    package, _ = resource_parts(envelope.definition)
    installed = Path(importlib.import_module(package).__file__).parent
    assert "site-packages" in str(installed), installed
    for source in (project / "src" / package).rglob("*"):
        if source.is_file() and "__pycache__" not in source.parts:
            assert (
                source.read_bytes()
                == (
                    installed / source.relative_to(project / "src" / package)
                ).read_bytes()
            )
    assert (
        files(package).joinpath("agent.yaml").read_bytes()
        == (project / "src" / package / "agent.yaml").read_bytes()
    )
    fixture_path = project / "evals" / spec.name / "mcp.json"
    fixtures = json.loads(fixture_path.read_text()) if fixture_path.exists() else None
    task = "Inspect the approved synthetic evidence and produce a cited result."
    local = asyncio.run(local_run(project, task, mcp_fixtures=fixtures))
    assert local["status"] == "SUCCEEDED", local
    tools = [item for item in local["trajectory"] if item["kind"] == "tool"]
    ca, cert, key = make_ca(scratch)
    gateway = Gateway(cert, key, tools, fixtures)
    token = scratch / "token"
    token.write_text(projected_token())
    sandbox = scratch / "sandbox"
    binding = CoreBinding.model_validate(
        {
            "profile": "zetra-core-v1",
            "tenant": "tenant-test",
            "agent": spec.name,
            "release": spec.name + "-test",
            "image": "example/agent@sha256:" + "a" * 64,
            "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "policy_sha256": "b" * 64,
            "namespace": "default",
            "workflow_id": f"session:tenant-test:{spec.name}:12345678-1234-1234-1234-123456789abc",
            "run_id": "23456789-1234-1234-1234-123456789abc",
            "session_id": "12345678-1234-1234-1234-123456789abc",
            "generation": 1,
            "task_sha256": hashlib.sha256(task.encode()).hexdigest(),
        }
    )
    env = {
        **os.environ,
        "AGENT_CORE_BINDING": binding.model_dump_json(),
        "AGENT_GATEWAY_URL": gateway.url,
        "AGENT_GATEWAY_CA": str(ca),
        "AGENT_TOKEN_HOST": "token.agents.internal",
        "AGENT_INFERENCE_HOST": "inference.agents.internal",
        "AGENT_MCP_HOST": "mcp.agents.internal",
        "AGENT_CLIENT_ID": f"agent-tenant-test-{spec.name}",
        "AGENT_TOKEN_PATH": str(token),
        "AGENT_TOKEN_ENDPOINT_PATH": "/v1/token",
        "AGENT_MODEL_ROUTE": "/models/llm-main",
        "AGENT_TOKENS_PER_SESSION": "200000",
        "AGENT_SANDBOX_DIR": str(sandbox),
        "AGENT_APP_DIR": "/app",
    }
    env.pop("PYTHONPATH", None)

    def child(action, position, operation=None):
        command = {
            "schema_version": 1,
            "binding": binding.model_dump(),
            "task": task,
            "action": action,
            "position": position,
            "operation": operation,
        }
        result = subprocess.run(
            [sys.executable, "-m", "agent_runtime.core_step"],
            input=encode_frame(command),
            capture_output=True,
            timeout=40,
            env=env,
            cwd=scratch,
            check=False,
        )
        reply = decode_frame(result.stdout)
        assert result.returncode in (0, 2), (
            result.returncode,
            reply,
            action,
            operation,
            gateway.mcp_calls,
        )
        return reply

    position = None
    observed = []
    try:
        for _ in range(64):
            prepared = child("prepare", position)
            if prepared["status"] == "done":
                assert prepared["text"] == local["result"]["final_text"]
                break
            assert prepared["status"] == "operation"
            operation = prepared["operation"]
            candidate = child("execute", prepared["position"], operation)
            assert candidate["status"] == "candidate"
            tape = Tape(
                FileStore(sandbox / "state/core/objects"),
                manifest=binding.manifest,
            )
            receipt = tape.validate_receipt(
                prepared["position"], operation, candidate["receipt"]
            )
            position = receipt.position.model_dump()
            if operation["kind"] == "tool":
                observed.append(operation["executor"])
        else:
            raise AssertionError("no completion within bound")
        actual = {
            p.relative_to(sandbox / "workspace").as_posix(): p.read_text()
            for p in (sandbox / "workspace").rglob("*")
            if p.is_file()
        }
        assert actual == local["file_contents"]
        assert observed == [item["executor"] for item in tools]
        assert len(gateway.chat_requests) == len(tools) + 1
        assert len(gateway.mcp_calls) == (len(fixtures["calls"]) if fixtures else 0)
        assert {
            item["function"]["name"] for item in gateway.chat_requests[0]["tools"]
        } == set(envelope.inventory)
        print(
            json.dumps(
                {
                    "agent": spec.name,
                    "status": "PASSED",
                    "installed": str(installed),
                    "steps": position["cursor"],
                    "mcp_calls": len(gateway.mcp_calls),
                    "scope": "installed image/local/core TLS fixture parity",
                }
            )
        )
    finally:
        gateway.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zetra-parity-") as directory:
        verify(Path(sys.argv[1]).resolve(), Path(directory))

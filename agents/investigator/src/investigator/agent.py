"""Static read-only tools (spec 11.7). The only route out is ctx.mcp, through the gateway."""

import hashlib
import json
import re

from agent_runtime.tools import Tool

BACKEND = "kubernetes"
NAMESPACE = "zetra-poc-fixtures"
MAX_OBSERVATION = 16_000
POD_NAME = re.compile(r"investigator-demo-[a-z0-9-]{1,40}")


def create_agent(ctx) -> dict:
    evidence_dir = ctx.workspace / "evidence"

    async def observe(tool: str, arguments: dict, evidence: str) -> dict:
        result = await ctx.mcp(BACKEND, tool, {"namespace": NAMESPACE, **arguments})
        if len(result["text"].encode()) > MAX_OBSERVATION:
            raise ValueError("MCP observation exceeded the bounded result size")
        observation = {"tool": tool, "namespace": NAMESPACE, "text": result["text"]}
        encoded = json.dumps(observation, sort_keys=True, indent=2).encode()
        filename = f"{evidence}-{hashlib.sha256(encoded).hexdigest()}.json"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / filename).write_bytes(encoded)
        return {**observation, "evidence": "evidence/" + filename}

    async def list_pods() -> dict:
        """List only the synthetic investigator demonstration pods."""
        return await observe(
            "pods_list_in_namespace", {"labelSelector": "app=investigator-demo"}, "pods"
        )

    async def get_pod(name: str = "investigator-demo-broken") -> dict:
        """Inspect a demonstration pod; name must start with investigator-demo-."""
        if not POD_NAME.fullmatch(name):
            return {"error": "Choose an investigator-demo- pod from list_pods."}
        return await observe("pods_get", {"name": name}, "pod-" + name)

    async def list_events() -> dict:
        """Read namespace events to explain observed pod startup failures."""
        return await observe("events_list", {}, "events")

    async def write_report(content: str) -> dict:
        """Write narrative under 150 words; exact evidence links are appended automatically."""
        if "evidence/" in content:
            return {"error": "Omit evidence paths from the narrative; exact links are appended."}
        if not content.strip() or len(content.split()) > 150:
            return {"error": "Write a nonempty narrative of at most 150 words."}
        evidence = sorted(evidence_dir.glob("*.json"))
        if not evidence:
            return {"error": "Gather MCP evidence before writing the report."}
        links = [path.relative_to(ctx.workspace).as_posix() for path in evidence]
        report = (
            content.rstrip()
            + "\n\n## Evidence\n\n"
            + "\n".join(f"- [{path}]({path})" for path in links)
            + "\n"
        )
        if len(report.encode()) > 8_000:
            return {"error": "Keep the report below 8000 UTF-8 bytes."}
        (ctx.workspace / "report.md").write_text(report, encoding="utf-8")
        return {"path": "report.md"}

    return {
        "tools": [
            Tool(list_pods, "remote_read"),
            Tool(get_pod, "remote_read"),
            Tool(list_events, "remote_read"),
            Tool(write_report, "workspace_write"),
        ]
    }

"""Conventional manifest factory; the fixture image executes its explicit step override."""

from agent_runtime.tools import Tool


def create_agent(ctx):
    from agent_runtime import step

    if getattr(step, "PROTOCOL_FIXTURE_OVERRIDE", None) != "conformance-protocol-v1":
        raise RuntimeError("protocol fixture requires the installed step override")

    async def protocol_fixture():
        """Fail visibly if the fixture image accidentally executes the normal SDK step."""
        raise RuntimeError("protocol fixture requires the installed step override")

    return {"tools": [Tool(protocol_fixture, "workspace_read")]}

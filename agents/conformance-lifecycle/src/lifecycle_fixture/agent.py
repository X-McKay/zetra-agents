"""Conventional manifest factory; the fixture image executes its explicit step override."""

from agent_runtime.tools import Tool


def create_agent(ctx):
    from agent_runtime import step

    if getattr(step, "LIFECYCLE_FIXTURE_OVERRIDE", None) != "conformance-lifecycle-v1":
        raise RuntimeError("lifecycle fixture requires the installed step override")

    async def lifecycle_fixture():
        """Fail visibly if the fixture image accidentally executes the normal SDK step."""
        raise RuntimeError("lifecycle fixture requires the installed step override")

    return {"tools": [Tool(lifecycle_fixture, "workspace_read")]}

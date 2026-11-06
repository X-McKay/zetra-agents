from agent_runtime.tools import Tool


def create_agent(ctx):
    from agent_runtime import step

    if getattr(step, "TRANSPORT_FIXTURE_OVERRIDE", None) != "conformance-transport-v1":
        raise RuntimeError("transport fixture requires the installed step override")

    async def transport_probe():
        """Record bounded credential-free transport observations."""
        from transport_fixture.probe import run

        return run()

    return {"tools": [Tool(transport_probe, "workspace_write")]}

from agent_runtime.tools import Tool


def create_agent(ctx):
    from agent_runtime import step

    if getattr(step, "PERFORMANCE_FIXTURE_OVERRIDE", None) != "conformance-performance-v1":
        raise RuntimeError("performance fixture requires the installed step override")

    async def performance_read():
        """One real allowed read through the ordinary SDK MCP session."""
        await ctx.mcp("kubernetes", "pods_list_in_namespace", {"namespace": "tenant-test"})
        return {"completed": True}

    return {"tools": [Tool(performance_read, "remote_read")]}

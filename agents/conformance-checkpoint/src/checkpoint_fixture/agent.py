from agent_runtime.tools import Tool


def create_agent(ctx):
    from agent_runtime import step

    if getattr(step, "CHECKPOINT_FIXTURE_OVERRIDE", None) != "conformance-checkpoint-v1":
        raise RuntimeError("checkpoint fixture requires the installed step override")

    async def checkpoint_read():
        """Perform one allowed Kubernetes MCP read through the ordinary SDK."""
        await ctx.mcp("kubernetes", "pods_list_in_namespace", {"namespace": "tenant-test"})
        return {"completed": True}

    return {"tools": [Tool(checkpoint_read, "remote_read")]}

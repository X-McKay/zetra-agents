from agent_runtime.tools import Tool


def create_agent(ctx):
    from agent_runtime import step

    if getattr(step, "BUDGET_FIXTURE_OVERRIDE", None) != "budget-conformance-v1":
        raise RuntimeError("budget fixture requires the installed step override")

    async def budget_fixture():
        """Execute only through the signed deterministic boundary driver."""
        raise RuntimeError("budget fixture requires the installed step override")

    return {"tools": [Tool(budget_fixture, "workspace_write")]}

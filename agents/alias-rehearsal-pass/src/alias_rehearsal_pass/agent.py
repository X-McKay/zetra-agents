"""One tool that writes the word the model chose into the workspace report."""

import pathlib
import re

from agent_runtime.tools import Tool

REPORT = "report.md"
WORD = re.compile(r"[A-Za-z]{1,32}")


def create_agent(ctx) -> dict:
    workspace = pathlib.Path(ctx.workspace)

    async def answer(word: str) -> dict:
        """Record the single word the task asks for."""
        if not isinstance(word, str) or not WORD.fullmatch(word.strip()):
            return {"error": "Give one short word made of letters."}
        path = workspace / REPORT
        if path.is_symlink():  # a restored workspace may hold one; never write through it
            path.unlink()
        path.write_text(f"word: {word.strip()}\n", encoding="utf-8")
        return {"path": REPORT}

    return {"tools": [Tool(answer, "workspace_write")]}

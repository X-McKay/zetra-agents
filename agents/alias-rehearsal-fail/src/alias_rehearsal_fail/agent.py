"""One tool that writes the model's word and the model name the gateway answers with.

The suite expects the served name of the release `fast` pointed at when the rehearsal
began, so this agent fails after the alias moves. That is its purpose.
"""

import pathlib
import re

from agent_runtime import models
from agent_runtime.tools import Tool

REPORT = "report.md"
WORD = re.compile(r"[A-Za-z]{1,32}")
MODEL = "fast"  # agent.yaml's model.name; ctx does not carry it, a test holds them equal


def create_agent(ctx) -> dict:
    workspace = pathlib.Path(ctx.workspace)

    async def answer(word: str) -> dict:
        """Record the single word the task asks for."""
        if not isinstance(word, str) or not WORD.fullmatch(word.strip()):
            return {"error": "Give one short word made of letters."}
        try:
            reply = models.chat_client().chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": "Say ok."}],
                max_tokens=1,
                temperature=0,
            )
            served = f"model: {reply.model}"
        except Exception as exc:  # noqa: BLE001 - recorded in the report, whose suite then fails
            served = f"model: unavailable ({type(exc).__name__})"
        path = workspace / REPORT
        if path.is_symlink():  # a restored workspace may hold one; never write through it
            path.unlink()
        path.write_text(f"word: {word.strip()}\n{served}\n", encoding="utf-8")
        return {"path": REPORT}

    return {"tools": [Tool(answer, "workspace_write")]}

"""Ordinary Python tools; only approved packaged content can enter answer.md."""

from importlib.resources import files

from google.adk.agents import LlmAgent
from zetra import AgentContext, Tool

DEFAULT_QUOTE = "Release only after tests and evaluations pass and a reviewer approves the change."


def source(document_id):
    if document_id != "guide":
        return None
    return files("documentassistant").joinpath("documents/guide.md").read_text(encoding="utf-8")


def abstain():
    return {"status": "ABSTAINED", "reason": "The approved guide does not support that request."}


def create_agent(ctx: AgentContext) -> LlmAgent:
    async def read_document(document_id: str = "guide") -> dict:
        """Read the approved guide and its grounding guidance; unknown IDs abstain."""
        text = source(document_id)
        if text is None:
            return abstain()
        instruction = (
            files("documentassistant")
            .joinpath("skills/grounded_answer.md")
            .read_text(encoding="utf-8")
        )
        return {
            "document_id": document_id,
            "text": text,
            "skill": {"name": "grounded_answer", "instruction": instruction},
        }

    async def write_answer(quote: str = DEFAULT_QUOTE, document_id: str = "guide") -> dict:
        """Read the guide first, then write an exact excerpt; otherwise refuse the write."""
        text = source(document_id)
        if text is None or not quote.strip() or len(quote.encode()) > 4000 or quote not in text:
            return abstain()
        grounded = any(
            read["result"].get("document_id") == document_id
            and read["result"].get("text") == text
            and read["result"].get("skill", {}).get("name") == "grounded_answer"
            and read["result"].get("skill", {}).get("instruction")
            for read in ctx.prior_tool_results("read_document")
        )
        if not grounded:
            return {
                "status": "READ_REQUIRED",
                "reason": "Call read_document for the approved guide and its skill before writing.",
            }
        (ctx.workspace / "answer.md").write_text(
            f"> {quote}\n\nSource: {document_id}\n", encoding="utf-8"
        )
        return {"path": "answer.md", "document_id": document_id}

    return LlmAgent(
        name="documentassistant",
        model=ctx.model,
        instruction=ctx.instruction,
        tools=ctx.tools(
            Tool(read_document, "workspace_read"), Tool(write_answer, "workspace_write")
        ),
    )

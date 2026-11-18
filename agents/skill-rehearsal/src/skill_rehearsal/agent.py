"""A session that is the same every time: write a report, check it with a skill's script,
then put what the script said into the report. There is no model; `decide` picks each step.

The script is run by the platform's launcher (`skill_run`), never by this code.
"""

import json
import pathlib

from agent_runtime.tools import Done, Tool, ToolCall

REPORT = "report.md"
HEADING = "## Result"
SKILL = "report-check"
SCRIPT = "scripts/check_report.py"


def passed(result) -> bool:
    """Whether a `skill_run` result says the script ran to its end and found the report in
    order. A refusal, a limit, a non-zero exit or output that is not the script's is a no."""
    if not isinstance(result, dict) or result.get("exit_status") != 0 or result.get("limits_hit"):
        return False
    try:
        said = json.loads(result.get("stdout") or "")
    except ValueError:
        return False
    return isinstance(said, dict) and said.get("ok") is True


def decide(task, results):
    done = {r.name: r.result for r in results}
    if "write_note" not in done:
        return ToolCall("write_note")
    if "skill_run" not in done:
        return ToolCall("skill_run", {"skill": SKILL, "script": SCRIPT, "arguments": [HEADING]})
    if "record_check" not in done:
        return ToolCall("record_check", {"passed": passed(done["skill_run"])})
    return Done("Report checked." if passed(done["skill_run"]) else "The report check failed.")


def create_agent(ctx) -> dict:
    workspace = pathlib.Path(ctx.workspace)

    def write(check: str | None) -> dict:
        path = workspace / REPORT
        if path.is_symlink():  # a restored workspace may hold one; never write through it
            path.unlink()
        text = f"# Skill rehearsal\n\n{HEADING}\n\nThe report was written.\n"
        if check is not None:
            text += f"check: {check}\n"
        path.write_text(text, encoding="utf-8")
        return {"path": REPORT}

    async def write_note() -> dict:
        """Write the report the skill's script will check."""
        return write(None)

    async def record_check(passed: bool) -> dict:
        """Write the report again with the outcome of the check."""
        if type(passed) is not bool:
            return {"error": "passed must be true or false"}
        return write("passed" if passed else "failed")

    return {
        "tools": [Tool(write_note, "workspace_write"), Tool(record_check, "workspace_write")],
        "decide": decide,
    }

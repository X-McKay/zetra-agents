import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from agent_runtime.tools import Done, ToolCall, ToolResult

from skill_rehearsal import agent

ROOT = Path(__file__).resolve().parents[1]
SUITE = yaml.safe_load((ROOT / "evaluation/suite.yaml").read_text())
EXPECT = SUITE["cases"][0]["expect"]
RUN = {"skill": "report-check", "script": "scripts/check_report.py", "arguments": ["## Result"]}


def ran(exit_status=0, stdout='{"ok": true}', limits_hit=()):
    return {
        "exit_status": exit_status,
        "limits_hit": list(limits_hit),
        "stdout": stdout,
        "stderr": "",
        "duration_ms": 12,
    }


def tools(workspace):
    made = agent.create_agent(SimpleNamespace(workspace=workspace))
    return {t.fn.__name__: t.fn for t in made["tools"]}


def accepted(report: str) -> bool:
    return (
        all(text in report for text in EXPECT["report_contains"])
        and all(re.search(p, report) for p in EXPECT["report_matches"])
        and not any(text in report for text in EXPECT["report_excludes"])
    )


def test_decide_writes_runs_the_script_records_and_finishes():
    history = []
    assert agent.decide("task", history) == ToolCall("write_note")
    history.append(ToolResult("write_note", {}, {"path": "report.md"}))
    assert agent.decide("task", history) == ToolCall("skill_run", RUN)
    history.append(ToolResult("skill_run", RUN, ran()))
    assert agent.decide("task", history) == ToolCall("record_check", {"passed": True})
    history.append(ToolResult("record_check", {"passed": True}, {"path": "report.md"}))
    assert agent.decide("task", history) == Done("Report checked.")


@pytest.mark.parametrize(
    "result",
    [
        ran(exit_status=1, stdout='{"ok": false}'),
        ran(stdout='{"ok": false}'),
        ran(stdout="not json"),
        ran(stdout="[true]"),
        ran(stdout=""),
        ran(limits_hit=["time"]),
        ran(exit_status=None),
        {"refused": "digest", "message": "The skill is not what the lock pins."},
        {"error": "launcher_failure"},
        "ok",
    ],
)
def test_a_run_that_did_not_end_well_is_recorded_as_failed(result):
    history = [
        ToolResult("write_note", {}, {"path": "report.md"}),
        ToolResult("skill_run", RUN, result),
    ]
    assert agent.decide("task", history) == ToolCall("record_check", {"passed": False})
    history.append(ToolResult("record_check", {"passed": False}, {"path": "report.md"}))
    assert agent.decide("task", history) == Done("The report check failed.")


async def test_the_suite_accepts_only_a_report_whose_check_passed(tmp_path):
    made = tools(tmp_path)
    assert await made["write_note"]() == {"path": "report.md"}
    assert not accepted((tmp_path / "report.md").read_text())
    assert await made["record_check"](False) == {"path": "report.md"}
    assert not accepted((tmp_path / "report.md").read_text())
    assert await made["record_check"](True) == {"path": "report.md"}
    assert accepted((tmp_path / "report.md").read_text())


async def test_recording_twice_leaves_one_outcome(tmp_path):
    made = tools(tmp_path)
    await made["record_check"](True)
    await made["record_check"](True)
    assert (tmp_path / "report.md").read_text().count("check: ") == 1


async def test_an_outcome_that_is_not_a_boolean_is_refused(tmp_path):
    assert "error" in await tools(tmp_path)["record_check"]("passed")
    assert not (tmp_path / "report.md").exists()


async def test_a_symbolic_link_report_is_not_written_through(tmp_path):
    target = tmp_path / "elsewhere.txt"
    target.write_text("keep")
    (tmp_path / "report.md").symlink_to(target)
    await tools(tmp_path)["write_note"]()
    assert target.read_text() == "keep"
    assert not (tmp_path / "report.md").is_symlink()


def test_the_manifest_has_no_model_asks_for_the_effect_and_lists_the_skill():
    manifest = yaml.safe_load((ROOT / "agent.yaml").read_text())
    assert manifest["model"] is None
    assert manifest["skills"] == ["report-check"]
    assert manifest["requires"]["effects"] == ["sandbox_execute"]
    assert "tools" not in manifest["requires"]


def test_the_lock_pins_the_skill_the_agent_lists():
    lock = json.loads((ROOT / "skills.lock").read_text())
    assert [s["name"] for s in lock["skills"]] == ["report-check"]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", lock["skills"][0]["digest"])

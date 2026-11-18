import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from alias_rehearsal_pass import agent

ROOT = Path(__file__).resolve().parents[1]
SUITE = yaml.safe_load((ROOT / "evaluation/suite.yaml").read_text())
PATTERNS = [p for case in SUITE["cases"] for p in case["expect"]["report_matches"]]


def answer_tool(workspace):
    tools = agent.create_agent(SimpleNamespace(workspace=workspace))["tools"]
    return tools[0].fn


def accepted(report: str) -> bool:
    return all(re.search(p, report) for p in PATTERNS)


async def test_the_report_is_accepted_by_the_suite(tmp_path):
    assert await answer_tool(tmp_path)("kestrel") == {"path": "report.md"}
    assert accepted((tmp_path / "report.md").read_text())


@pytest.mark.parametrize(
    "word", ["", "two words", "kes trel", "kestrel\nmodel: x", "k3strel", "a" * 33]
)
async def test_a_word_that_is_not_one_short_token_is_refused(tmp_path, word):
    assert "error" in await answer_tool(tmp_path)(word)
    assert not (tmp_path / "report.md").exists()


async def test_a_symbolic_link_report_is_not_written_through(tmp_path):
    target = tmp_path / "elsewhere.txt"
    target.write_text("keep")
    (tmp_path / "report.md").symlink_to(target)
    await answer_tool(tmp_path)("kestrel")
    assert target.read_text() == "keep"
    assert not (tmp_path / "report.md").is_symlink()
    assert accepted((tmp_path / "report.md").read_text())


def test_the_manifest_names_fast_on_llm_fast_and_no_tool_server():
    manifest = yaml.safe_load((ROOT / "agent.yaml").read_text())
    assert manifest["model"]["name"] == "fast"
    assert manifest["model"]["backend"] == "llm-fast"
    assert "tools" not in manifest["requires"]

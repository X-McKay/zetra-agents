import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from agent_runtime import models

from alias_rehearsal_fail import agent

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = yaml.safe_load((ROOT / "agent.yaml").read_text())
SUITE = yaml.safe_load((ROOT / "evaluation/suite.yaml").read_text())
PATTERNS = [p for case in SUITE["cases"] for p in case["expect"]["report_matches"]]


def answer_tool(workspace):
    tools = agent.create_agent(SimpleNamespace(workspace=workspace))["tools"]
    return tools[0].fn


def accepted(report: str) -> bool:
    return all(re.search(p, report) for p in PATTERNS)


class Gateway:
    """A chat client that answers with a model name, or raises, and remembers its calls."""

    def __init__(self, served=None, error=None):
        self.served, self.error, self.calls = served, error, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(model=self.served)


def serve(monkeypatch, gateway):
    monkeypatch.setattr(models, "chat_client", lambda: gateway)
    return gateway


async def test_the_report_is_accepted_by_the_suite(tmp_path, monkeypatch):
    serve(monkeypatch, Gateway("Qwen/Qwen3.5-0.8B"))
    assert await answer_tool(tmp_path)("kestrel") == {"path": "report.md"}
    assert accepted((tmp_path / "report.md").read_text())


async def test_a_moved_alias_fails_the_suite_on_the_model_line_only(tmp_path, monkeypatch):
    serve(monkeypatch, Gateway("Qwen/Qwen3.5-0.8B-rehearsal"))
    await answer_tool(tmp_path)("kestrel")
    report = (tmp_path / "report.md").read_text()
    assert re.search(PATTERNS[0], report)
    assert not re.search(PATTERNS[1], report)
    assert not accepted(report)


async def test_a_client_that_raises_is_reported_and_fails_the_suite(tmp_path, monkeypatch):
    serve(monkeypatch, Gateway(error=ConnectionError("down")))
    assert await answer_tool(tmp_path)("kestrel") == {"path": "report.md"}
    report = (tmp_path / "report.md").read_text()
    assert "model: unavailable (ConnectionError)" in report
    assert not accepted(report)


async def test_the_gateway_is_asked_with_the_manifest_model_and_one_token(tmp_path, monkeypatch):
    gateway = serve(monkeypatch, Gateway("Qwen/Qwen3.5-0.8B"))
    await answer_tool(tmp_path)("kestrel")
    assert len(gateway.calls) == 1
    assert gateway.calls[0]["model"] == MANIFEST["model"]["name"]
    assert gateway.calls[0]["max_tokens"] == 1


@pytest.mark.parametrize(
    "word", ["", "two words", "kes trel", "kestrel\nmodel: x", "k3strel", "a" * 33]
)
async def test_a_word_that_is_not_one_short_token_is_refused(tmp_path, monkeypatch, word):
    gateway = serve(monkeypatch, Gateway("Qwen/Qwen3.5-0.8B"))
    assert "error" in await answer_tool(tmp_path)(word)
    assert not (tmp_path / "report.md").exists()
    assert gateway.calls == []


async def test_a_symbolic_link_report_is_not_written_through(tmp_path, monkeypatch):
    serve(monkeypatch, Gateway("Qwen/Qwen3.5-0.8B"))
    target = tmp_path / "elsewhere.txt"
    target.write_text("keep")
    (tmp_path / "report.md").symlink_to(target)
    await answer_tool(tmp_path)("kestrel")
    assert target.read_text() == "keep"
    assert not (tmp_path / "report.md").is_symlink()
    assert accepted((tmp_path / "report.md").read_text())


def test_the_manifest_names_fast_on_llm_fast_and_no_tool_server():
    assert MANIFEST["model"]["name"] == agent.MODEL == "fast"
    assert MANIFEST["model"]["backend"] == "llm-fast"
    assert "tools" not in MANIFEST["requires"]

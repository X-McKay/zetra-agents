"""The script of the skill `report-check`, run in this process against a directory that
stands for the workspace. The launcher is what runs it in a session; that is tested in
zetra."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "skills/report-check/scripts/check_report.py"


@pytest.fixture
def check(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("check_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.chdir(tmp_path)

    def run(*arguments):
        status = module.main(list(arguments))
        return status, json.loads(capsys.readouterr().out)

    return run


def test_a_report_with_every_line_passes(tmp_path, check):
    (tmp_path / "report.md").write_text("# Title\n\n## Findings  \nfine\n\n## Advice\n")
    assert check("## Findings", "## Advice") == (
        0,
        {"report": "report.md", "ok": True, "bytes": 39, "missing": [], "problem": None},
    )


def test_with_no_arguments_only_the_file_is_checked(tmp_path, check):
    (tmp_path / "report.md").write_text("anything\n")
    status, said = check()
    assert (status, said["ok"]) == (0, True)


def test_a_missing_line_is_named(tmp_path, check):
    (tmp_path / "report.md").write_text("## Findings\n\nSee ## Advice below.\n")
    status, said = check("## Findings", "## Advice")
    assert (status, said["ok"], said["missing"]) == (1, False, ["## Advice"])


def test_no_report_is_a_failure(check):
    status, said = check("## Findings")
    assert (status, said["problem"], said["bytes"]) == (1, "absent", None)


def test_a_link_is_not_followed(tmp_path, check):
    (tmp_path / "elsewhere.md").write_text("## Findings\n")
    (tmp_path / "report.md").symlink_to(tmp_path / "elsewhere.md")
    status, said = check("## Findings")
    assert (status, said["problem"]) == (1, "not_a_file")


def test_a_report_the_platform_would_cut_is_a_failure(tmp_path, check):
    (tmp_path / "report.md").write_text("## Findings\n" + "x" * 16000)
    status, said = check("## Findings")
    assert (status, said["problem"], said["bytes"]) == (1, "too_large", 16012)


def test_a_report_that_is_not_text_is_a_failure(tmp_path, check):
    (tmp_path / "report.md").write_bytes(b"## Findings\n\xff\xfe")
    status, said = check("## Findings")
    assert (status, said["problem"]) == (1, "not_text")


@pytest.mark.parametrize("argument", ["", "   ", "## Findings\n## Advice", "a\rb"])
def test_an_argument_that_cannot_be_a_line_is_a_usage_error(tmp_path, check, argument):
    (tmp_path / "report.md").write_text("## Findings\n")
    status, said = check(argument)
    assert (status, said["problem"]) == (2, "arguments")


def test_checking_changes_nothing(tmp_path, check):
    (tmp_path / "report.md").write_text("## Findings\n")
    before = sorted(p.name for p in tmp_path.iterdir()), (tmp_path / "report.md").stat().st_mtime_ns
    assert check("## Findings") == check("## Findings")
    assert before == (
        sorted(p.name for p in tmp_path.iterdir()),
        (tmp_path / "report.md").stat().st_mtime_ns,
    )

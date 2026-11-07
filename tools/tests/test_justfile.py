"""Exercise recipe exit statuses without installing every agent environment."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("failing_agent", ["first", ""])
def test_check_propagates_an_early_agent_failure(tmp_path, failing_agent):
    just = shutil.which("just")
    if just is None:
        pytest.skip("just is required to exercise the repository recipes")
    shutil.copyfile(REPO / "justfile", tmp_path / "justfile")
    for directory in ("tools", "agents/first", "agents/last", "bin"):
        (tmp_path / directory).mkdir(parents=True)
    uv = tmp_path / "bin/uv"
    uv.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  *"zetra-agents list"*) echo \'["first", "last"]\'; exit 0 ;;\n'
        "esac\n"
        'case "$PWD:$*" in\n'
        '  */agents/*:*"ruff check ."*)\n'
        "    agent=${PWD##*/}\n"
        '    echo "$agent" >> "$CHECK_LOG"\n'
        '    if [ "$agent" = "$FAILING_AGENT" ]; then exit 17; fi ;;\n'
        "esac\n"
    )
    uv.chmod(0o755)
    log = tmp_path / "checks.log"
    result = subprocess.run(
        [just, "check"],
        check=False,
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{uv.parent}{os.pathsep}{os.environ['PATH']}",
            "CHECK_LOG": str(log),
            "FAILING_AGENT": failing_agent,
        },
        capture_output=True,
        text=True,
    )
    if failing_agent:
        assert result.returncode != 0, result.stdout + result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert log.read_text().splitlines() == ["first", "last"]

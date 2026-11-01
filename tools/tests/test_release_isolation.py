"""Release validation must not execute agent code in its credentialed host shell."""

import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_release_routes_quality_through_uncredentialed_container(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(REPO / "scripts", root / "scripts")
    agent = root / "agents" / "probe"
    (agent / "scripts").mkdir(parents=True)
    (agent / "scripts" / "quality.sh").write_text("exit 81\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls"
    commands = {
        "git": '#!/bin/sh\ncase "$1" in rev-parse) printf "%s\\n" "$TEST_REPO";; status) exit 0;; archive) tar -cf - --files-from /dev/null;; esac\n',
        "uv": """#!/bin/sh
case "$*" in *" check "*) exit 0;; esac
echo host-agent-code >> "$TEST_LOG"
exit 82
""",
        "docker": """#!/bin/sh
if [ "$1" = run ]; then
  for arg in "$@"; do
    case "$arg" in -v|--volume|--mount|--env-file|COSIGN*|DOCKER_CONFIG*) exit 83;; esac
  done
  echo isolated-quality-container >> "$TEST_LOG"
  exit 84
fi
exit 0
""",
    }
    for name, text in commands.items():
        path = bin_dir / name
        path.write_text(text)
        path.chmod(0o700)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "TEST_REPO": str(root),
        "TEST_LOG": str(log),
        "COSIGN_KEY": "env://COSIGN_PRIVATE_KEY",
        "COSIGN_PRIVATE_KEY": "synthetic-test-canary",
        "COSIGN_PASSWORD": "synthetic-test-password",
        "REVISION": "a" * 40,
    }
    result = subprocess.run(
        ["bash", str(root / "scripts/release.sh"), "probe"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 84, result.stderr
    assert log.read_text().splitlines() == ["isolated-quality-container"]

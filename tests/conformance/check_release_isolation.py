"""Native canary check for the release-validation container boundary."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory(prefix="zetra-host-credentials-") as directory:
    sentinel = Path(directory) / "registry-credentials.json"
    sentinel.write_text('{"synthetic": "host-only-canary"}')
    probe = """
import os, sys
from pathlib import Path
assert 'COSIGN_PRIVATE_KEY' not in os.environ
assert 'COSIGN_PASSWORD' not in os.environ
assert not Path('/var/run/docker.sock').exists()
for path in [sys.argv[1], '/root/.docker/config.json', '/root/.sigstore/root.json']:
    try:
        open(path).read()
    except (FileNotFoundError, PermissionError):
        continue
    raise AssertionError('host credential file is readable')
print('synthetic signing environment and host credential files are inaccessible')
"""
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--read-only",
            "--user",
            "1500:1500",
            "--network",
            "none",
            "--tmpfs",
            "/tmp",
            "--entrypoint",
            "/app/.venv/bin/python",
            sys.argv[1],
            "-c",
            probe,
            str(sentinel),
        ],
        env={
            **os.environ,
            "COSIGN_PRIVATE_KEY": "synthetic-host-key",
            "COSIGN_PASSWORD": "synthetic-password",
        },
        check=True,
    )

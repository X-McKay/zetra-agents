"""What every agent directory must contain, and the static import check of spec 14.1."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

FORBIDDEN_IMPORTS = {"httpx", "requests", "urllib", "socket", "aiohttp", "subprocess"}
NAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$")
REQUIRED = ("agent.yaml", "deploy/agent.yaml", "Dockerfile", "pyproject.toml", "uv.lock")


@dataclass(frozen=True)
class AgentDir:
    root: Path

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def manifest_path(self) -> Path:
        return self.root / "agent.yaml"

    @property
    def lock_path(self) -> Path:
        return self.root / "uv.lock"

    @property
    def agent_cr_path(self) -> Path:
        return self.root / "deploy" / "agent.yaml"

    def manifest(self) -> dict[str, Any]:
        return yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))

    def agent_cr(self) -> dict[str, Any]:
        return yaml.safe_load(self.agent_cr_path.read_text(encoding="utf-8"))


def find(repo: Path, name: str) -> AgentDir:
    agent = AgentDir(repo / "agents" / name)
    if not agent.root.is_dir():
        raise SystemExit(f"no agent directory agents/{name}")
    return agent


def all_agents(repo: Path) -> list[AgentDir]:
    return [AgentDir(p) for p in sorted((repo / "agents").iterdir()) if p.is_dir()]


def forbidden_imports(src: Path) -> list[str]:
    """Imports of network or process modules anywhere under the agent's source."""
    found = []
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if name.split(".")[0] in FORBIDDEN_IMPORTS:
                    found.append(f"{path}:{node.lineno}: imports {name}")
    return found


def check(agent: AgentDir) -> list[str]:
    """Every problem with one agent directory; an empty list means it is releasable."""
    problems = [f"{agent.name}: missing {f}" for f in REQUIRED if not (agent.root / f).is_file()]
    if problems:
        return problems
    if not NAME.match(agent.name):
        problems.append(f"{agent.name}: directory name is not a DNS label of at most 32")
    manifest, cr = agent.manifest(), agent.agent_cr()
    if manifest.get("name") != agent.name:
        problems.append(f"{agent.name}: agent.yaml name is {manifest.get('name')!r}")
    if cr.get("kind") != "Agent" or cr.get("metadata", {}).get("name") != agent.name:
        problems.append(f"{agent.name}: deploy/agent.yaml must be the Agent named {agent.name}")
    caps = (cr.get("spec") or {}).get("capabilities") or {}
    models = {m["backend"]: set(m["models"]) for m in caps.get("models") or []}
    model = manifest.get("model") or {}
    if model.get("name") not in models.get(model.get("backend"), set()):
        problems.append(f"{agent.name}: manifest model is not granted by the Agent")
    if any(t.get("effect") == "remote_write" for t in manifest.get("tools") or []):
        problems.append(f"{agent.name}: remote_write tools are not admitted")
    src = agent.root / "src"
    problems += [f"{agent.name}: {p}" for p in forbidden_imports(src)] if src.is_dir() else []
    return problems

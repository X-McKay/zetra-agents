"""zetra-agents: `check` every agent, or write the `release` artifacts for one image."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from agent_platform.constants import DEFAULT_TRUST_DOMAIN

from zetra_agents import layout, release

MCP_RESOURCE_BASE = "https://mcp.almckay.io"  # Kubani registry-controller.yaml


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zetra-agents")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="print the agent names as a JSON array")

    chk = sub.add_parser("check", help="layout and static import checks")
    chk.add_argument("agents", nargs="*", help="default: every agent")

    rel = sub.add_parser("release", help="write release artifacts for a pushed image")
    rel.add_argument("agent")
    rel.add_argument("--image", required=True, help="<repository>@sha256:<digest>")
    rel.add_argument("--revision", required=True, help="git commit of the build")
    rel.add_argument("--out", type=Path, required=True)
    rel.add_argument(
        "--mcp-resource-base",
        default=os.environ.get("AGENT_PLATFORM_MCP_RESOURCE_BASE", MCP_RESOURCE_BASE),
    )
    rel.add_argument(
        "--trust-domain",
        default=os.environ.get("AGENT_PLATFORM_TRUST_DOMAIN", DEFAULT_TRUST_DOMAIN),
    )

    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    if args.command == "list":
        print(json.dumps([a.name for a in layout.all_agents(repo)]))
        return 0
    if args.command == "check":
        agents = [layout.find(repo, n) for n in args.agents] or layout.all_agents(repo)
        problems = [p for a in agents for p in layout.check(a)]
        for p in problems:
            print(p, file=sys.stderr)
        if not problems:
            print(f"ok: {', '.join(a.name for a in agents)}")
        return 1 if problems else 0

    agent = layout.find(repo, args.agent)
    problems = layout.check(agent)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    artifacts = release.build(
        agent,
        image=args.image,
        revision=args.revision,
        mcp_resource_base=args.mcp_resource_base,
        trust_domain=args.trust_domain,
    )
    for path in release.write(artifacts, args.out):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""zetra-agents: `check` every agent, write the `release` artifacts for one image, or
build one attestation `predicate` for it."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from agent_platform.constants import DEFAULT_TRUST_DOMAIN

from zetra_agents import attestations, layout, preflight, release

MCP_RESOURCE_BASE = "https://mcp.almckay.io"  # Kubani registry-controller.yaml


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zetra-agents")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="print the agent names as a JSON array")

    chk = sub.add_parser("check", help="layout and static import checks")
    chk.add_argument("agents", nargs="*", help="default: every agent")

    pre = sub.add_parser(
        "preflight", help="offline source/candidate GitOps compatibility before tagging"
    )
    pre.add_argument("agent")
    pre.add_argument("--kubani", type=Path, required=True)
    pre.add_argument("--tag", required=True, help="prospective <agent>/v<version> tag")

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

    pred = sub.add_parser("predicate", help="write one attestation predicate as JSON")
    kinds = pred.add_subparsers(dest="kind", required=True)
    ev = kinds.add_parser("eval", help="eval/v1 from a pytest JUnit XML report")
    ev.add_argument("--junit", type=Path, required=True)
    ev.add_argument("--suite", required=True)
    ev.add_argument("--commit", required=True)
    vu = kinds.add_parser("vuln", help="cosign vuln/v1 from a grype JSON report")
    vu.add_argument("--grype", type=Path, required=True)
    vu.add_argument("--started", type=dt.datetime.fromisoformat, required=True)
    vu.add_argument("--finished", type=dt.datetime.fromisoformat, required=True)
    pv = kinds.add_parser("provenance", help="SLSA provenance v1 from the GitHub Actions env")
    pv.add_argument("--revision", required=True, help="git commit of the build")
    for kind in (ev, vu, pv):
        kind.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "predicate":
        return write_predicate(args)
    repo = args.repo.resolve()
    if args.command == "preflight":
        result = preflight.check(repo, args.kubani, args.agent, args.tag)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ok"] else 1
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


def write_predicate(args: argparse.Namespace) -> int:
    env = os.environ
    run = ""
    if env.get("GITHUB_RUN_ID") and env.get("GITHUB_REPOSITORY"):
        server = env.get("GITHUB_SERVER_URL", "https://github.com")
        run = f"{server}/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"
    if args.kind == "eval":
        predicate = attestations.eval_predicate(args.junit, suite=args.suite, commit=args.commit)
    elif args.kind == "vuln":
        predicate = attestations.vuln_predicate(
            json.loads(args.grype.read_text()),
            started=args.started,
            finished=args.finished,
            invocation_uri=run,
            builder_id=f"https://github.com/{env['GITHUB_WORKFLOW_REF']}"
            if env.get("GITHUB_WORKFLOW_REF")
            else "",
        )
    else:
        predicate = attestations.slsa_provenance(env, revision=args.revision)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(predicate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

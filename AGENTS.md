# Working in zetra-agents

- One agent per `agents/<name>/`, a member of the root uv workspace; run `just check`
  after changes. `just setup` installs everything. Agent dependencies live in the agent's
  own `pyproject.toml`; the one `uv.lock` is the image lock for every agent.
- Declare a tool once, in `create_agent`: `just render` writes the `tools:` list of
  `agent.yaml` from the code and `just check` fails when they differ, so do not edit that
  list by hand. The nine conformance fixtures are the exception: their lists are not
  derived, so edit the list and the set in the fixture's `verify_image.py` together;
  only the image build (`just build`, CI) catches a mismatch there, `just check` does
  not. Every MCP tool the code calls must be granted in `deploy/agent.yaml`, which stays
  hand-written: it is what the security review approves, and `zetra-agents check` holds
  it to the Agent CRD schema.
- Agent code reaches the outside only through `ctx.mcp`. Never import network or process
  modules in an agent package; `zetra-agents check` rejects them.
- `Dockerfile`, `.dockerignore`, `justfile`, the root `pyproject.toml`, `ci.yml` and
  `release.yml` are rendered from zetra `platform/agent-tools` at the zetra commit the
  root pyproject pins; CI fails if they are edited by hand. Change the templates in
  zetra instead, then bump the pin and `zetra-agents render`.
- Conformance fixtures that replace the SDK boundary driver are listed in zetra's
  `layout.FIXTURES` and build with the Dockerfile's `fixture` target; `check` refuses
  `verify_image.py` or a package `step.py` on any other agent.
- Nothing here is applied to a cluster. Kubani owns the applied Agent and AgentRelease, and
  approval is a reviewed Kubani change; never produce an approved release here.
- Release by pushing a tag `<agent>/v<version>` from merged main, one at a time.
- Never commit signing keys, registry credentials, `dist/`, or session output.
- `legacy/openshell-investigator` is the OpenShell POC; change it only to keep it working.

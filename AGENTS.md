# Working in zetra-agents

- One agent per `agents/<name>/`, each its own uv project; run `just check` after changes.
- Keep `agent.yaml`, `create_agent` and `deploy/agent.yaml` in agreement: every tool in the
  code is in the manifest with the same effect, every MCP tool it calls is granted.
- Agent code reaches the outside only through `ctx.mcp`. Never import network or process
  modules in an agent package; `zetra-agents check` rejects them.
- Nothing here is applied to a cluster. Kubani owns the applied Agent and AgentRelease, and
  approval is a reviewed Kubani change; never produce an approved release here.
- Never commit signing keys, registry credentials, `dist/`, or session output.
- `legacy/openshell-investigator` is the OpenShell POC; change it only to keep it working.

# conformance-b

A copy of `../conformance` under a second agent identity. Spec 15.2 T26 presents
agent A's access token from a sandbox of agent B and expects
`deny.pod_agent_mismatch`; the harness needs a second agent that can run
agent-mode sessions, and this is it. `just check` runs both agents.

Conformance-b also supplies `probe_revocation` for T15/T20. It pins one token and
sends bounded MCP initialize requests for up to 240 seconds, continuing through
403 responses. It reports status counts only, never tokens or response bodies.
The in-cluster harness reads actual gateway/APS logs while the probe runs and
temporarily disables or drifts only this fixture Agent. The tool registration is
part of the signed manifest and requires a new reviewed release.

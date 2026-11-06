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

`probe_fail_closed` is the T17 fixture. It schedules exactly five independent MCP
initialize requests per second for 60–240 seconds and pins one token with enough
remaining lifetime. A request timeout remains an error; responses are never
retried or normalized into a denial. It writes every sequence, trace ID, timing,
status and safe error class to `/sandbox/workspace/t17/requests.json` (0600), with
no token, headers or response bodies. The model receives only a compact count and
artifact path. The read-only runner harness verifies the accepted snapshot,
gateway logs and explicit operator scale receipts; this fixture does not scale
the APS. A new signed release is required before live T17 qualification.

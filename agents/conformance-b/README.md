# conformance-b

A copy of `../conformance` under a second agent identity. Spec 15.2 T26 presents
agent A's access token from a sandbox of agent B and expects
`deny.pod_agent_mismatch`; the harness needs a second agent that can run
agent-mode sessions, and this is it. Keep the two directories identical apart
from the agent name (the `agent.yaml` `name`, the Agent `metadata.name` and the
package name); `just check` runs both.

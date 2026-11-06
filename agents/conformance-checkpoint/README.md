# Checkpoint failure fixture (T23)

This separate signed fixture exercises three deterministic boundaries. Boundary
0 writes baseline workspace/state and a 2 MiB padding file. Boundary 1 performs
one allowed `pods_list_in_namespace` through `ctx.mcp`, using the ordinary SDK
client, then commits its local state and `.done`. Boundary 2 completes. The
fixture records fixed run/session/generation/boundary/stage metadata to stderr;
MCP contents, headers and credentials never enter that record.

The image deliberately replaces only its installed SDK `step` module, preserving
the original manifest/factory validators. Docker's build-time check invokes the
actual installed driver with `-I` and checks the baseline and ordinary validators.
Normal agents and the runner's workflow implementation are unchanged. The declared
model remains granted for manifest agreement but this driver makes no model call.

In case b, generation 1 pauses after the real MCP read returns and before changing
state or writing `.done`. It must be killed by the external observed-barrier worker;
a 120-second expiry is an error. Other failure points are paused in actual runner
activity/exec/storage code. A generation restored from the last accepted snapshot
continues at its recorded next boundary. Any attempt to replay a locally completed
boundary fails instead of performing another read.

Release staging and approval belong in Kubani. This image alone does not qualify
T23: the harness must join actual MCP/gateway/APS evidence, Temporal history,
hash-verified checkpoints, exact Pod UID deletion receipts and final cleanup for
all five failure points plus healthy controls.

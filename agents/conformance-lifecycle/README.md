# Lifecycle conformance fixture

This signed T24 guest makes one deterministic workspace checkpoint, then completes
on boundary 1. The retry-exhaustion case instead emits actual invalid JSON at
boundary 1, without advancing its checkpoint. All other faults are performed by
the trusted isolated worker/root operator, never by this guest.

The eight exact task cases are `success`, `aps_down`, `finalizer`, `worker_kill`,
`terminate`, `cancel`, `activity_crash`, and `retry_exhaustion`. No model, MCP,
network, human access token, refresh token or grant access is used. The model
capability is limited to one token/day and one/session, below the unchanged real
backend reservation bound. Genuine grant creation and cleanup observations belong
to the trusted T24 harness/operator.

The Dockerfile explicitly replaces only this image's installed boundary driver,
retains the original SDK manifest/factory validators, and verifies every case
against that installed module. An unpatched ordinary SDK fails visibly. The
production runtime is unchanged. Normal release CI and signing still apply; no
AgentRelease approval is included here.

Local tests establish deterministic wire and validator behavior. They do not
qualify live cleanup, authorize grants, or prove the production eight-hour timer.

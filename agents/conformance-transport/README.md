# T27 transport fixture

This signed fixture makes only credential-free transport probes. Its deterministic
installed boundary driver preserves the unmodified SDK manifest/factory validators;
image CI checks the actual installed module. No model or MCP request is made, and
no grant is needed. The conventional model grant is limited to one token per day
and session to keep manifest validation intact.

The positive gateway probe uses `AgentIdentity._client()` without calling its
refresh method. A plain HTTP GET, without Authorization or a client assertion,
then reaches the same fixed gateway IP on 443. Timeout, connect failure, successful
HTTP and unrelated HTTP errors are failures, not evidence of TLS enforcement.
The negative must observe a reachable listener closing/resetting plaintext or
explicitly stating TLS is required, alongside a successful verified TLS control.

The second control creates a short-lived CA and valid IP-SAN certificate inside
its private `/tmp` directory, starts an unprivileged loopback HTTPS listener, and
first verifies it using that CA. The exact ordinary SDK identity client must
reject it with an unknown-issuer chain error before any application request.
The key and CA are removed in `finally`; neither is committed, deployed as a
Secret, logged, or written to the workspace. No credential is sent to either
negative. Tests deliberately disable verification and require the test to fail.

The workspace contains only bounded statuses, certificate error codes and request
counts. T27's host capture is a separate operator action during an ordinary
conformance Agent T4 session, gated before its first boundary. This fixture does
not perform or authorize host capture and does not alone qualify T27.

# T27 transport fixture

This signed fixture makes only credential-free transport probes. Its deterministic
installed boundary driver preserves the unmodified SDK manifest/factory validators;
image CI checks the actual installed module. No model or MCP request is made, and
no grant is needed. The manifest explicitly declares `model: null`, and the Agent has no model
capabilities or inference routes.

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

The refusal classifier also accepts one complete seven-byte TLS fatal alert:
record type 21, legacy version 0x0303, payload length two, level two, and only
unexpected_message(10) or decode_error(50). This intentionally narrow allowlist
follows [RFC 5246](https://www.rfc-editor.org/rfc/rfc5246) and the gateway v1.7.0
[rustls 0.23.46 alert writer](https://github.com/rustls/rustls/blob/v/0.23.46/rustls/src/common_state.rs).
`15030300020232` is fatal decode_error. Warning, close-notify, unknown codes,
wrong lengths/versions, partial records, and trailing bytes remain failures.
The socket reads through EOF/reset within the existing three-second timeout and
4096-byte bound; a matching prefix alone cannot qualify. Raw response bytes are
never written to fixture output. Arbitrary non-HTTP bytes are `unexpected_response`.

Run31 remains failed historical evidence: its host diagnostic does not prove
what its sandbox received, and its capture never started. This source correction
requires a fresh signed transport fixture release, installed-image verification,
and a new coordinated exact-T4 capture before T27 can qualify. No host capture,
image build or release was performed as part of the local regression tests.

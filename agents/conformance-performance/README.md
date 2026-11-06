# T29 performance fixture

This signed fixture uses a fresh ordinary SDK step process per boundary. Its
initial boundary obtains an agent token and performs one real Kubernetes MCP
read; the second boundary uses the persisted token and another real SDK MCP
session. `warm` means warm token state, never a persistent process or proved
image-cache-cold start. No model inference is issued; its model capability has
one token per day/session. Runtime remains the normal one CPU/1Gi profile.

The `pair` and `recovery` modes have two boundaries. `trial` and `saturation`
add a fixed20-second first-boundary hold so actual concurrent activity and queue
states can be observed. The runner owns any exact Pod-UID kill and all recovery.
The snapshot mode writes exactly the requested file bytes, in bounded chunks,
without network calls; only0..64MiB is admitted. Metadata/state/tar framing are
additional bytes, so a64MiB file intentionally exceeds the unchanged64MiB whole
archive cap. An accepted artifact, its actual workspace payload and archive size
must be measured separately. No artifact here proves Temporal acceptance.

Evidence contains only run/session identity, process/generation/boundary IDs,
monotonic timings, actual payload bytes and a SHA256 token fingerprint. No token,
Authorization header, MCP contents or arbitrary exception messages are emitted.
The fixture fails without a real SDK MCP completion. The isolated driver keeps
the original installed SDK manifest/effect validators, verified during the image
build. The release compiler must retain only the exact remote-read MCP grant.

The agent-platform T29 harness and same-image worker supply independent history,
Pod UID, APS/gateway/capture and memory-capacity evidence. Fixture-only tests do
not qualify latency,20Running Pods, arm64, node capacity or the literal64MiB
snapshot target. Root owns release, separate unapproved Kubani staging and the
exclusive live window; no benchmarks run during host Docker builds.

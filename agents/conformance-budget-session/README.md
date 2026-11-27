# Signed deterministic budget fixture

This image intentionally overrides its installed `agent_runtime.step` only. The
unmodified SDK is preserved for standard manifest/factory validation. Image builds
exercise the installed override and the normal CI contract; production runtime code
is unchanged. Source and verification code must remain identical across the two
budget identities. Each identity has its own manifest, signed release and budget.

`conformance-budget-day` has
exactly 2000 tokens/day; `conformance-budget-session`
has exactly 1000 tokens/session. Both can call only llm-budget-conformance model
conformance-byte-v1, whose server enforces input<=200/output<=100/total<=300 tokens.
A token is explicitly one UTF-8 byte; actual50-input/50-output requests cost100.
These fixtures qualify budget-path enforcement, not Qwen accounting.

The driver makes no model orchestration call. It retains real HTTP statuses and
safe trace/usage/timing evidence in committed state. It never retries failures,
stores bearer evidence or prints arbitrary response/exception material. The session
probe really sets local state.usage to0, commits it, emits one deliberate malformed
wire result on generation1, then uses the runner's ordinary generation2 snapshot
restore to retry. The independent control session remains active for240seconds.
The daily probe pauses120seconds after its first expected refusal for an external
operator to replace both exact old gateway pods. Missing/late restart is a harness
failure, never a simulated success.

Use the existing reviewed release/signing workflow for this agent directory. Kubani
owns applied Agent/AgentRelease, approval, key material, policies and test Jobs; this
repository does not approve or apply releases. See Zetra's budget conformance
playbook for harness flags and trusted observation requirements.

Two retry identities, `conformance-budget-day-retry` and
`conformance-budget-day-retry2`, were released on 2026-11-06 for repeats on the day
the daily ledger was spent. They were retired on 2026-11-27: their source is removed
from this repository, their tags and releases remain, and Kubani keeps both Agents
switched off as the record. A daily ledger cannot be reset, so a repeat on the same
day needs a new identity with its own signed release and exact
gateway/backend/observer authorization; none is generated automatically.

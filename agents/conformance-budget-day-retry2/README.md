# Signed deterministic budget fixture

This image intentionally overrides its installed `agent_runtime.step` only. The
unmodified SDK is preserved for standard manifest/factory validation. Image builds
exercise the installed override and the normal CI contract; production runtime code
is unchanged. Source and verification code must remain identical across the four
budget identities. Each identity has its own manifest, signed release and budget.

`conformance-budget-day` and the fixed `conformance-budget-day-retry` and
`conformance-budget-day-retry2` each have
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

The retry identity uses its own explicitly selected ledger after a failed daily
run. It does not reset or alter the original identity's ledger, limits or evidence,
and it is never generated automatically. It needs its own signed unapproved
release and exact gateway/backend/observer authorization before a root-approved
exclusive run. Missing baseline, late replacement or any unexpected HTTP status
still fails.

Retry2 is an explicit new signed identity after run 30 consumed 1800 tokens on the
first retry fixture before Kubernetes log deserialization blocked evidence
collection. The first retry ledger, original ledger and failed reports remain
unchanged. No budget reset or automatic identity generation is performed.

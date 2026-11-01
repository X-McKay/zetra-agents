# zetra-agents

Agents built with [Zetra](https://github.com/X-McKay/zetra) and deployed by
[Kubani](https://github.com/X-McKay/kubani) on the Agent Runtime Platform. Zetra owns
the platform and the sandbox SDK (`platform/agent-runtime`); Kubani owns the cluster
and every object applied to it; this repository owns the agents: their code, their
manifests and capabilities, and the signed releases Kubani consumes.

## Layout

```
agents/<name>/                one directory per agent, each its own uv project
  agent.yaml                  manifest (spec 11.7), baked in as /app/agent.yaml
  deploy/agent.yaml           the Agent resource (spec 6.1): identity, models, MCP tools, budget
  src/<package>/              create_agent(ctx) and the agent's instructions
  tests/                      unit tests, including manifest/tool agreement
  Dockerfile                  the agent image: SDK venv + manifest + package, UID 1500
  pyproject.toml, uv.lock     the image lock; its SHA-256 is AgentRelease.spec.lockSha256
tools/                        `zetra-agents check | list | release`, pinned to the zetra
                              contracts the Registry Controller runs
scripts/release.sh            build, push, sign, attest, write release artifacts
legacy/openshell-investigator the OpenShell POC moved from kubani pocs/, kept until
                              OpenShell is retired after platform Phase B
```

## Writing an agent

New agents use ordinary Python: `create_agent(ctx)` returns an ADK `LlmAgent`
using `ctx.model`, `ctx.instruction`, and `ctx.tools(zetra.Tool(...))`. The same
packaged SDK definition runs locally, under local Temporal, and in the platform's
explicit `zetra-core-v1` profile. The schema-2 root envelope points to that resource;
`[tool.zetra.agents]` indexes the same file. Old immutable releases retain their
legacy runtime and are not relabelled or resumed as core sessions.

`ctx.workspace` holds run artifacts. Registered `remote_read` tools may call
`await ctx.mcp(backend, tool, arguments)`. Local calls need explicit fixtures; the
platform injects the reviewed authenticated gateway binding. Factory/background
MCP calls and unbound calls fail. Remote writes remain outside the admitted profile.

Two references cover different workloads:

- `investigator`: scoped synthetic Kubernetes observations and a cited report;
  existing MCP capabilities are unchanged.
- `documentassistant`: approved packaged documentation, a runtime grounding skill,
  exact-quote output and explicit abstention. No external MCP capability.

```sh
just setup
just check                   # static checks, tests, component/trajectory quality gates
cd agents/investigator
uv run --locked zetra dev . --input "Investigate the synthetic pod" \
  --mcp-fixtures evals/investigator/mcp.json
# Optional native local Temporal: append --temporal (Linux; no cluster needed).
bash scripts/quality.sh      # explicitly selects this agent's synthetic MCP fixture
```

The document assistant uses the same commands without `--mcp-fixtures`.
`zetra quality . --explain` shows required coverage; `evals/<agent>/quality.json`
maps every tool to contract/security/recovery tests and the agent to outcome,
trajectory and performance evidence. Runtime skills require contract, activation
and nonactivation coverage. CI and the release script execute these gates.
Deterministic fixtures and step budgets are not live accuracy, latency, cost or
prompt-injection qualification. Representative model evals and calibrated gates
remain required before production approval.

`zetra-agents check` is data-only: it rejects missing/different packaged resources,
unsupported profiles, model permissions and tool/quality inventory drift without
importing factories. Static network-import checks are a review aid, not a sandbox.
New artifact generation requires schema 2; downgrade/mixed legacy manifests fail.
Existing immutable legacy images and histories remain supported by the platform.
Image conformance runs the installed package as UID 1500, read-only and with no
external network, comparing local results with cold core commands through a TLS
model/MCP fixture. Build-time Git and development dependencies are absent from the
runtime image.

Start ordinary local-first projects with the canonical `zetra-template`. These
references add the currently required reviewed Agent resource and platform envelope;
a deployment scaffold that generates those files is still a future DX improvement.
Run `just build <agent>` to build locally. No cluster stages are changed here.

## Releasing

A tag `<agent>/v<version>` runs `.github/workflows/release.yml`, which calls
`scripts/release.sh`. The same script runs anywhere with Docker, cosign and the keys
(`just release <agent>` on RIG0 when GitHub-hosted runners cannot reach the registry):

1. Refuse a dirty agent tree and export the selected Git revision. Build and run
   its validation target without inherited signing variables, credential files, host
   mounts or external network. Cache writes go to tmpfs. Agent code never executes
   in the credentialed release shell.
2. Build, verify the installed image against offline/core TLS fixtures, then push to `registry.almckay.io/agents/<agent>`, the repository Kubani's
   admission accepts, and resolve the pushed digest.
3. Write `dist/<agent>/`:

   | File | What |
   | --- | --- |
   | `agent.yaml` | the Agent resource |
   | `agentrelease.yaml` | the AgentRelease, `approval.approved: false`, with `image@sha256`, `manifestSha256`, `lockSha256`, `policySha256`, `buildRevision` |
   | `policy-bundle.json` | the compiled bundle (spec 6.3) security review reads |
   | `predicate.json` | the attestation predicate |
   | `image`, `SHA256SUMS` | the pinned reference and checksums |

4. `cosign sign` the digest and `cosign attest` the predicate
   (`https://agentplatform.io/attestations/release/v1`), then verify both when
   `COSIGN_PUBLIC_KEY` is set. Transparency-log upload is off by default; it must match
   how Kubani's Kyverno Rule 1 verifies (an open decision in Kubani's
   `docs/infrastructure/configuration/agent-runtime-platform.md`).
5. Publish the files as a GitHub release.

The policy digest is computed with the same `agent_platform` contracts commit the
Registry Controller runs. When Kubani moves to a newer controller image, bump the pin
in `tools/pyproject.toml` with it, or the controller's recomputed digest will differ and
the release will never be ready.

The workflow needs secrets `REGISTRY_USERNAME`, `REGISTRY_PASSWORD`,
`COSIGN_PRIVATE_KEY`, `COSIGN_PASSWORD`, and optionally variables `COSIGN_PUBLIC_KEY`,
`RELEASE_RUNNER`, `AGENT_REGISTRY`, `COSIGN_TLOG_UPLOAD`.

## Deploying through Kubani

Kubani applies agents from `infrastructure/gitops/apps/agents/<tenant>/<agent>/`
(spec 14.1):

1. PR the Agent (`dist/<agent>/agent.yaml`) and wait for its `Ready` condition.
2. PR the unapproved `agentrelease.yaml`; wait for `status.signatureVerified` and
   `status.policyDigest`.
3. Security review reads the policy bundle ConfigMap and the image's `agent.yaml`, then
   approves with a PR setting `approval.approved: true`, `approvedBy`, `approvedAt` and
   `ticket`. Approval is not part of the policy digest, so it does not invalidate it.
4. Confirm `status.ready: true` and run the smoke session (T18).

Changing an agent's capabilities is a change to `deploy/agent.yaml` here, then the same
copy into Kubani; the controller recompiles the bundle from the applied Agent, so a
release built against the old Agent stops being ready until a new one is cut.

## Status

The platform is staged in Kubani and has not run on the cluster yet. The OpenShell POC
under `legacy/` is still the investigator that has run there; its deploy recipe is
`legacy/openshell-investigator/deploy/README.md`.

## Integration pins

Core agents install `agent-runtime` at `1b7e7733f43d0d5487dc4e3b023eecbd2b33cbdb`,
which installs SDK `2c70149d7c0472e79551ce0ce124a885dbf3eaea`. Release tooling uses
contracts `bba8b097789e1b3b6632052ce8e954c6b8c2a669`. Preserve these reachable Git
commits when integrating prerequisite PRs. New core releases require the matching
controller/runner and CRD before activation; legacy deployed stages stay unchanged.
The release builder derives `runtimeProfile` before computing the signed policy
digest and always emits `approval.approved: false`.

## Statistical live-model evaluations

Both references declare separate `smoke` and `reliability` experiments with synthetic
inputs. The document assistant covers exact quotes/citations, skill activation,
abstention and unauthorized requests. The investigator covers evidence ordering,
namespace scope, refusal to repair and instruction attacks embedded in MCP output.
These are development cases, not a hidden holdout or a claim of model robustness.

From an agent directory, inspect budgets with `uv run --locked zetra quality .
--explain`. Run a bounded smoke against an explicitly configured model:

```sh
uv run --locked zetra eval . --mode local --experiment smoke --model-config /private/model.json --output /private/smoke.json
```

For investigator, additionally pass `--mcp-fixtures evals/investigator/mcp-live.json`.
Use `mcp.json` for the ordinary offline quality gate. No live MCP or cluster connection
is needed. `reliability` uses 40 trials per case, all-assertions-pass and an approximate
per-case Wilson lower bound of 0.8 with Bonferroni adjustment at requested 95% family
confidence. These illustrative targets must be adapted before new studies. They do
not establish production or unseen-task accuracy. Repeated trials are not additional
independent cases; do not add samples/rerun until passing or discard failures.

Use `zetra quality . --mode local --experiment reliability --model-config FILE` for
the combined deterministic/live gate, adding the investigator fixture option. Its
live evidence is nested under `experiment`. Standalone `eval` reports can be compared
with `zetra eval-compare BASELINE.json CANDIDATE.json`; noninferiority can remain
inconclusive even if both configurations pass every case. Missing usage is not zero.
Token caps are checked after a bounded trial and may overshoot by that trial; model
request counts are capped before dispatch. This is not an exact monetary budget.

The manual live workflow requires a preconfigured GitHub environment named
`live-evaluation` with default-branch-only deployment protection, administrator-owned
`EVAL_MODEL_BASE_URL` / `EVAL_MODEL_NAME` variables and an optional dedicated
environment secret `EVAL_MODEL_API_KEY`. Do not put this key in repository-wide
secrets or mix in signing/registry credentials. Endpoint/model configuration is not
a dispatch input. Routine CI is offline; live execution is trusted code only. Compact
reports exclude prompts/answers/tool results but can contain sensitive metadata;
workflow artifacts retain seven days. No merge, release, deployment or production
qualification is performed by this workflow.

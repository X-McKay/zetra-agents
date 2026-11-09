# zetra-agents

Agents built with [Zetra](https://github.com/X-McKay/zetra) and deployed by
[Kubani](https://github.com/X-McKay/kubani) on the Agent Runtime Platform. Zetra owns
the platform and the sandbox SDK (`platform/agent-runtime`); Kubani owns the cluster
and every object applied to it; this repository owns the agents: their code, their
manifests and capabilities, and the signed releases Kubani consumes.

`conformance-protocol` is the dedicated T25 wire-protocol fixture. Its Dockerfile
explicitly replaces the installed `agent_runtime.step` module and runs
`verify_image.py` using that installed module before the image can build. It keeps
the original SDK manifest/factory validators, normal wait process and sandbox
shape. The standard image CI check remains unchanged and a mismatched manifest
must still fail. The fixture makes no model/network
calls: a task selects a healthy completion or a checkpoint followed by 10 MiB
stdout, invalid JSON, a wrong boundary number, done:true with rc0, or a permanent
hang. The ordinary agent factory fails visibly if the SDK override is missing.
This is a test image, not a production runtime fallback. Its passing subprocess
tests mean the intended faults are produced; only retained live runner evidence
can qualify T25. The normal tag/signature/attestation pipeline still applies, and
Kubani must pin the new signer identity and approve the specific release.

## Layout

The same layout every agent repository has, whether it holds one agent or thirteen
(`zetra init` renders it; see zetra `docs/agents.md`):

```
agents/<name>/                one directory per agent, a member of the root uv workspace
  agent.yaml                  manifest (spec 11.7), baked in as /app/agent.yaml
  deploy/agent.yaml           the Agent resource (spec 6.1): identity, models, MCP tools, budget
  pyproject.toml              this agent's dependencies (agent-runtime, pinned once at the root)
  src/<package>/              create_agent(ctx) and the agent's instructions
  tests/                      unit tests, including manifest/tool agreement
  verify_image.py             conformance fixtures only: checks the installed SDK override
pyproject.toml, uv.lock       one workspace, one lock; its SHA-256 is AgentRelease.spec.lockSha256
                              for every agent released from here
Dockerfile                    one image recipe: targets `runtime` and `fixture` (UID 1500)
justfile, .dockerignore       rendered with the Dockerfile from zetra platform/agent-tools
.github/workflows/ci.yml      rendered: check, render check, per-agent tests and image build
.github/workflows/release.yml rendered shim: calls zetra's agent-release action on <agent>/v* tags
.github/workflows/legacy.yml  this repository's own checks for legacy/
legacy/openshell-investigator the OpenShell POC moved from kubani pocs/, kept until
                              OpenShell is retired after platform Phase B
```

The rendered files pin one zetra commit (root `pyproject.toml`, `[tool.uv.sources]`)
that provides the sandbox SDK in the images, the `zetra-agents` tooling and the
`agent_platform` contracts the Registry Controller runs. `zetra-agents render --check`
fails in CI if a rendered file is edited by hand; change the templates in zetra, bump the
pin, `uv lock`, and `uv run --locked zetra-agents render`.

## Writing an agent

An agent is a package whose `create_agent(ctx)` returns `{"tools": [Tool(fn, effect)]}`.
`ctx.workspace` is the session's workspace, `ctx.instructions` the loaded instructions,
and `ctx.mcp(backend, tool, arguments)` the only route out: it goes through the gateway
with the agent's own token. Effects are `workspace_read`, `workspace_write` and
`remote_read`; `remote_write` is not admitted. Tool docstrings are the descriptions the
model sees.

`zetra-agents check` (run in CI) refuses an agent whose source imports `httpx`,
`requests`, `urllib`, `socket`, `aiohttp` or `subprocess` (spec 14.1), whose manifest
names a model the Agent does not grant, or whose names disagree. Deterministic
boundary drivers explicitly declare `model: null` and `capabilities.models: []`;
a missing model field remains an error. This declaration grants no inference
route; deterministic behavior comes from the implementation, not this declaration.
The ordinary SDK inference loop remains unchanged. Each agent's tests load
the manifest through the SDK's own `build_agent`, and CI does the same inside the built
image, so a tool added to the code but not to `agent.yaml` fails before release.

To add one, copy `agents/investigator`, rename the directory, package and names, set the
Agent's tenant namespace to one Kubani defines, then `uv lock` at the root (the new member
joins the one lock). A new repository instead of a new directory is `zetra init`.

```sh
just setup           # the locked workspace: every agent and the tooling
just check           # what CI runs, minus the image build
just build <agent>   # local image with the agent's target, not pushed
```

## Releasing

Before creating or pushing a tag, run the offline compatibility preflight against an
explicit Kubani candidate checkout:

```sh
just preflight db-admin db-admin/v0.1.2 /path/to/kubani
```

This compares source with **candidate desired GitOps**, checks both model budgets
against APS reservations, and checks both tenant signer declarations against the
prospective workflow identity. It does not inspect live cluster state or remaining
daily allowance. Only the selected agent is checked. The source checkout must be
clean and the prospective tag must not already exist locally. Candidate worktree
edits are allowed; the JSON receipt records both HEADs, dirty flags, input hashes
and local main ancestry. Exit 0 means compatible; exit 1 includes structured errors.

Update checkout references through your normal process and review the recorded local
main relation: preflight never fetches and cannot prove remote freshness. Missing or
divergent local main refs are informational, allowing intentional maintenance branches.
Re-run after changing either checkout and immediately before tagging. This command
adds no automatic workflow gate and does not create a tag or approve a release.

A tag `<agent>/v<version>` runs `.github/workflows/release.yml` on Kubani's
`kubani-zetra-agents` runner scale set, which calls zetra's
`.github/actions/agent-release` composite action at the pinned zetra commit:

1. Check the agent and the rendered files, refuse a dirty tree (a release is a commit),
   and refuse to run as any identity other than the tenant's pin (this workflow on an
   `<agent>/v*` tag).
2. Run the agent's tests; their JUnit report becomes the eval predicate.
3. Build with the agent's image target (`runtime`, or `fixture` for the conformance
   fixtures), push to `registry.almckay.io/agents/<agent>`, the repository Kubani's
   admission accepts, and resolve the pushed digest.
4. Write `dist/<agent>/`:

   | File | What |
   | --- | --- |
   | `agent.yaml` | the Agent resource |
   | `agentrelease.yaml` | the AgentRelease, `approval.approved: false`, with `image@sha256`, `manifestSha256`, `lockSha256`, `policySha256`, `buildRevision` |
   | `policy-bundle.json` | the compiled bundle (spec 6.3) security review reads |
   | `predicate.json` | the release predicate (`https://agentplatform.io/attestations/release/v1`) |
   | `provenance.json` | SLSA provenance v1 for the run |
   | `sbom.spdx.json` | syft's SPDX SBOM of the pushed digest |
   | `vuln.json` | grype's scan of that SBOM, findings with a fix only, as a cosign vuln/v1 predicate |
   | `vuln-full.json` | the complete grype report, including findings the distribution will not fix |
   | `eval.json` | the eval/v1 predicate from the agent's tests |
   | `image`, `SHA256SUMS` | the pinned reference and checksums |

5. Sign the digest and attest the five predicates **keylessly through Kubani's private
   Sigstore**: Fulcio (`https://fulcio.almckay.io`) certifies the workflow's GitHub OIDC
   identity, Rekor (`https://rekor.almckay.io`) logs every entry. There is no signing key.
   The trust roots ship with the action, pinned by the zetra commit; public Sigstore is
   never used.
6. Verify the signature and all five attestations against those roots with the tenant's
   identity pin, then run the eval and vuln conditions Kyverno applies (`agentctl
   validate`): no Critical findings, High only when listed in `VULN_EXCEPTIONS`.
7. Publish the files as a GitHub release.

Fulcio accepts only GitHub Actions tokens, so releases cannot be signed from a laptop.

The conformance agent's T19 probe pins one token for 50 MCP allow/deny cycles,
records the actual tools/call HTTP statuses and monotonic duration, and can then
run two main/fast model-route cycles with six-second settlement pauses. Its raw
tool result is retained in the runner's accepted snapshot; the model's compact
summary is not the qualification evidence. HTTP 429s and timeouts are preserved
as failures, never retried into passes. `conformance-b` keeps the same probe code
for source parity, but only the primary conformance release is needed for T19.
cosign, syft and grype come from `registry.almckay.io/mirror/` by digest (see the
workflow's `env`); grype downloads its vulnerability database on each run.

The policy digest is computed with the same `agent_platform` contracts commit the
Registry Controller runs. When Kubani moves to a newer controller image, bump the zetra
pin in the root `pyproject.toml` with it (then `uv lock` and `zetra-agents render`), or
the controller's recomputed digest will differ and the release will never be ready.

The workflow needs secrets `REGISTRY_USERNAME`, `REGISTRY_PASSWORD`, variable
`RELEASE_RUNNER=kubani-zetra-agents`, and optionally `AGENT_REGISTRY` and
`VULN_EXCEPTIONS`.

## Deploying through Kubani

Kubani applies agents from `infrastructure/gitops/apps/agents/<tenant>/<agent>/`
(spec 14.1):

1. Once per repository, `just agent register <tenant> <owner/repo> <agent>...`
   in Kubani copies the Agent from this checkout and pins this repository's release
   identity for exactly these agents; later Agent changes are `just agent sync`. Wait
   for the `Ready` condition.
2. `just agent stage <agent> <agent>/vX.Y.Z` verifies the published assets and PRs the
   unapproved `agentrelease.yaml`; wait for `status.signatureVerified` and
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

Local installed-fixture checks must use a private `UV_CACHE_DIR` and
`UV_LINK_MODE=copy`. Before replacing an installed SDK module, call
`zetra_agents.verification.replace_installed_file(path, content)` from the
workspace environment (`uv run --locked python`). It atomically replaces the directory entry; writing directly through a
uv-installed path can overwrite a hardlinked shared cache or another environment.
The helper has a real hardlink regression. Image validation still runs against
its own installed SDK inside the release build; local checks do not replace it.

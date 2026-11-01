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
tools/                        `zetra-agents check | list | release | predicate`, pinned to the zetra
                              contracts the Registry Controller runs
scripts/release.sh            build, push, keyless sign + attest, verify, write release artifacts
.github/sigstore/             the private Sigstore trust roots releases sign and verify with
legacy/openshell-investigator the OpenShell POC moved from kubani pocs/, kept until
                              OpenShell is retired after platform Phase B
```

## Writing an agent

An agent is a package whose `create_agent(ctx)` returns `{"tools": [Tool(fn, effect)]}`.
`ctx.workspace` is the session's workspace, `ctx.instructions` the loaded instructions,
and `ctx.mcp(backend, tool, arguments)` the only route out: it goes through the gateway
with the agent's own token. Effects are `workspace_read`, `workspace_write` and
`remote_read`; `remote_write` is not admitted. Tool docstrings are the descriptions the
model sees.

`zetra-agents check` (run in CI) refuses an agent whose source imports `httpx`,
`requests`, `urllib`, `socket`, `aiohttp` or `subprocess` (spec 14.1), whose manifest
names a model the Agent does not grant, or whose names disagree. Each agent's tests load
the manifest through the SDK's own `build_agent`, and CI does the same inside the built
image, so a tool added to the code but not to `agent.yaml` fails before release.

To add one, copy `agents/investigator`, rename the directory, package and names, set the
Agent's tenant namespace to one Kubani defines, then `uv lock` in the new directory.

```sh
just setup           # lock-exact environments for tools and every agent
just check           # what CI runs, minus the image build
just build <agent>   # local image, not pushed
```

## Releasing

A tag `<agent>/v<version>` runs `.github/workflows/release.yml` on Kubani's
`kubani-zetra-agents` runner scale set, which calls `scripts/release.sh`:

1. Check the agent, refuse a dirty tree (a release is a commit), and refuse to run as any
   identity other than the tenant's pin (this workflow on an `<agent>/v*` tag).
2. Run the agent's tests; their JUnit report becomes the eval predicate.
3. Build and push to `registry.almckay.io/agents/<agent>`, the repository Kubani's
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
   | `vuln.json` | grype's scan of that SBOM, as a cosign vuln/v1 predicate |
   | `eval.json` | the eval/v1 predicate from the agent's tests |
   | `image`, `SHA256SUMS` | the pinned reference and checksums |

5. Sign the digest and attest the five predicates **keylessly through Kubani's private
   Sigstore**: Fulcio (`https://fulcio.almckay.io`) certifies the workflow's GitHub OIDC
   identity, Rekor (`https://rekor.almckay.io`) logs every entry. There is no signing key.
   The trust roots are pinned in [`.github/sigstore/`](.github/sigstore/README.md); public
   Sigstore is never used.
6. Verify the signature and all five attestations against those roots with the tenant's
   identity pin, then run the eval and vuln conditions Kyverno applies (`agentctl
   validate`): no Critical findings, High only when listed in `VULN_EXCEPTIONS`.
7. Publish the files as a GitHub release.

Fulcio accepts only GitHub Actions tokens, so releases cannot be signed from a laptop.
cosign, syft and grype come from `registry.almckay.io/mirror/` by digest (see the
workflow's `env`); grype downloads its vulnerability database on each run.

The policy digest is computed with the same `agent_platform` contracts commit the
Registry Controller runs. When Kubani moves to a newer controller image, bump the pin
in `tools/pyproject.toml` with it, or the controller's recomputed digest will differ and
the release will never be ready.

The workflow needs secrets `REGISTRY_USERNAME`, `REGISTRY_PASSWORD`, variable
`RELEASE_RUNNER=kubani-zetra-agents`, and optionally `AGENT_REGISTRY` and
`VULN_EXCEPTIONS`.

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

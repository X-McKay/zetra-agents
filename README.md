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

A tag `<agent>/v<version>` runs `.github/workflows/release.yml`, which calls
`scripts/release.sh`. The same script runs anywhere with Docker, cosign and the keys
(`just release <agent>` on RIG0 when GitHub-hosted runners cannot reach the registry):

1. Check the agent and refuse a dirty tree: a release is a commit.
2. Build and push to `registry.almckay.io/agents/<agent>`, the repository Kubani's
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

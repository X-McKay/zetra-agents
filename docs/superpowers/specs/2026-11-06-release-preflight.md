# Offline release compatibility preflight

Add `zetra-agents preflight <agent> --kubani <checkout> --tag <agent>/v<version>` before operators create/push a release tag. This reads source and candidate desired GitOps files. It does not inspect or describe an applied live Agent. Candidate GitOps can intentionally differ from main and the live release: source and candidate capabilities must agree with each other, without deploying unsigned source first.

## Inputs and binding

Use existing global `--repo` for source, explicit `--kubani`, and required prospective `--tag`. Fix the supported workflow identity to this repository's existing `X-McKay/zetra-agents/.github/workflows/release.yml`; do not infer authority from a writable git remote. Validate the existing `<agent>/v[0-9][A-Za-z0-9.+-]*` convention and exact selected-agent prefix. Reject an already-existing local source tag as a stale-looking prospective input.

The JSON receipt includes schema version 1, `scope: candidate-desired-gitops`, agent, tag, exact subject, resolved source/Kubani paths, both HEADs, both whole-checkout dirty indicators, and the selected files' SHA-256 hashes. Dirty candidate edits are allowed and visible; this permits reviewing a candidate before committing it. Dirty source yields an error because a tag binds HEAD rather than worktree edits. Receipt hashes bind candidate worktree edits even when HEAD is unchanged. Re-run after changing either checkout or before tagging.

Record the local `refs/remotes/origin/main` tip (fall back to `refs/heads/main`) for each checkout. Include its object ID and whether it is an ancestor of HEAD; if neither ref exists, record unavailable metadata. Missing or divergent main refs do not fail compatibility: maintenance and candidate branches may intentionally differ. These are local-ref observations only: the command never fetches and cannot certify that local main is current remotely. Documentation asks operators to update checkout references through their normal process and review the recorded relation before preflight.

## Checks

1. Reuse `layout.find()` and `layout.check()` for the selected agent. No checks of other agents and no exception changes for deliberately underbudget conformance fixtures. Do not add Python AST tool discovery or duplicate SDK policy compilation.
2. Read source `agents/<agent>/deploy/agent.yaml` and candidate `infrastructure/gitops/apps/agents/<namespace>/<agent>/agent.yaml`. Require exactly one Agent with matching name/namespace and equal complete `spec.capabilities` mappings. Equality is structural and list order remains significant, matching declared release input. Report differing field paths, not full file contents. Other spec fields are outside this compatibility comparison.
3. Select exactly one Deployment named `agent-policy-service` and its container named `agent-policy-service` in `infrastructure/gitops/apps/agent-platform/workloads/agent-policy-service.yaml`; require exactly one literal `APS_BACKEND_CATALOGUE` env entry. Parse its JSON. Each granted backend must have positive integer `maxModelLen`; require positive integer `tokensPerSession` and `tokensPerDay`, each at least that reservation. Reject booleans as integers. This checks capacity to admit one reservation, not remaining daily allowance, actual consumption, or runtime availability.
4. Select exactly one matching Namespace in `infrastructure/gitops/infrastructure/namespace-policy/agent-platform-namespaces.yaml`, and exactly one `ConfigMap/kyverno/tenant-signers` in `infrastructure/gitops/infrastructure/kyverno/tenant-signers.yaml`. Parse the tenant JSON entry. Require namespace signer issuer and subject regex to equal the ConfigMap values; require issuer `https://token.actions.githubusercontent.com`, nonempty anchored valid regex and a full match of the prospective exact subject. This checks agreement and acceptance, not the global least privilege of an existing tenant regex. Preserve existing admission/security tests; do not implement a new RE2 parser.

## Parsing, output and boundaries

Every YAML/JSON document newly parsed for this command rejects duplicate mapping keys, including nested keys and embedded JSON; JSON rejects nonstandard NaN/Infinity constants. Use a local SafeLoader subclass and JSON `object_pairs_hook`; reject YAML merge keys rather than accepting ambiguous merged duplicate semantics. Validate mapping/list/string shapes before use and distinguish missing from duplicate/ambiguous selectors. Pre-parse source manifest and deploy YAML strictly before calling existing layout helpers; do not change global loaders or SDK behavior.

Return one JSON object to stdout on success or validation failure: `{schemaVersion, scope, ok, receipt, errors}`. Each error has stable `code`, `path` and bounded `message`. Exit 0 only with no errors; exit 1 for input/check failures. Argparse usage errors retain exit 2. Convert filesystem, parsing, git and regex exceptions to input errors without traceback or raw file/token content. Git subprocesses are read-only argument arrays with timeout and no shell. Do not accept credentials, access the network, write artifacts, mutate tags/workflows, compile a pretend release, approve releases, or run live/platform qualifications.

## Existing code to reuse

- `tools/zetra_agents/layout.py`: `find`, `AgentDir` accessors and `check`.
- `tools/zetra_agents/cli.py`: global repository handling and argparse patterns.
- Kubani `tests/test_db_admin_release.py`: reservation-versus-both-budgets algorithm.
- Kubani `tests/test_db_admin_gateway.py`: paired pin equality/exact prospective identity examples.
- Kubani `tests/test_tenant_signers.py`: existing soundness/admission coverage remains authoritative.
- `scripts/release.sh` identity convention remains unchanged. Its generated local signer regex does not substitute for checking the two candidate GitOps declarations.

No changes to `release.build`, signing, runtime agents, SDK dependencies, `.github/workflows/release.yml`, or conformance fixtures.

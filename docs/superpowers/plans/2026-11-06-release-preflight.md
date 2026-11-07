# Offline Release Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Check selected-agent source against candidate desired Kubani GitOps before creating a release tag, with a locally bound JSON receipt.

**Architecture:** A pure read-only compatibility module reads two explicit local checkouts; the existing tools CLI provides the entry point. Source and candidate capabilities must agree, budgets must admit APS reservations, and both signer pins must accept the prospective workflow identity. No live state is involved.

**Tech Stack:** Python 3.12, existing argparse/PyYAML/pytest dependencies, standard JSON/hashlib/subprocess; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-06-release-preflight.md`

## Global Constraints

- Candidate desired GitOps is not applied live state.
- Selected agent only; preserve all conformance fixture exceptions and security checks.
- No network, credentials, tag/workflow mutation, release approval or platform qualification.
- Newly parsed YAML/JSON rejects duplicate keys; no SDK or tool parsing duplication.
- Preserve existing CLI commands and `just check` expectations.

## Review Focus

- Duplicate keys and multiple resource/env matches fail before choosing arbitrary data.
- Dirty candidate worktrees remain reviewable through hashes; dirty source cannot describe a future HEAD tag faithfully.
- Missing or divergent local main refs remain informational; a local-only receipt never proves remote freshness.
- Source/candidate MCP or model capability drift fails even when budgets pass.
- Malformed or mismatched signer pins fail without leaking raw document contents.

---

### Task 1: Implement and expose the offline compatibility check

**Files:**
- Create: `tools/zetra_agents/preflight.py` — strict local parsing, checkout receipt, selected-resource validation and compatibility checks.
- Modify: `tools/zetra_agents/cli.py` — add `preflight` parser and JSON dispatch before existing release-only path.
- Create: `tools/tests/test_preflight.py` — temporary two-repository fixtures and CLI assertions.
- Modify: `README.md` — pre-tag command, candidate-versus-live scope, update-main/re-run instructions and receipt semantics.

**Interfaces:**
- Consumes `layout.find(repo: Path, name: str) -> AgentDir`, `layout.check(agent: AgentDir) -> list[str]`.
- Produces `preflight.check(repo: Path, kubani: Path, agent: str, tag: str) -> dict[str, Any]`, returning the spec's JSON object without printing or mutation. Helpers remain private.
- CLI prints `json.dumps(result, sort_keys=True)` and returns `0 if result['ok'] else 1`.

- [x] **Step 1: Write focused failing tests** in `tools/tests/test_preflight.py`. Build small temporary git repositories with main refs and candidate files, not copies of production source trees. Use the real `layout.check` in small valid selected-agent fixtures to prove dispatch/reuse. Give the candidate `131072` reservation, source/candidate `200000` session and `1000000` day budgets. Assert these named cases:
  - `test_cli_preflight_success_receipt`: exit 0, parsed JSON scope/version, both HEADs, exact prospective subject, dirty flags and independently computed SHA-256 hashes; no files/tags changed.
  - `test_source_candidate_capability_drift`: parameterize MCP tools/effect/delegation, model name, backend and budget changes; exit 1 with a field-path error and no raw source dump.
  - `test_reservation_budget_boundaries`: both budgets equal `131072` pass; either `131071` fails; `100000` session fails; unknown backend, missing catalogue, zero/negative/noninteger/boolean values fail.
  - `test_signer_pin_failures`: issuer/regex disagreements, wrong issuer, empty/unanchored/invalid regex, rejected subject, wrong agent prefix, branch-looking tag and empty version all fail; valid multi-agent anchored pin accepts exact selected identity.
  - `test_strict_input_rejections`: duplicate nested YAML keys in each newly read YAML class, duplicate embedded JSON keys in catalogue/pin, YAML merge key, malformed JSON/YAML, wrong shapes, missing file and duplicate/missing matching Agent/Deployment/container/env/Namespace/ConfigMap produce bounded structured errors rather than traceback.
  - `test_checkout_binding`: candidate differs from main but descends from it and has dirty capabilities matching source: pass with hashes/dirty true; dirty source fails; existing local tag fails; missing git/HEAD and git timeout fail structurally; missing main ref and locally behind/diverged HEAD pass with informational metadata. Successful receipt captures the selected local base refs. No remote operations occur.
  - `test_selected_agent_only_and_layout_failure`: unrelated underbudget conformance declarations do not affect the selected agent; selected `layout.check` problems become structured errors.
  - `test_no_side_effects_and_cli_regressions`: patch mutating/network subprocesses to reject use, assert git argument allowlist/timeouts/no shell, and existing `check`, `list`, `release` tests retain their behavior.

- [x] **Step 2: Run** `uv run --project tools --locked pytest tools/tests/test_preflight.py -q`; expect failure because the command/module does not exist.
- [x] **Step 3: Implement** `preflight.check(...)` with private strict-load/selector/git/error helpers and the exact selectors/receipt contract in the spec. Perform strict pre-parsing before existing layout accessors. Stop dependent checks after malformed inputs while retaining independent actionable errors. Add the parser/dispatch and README usage. Do not modify release generation or workflows.
- [x] **Step 4: Run** `uv run --project tools --locked pytest tools/tests/test_preflight.py -q`; expect all focused cases to pass. Run repository-required `just check` once (it includes `check-tools`); expect successful existing lint/layout/test suites without changing fixtures. Investigate failures rather than weakening existing tests.
- [x] **Step 5: Review** the diff against the spec: explicit candidate terminology, input hashes, both budget fields, both pin declarations, structured failures and zero live operations. Commit only the module, CLI, tests, README and reviewed design/plan documents with `feat: add offline release compatibility preflight`.

## Handoff

Implementation completed for root's independent review. Main ancestry was amended to informational metadata before implementation, as directed by root.

Verification evidence (local logs under `/tmp`, not release artifacts):
- Initial 59 focused tests failed because the CLI command was absent; successive green run reached 74 cases. One additional strict-JSON NaN test failed before its fix.
- Final tools suite: 108 passed, including 75 preflight cases. Lint and formatting passed.
- The first `just check` attempt stopped during editable build because hatchling could not be fetched (DNS). Reused isolated copies of existing locked environments, adjusting editable paths/shebangs to this checkout and setting `UV_NO_SYNC=1`.
- Required `just check` then exercised all projects: 290 passed, 4 existing local-socket tests failed with sandbox `PermissionError`; zero skips. Each of those four passed on a targeted rerun with local socket access (conformance and conformance-b refused-port tests, transport wrong-CA and disabled-verification tests). The final added tools case makes 295 distinct passing tests across these runs. This is not a claim of one fully green `just check` invocation.
- Existing `just check` shell loop masks earlier agent recipe failures if the final agent succeeds; observed follow-up only, no justfile change.
- Logs: `/tmp/agent-preflight-red.log`, `/tmp/agent-preflight-red2.log`, `/tmp/agent-preflight-json-red.log`, `/tmp/agent-preflight-tools-final.log`, `/tmp/agent-preflight-just-check.log`, `/tmp/agent-preflight-just-check-reused-env.log`, and `/tmp/agent-preflight-*-socket-tests.log`.
- Verified Python imports resolve `cli.py` and `preflight.py` from `/tmp/agent-preflight/tools/zetra_agents`.

No live operations, workflow changes, tagging, publishing, pushes or dependency changes. Root reviews before PR creation.

# T17 fail-closed implementation plan

> **For agentic workers:** use superpowers:executing-plans to implement this plan task by task.

**Goal:** Qualify APS unavailability against real gateway traffic at five requests per second.

**Architecture:** A signed conformance-b tool schedules bounded, independent requests and writes token-free evidence to its accepted workspace. A read-only harness observes Kubernetes state and correlates every request with gateway access logs. Operator-written ConfigMap receipts identify exact scale request start/ack times and Deployment UID/resourceVersion; the harness never changes replicas or Flux.

**Tech stack:** Python, Temporal, Kubernetes API, HTTPX.

**Spec:** Kubani agent-runtime-platform-spec.md section 15 T17 and section 3.7.

## Constraints and review focus

- One pinned agent token, lifetime longer than the probe plus 15 seconds; duration 60–240 seconds.
- Exactly five starts per second; missing requests, transport failures, duplicate logs and scheduling gaps cannot pass.
- Every request starting at least one second after the operator's scale-down request and before scale-up must be HTTP 403, including Pod shutdown.
- Actual zero Pods and empty ready/not-ready Endpoints, followed by two new Ready Pod UIDs and matching Endpoints, must be observed.
- The final Deployment specification and UID must match the original; its resourceVersion changes are tied to operator receipts.
- Cancellation retains normal confirmed session cleanup; no live mutation or status fabrication.

## Steps

- [x] Write failing fixture tests for absolute scheduling, one token, failures and bounded input. Implement the tool, manifest and compact workspace evidence.
- [x] Write failing evaluator tests for every missing/extra/timing/state/receipt failure. Implement bounded archive extraction and exact gateway correlation.
- [x] Write adapter tests for read-only observation, explicit operator phases and cancellation cleanup. Integrate opt-in T17 arguments.
- [x] Document exact RBAC, ConfigMap receipt schema and operator sequence. Run full runner/agent checks and request independent review before PRs.

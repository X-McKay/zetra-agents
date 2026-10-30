#!/usr/bin/env bash
# Build, push, sign and attest one agent image, then write its release artifacts
# (spec 14.1). Used by .github/workflows/release.yml and by `just release` on a host
# that can reach the registry.
#
# Environment:
#   COSIGN_KEY           required; a key file path or env://COSIGN_PRIVATE_KEY
#   COSIGN_PASSWORD      the key's password (cosign reads it from the environment)
#   COSIGN_PUBLIC_KEY    optional; when set, the signature and attestation are verified
#   COSIGN_TLOG_UPLOAD   default false; must match how Kubani's Kyverno Rule 1 verifies
#   AGENT_REGISTRY       default registry.almckay.io/agents (what admission accepts)
#   REVISION             default: git HEAD
#   OUT                  default: dist/<agent>
set -euo pipefail

agent=${1:?usage: release.sh <agent>}
root=$(git rev-parse --show-toplevel)
cd "$root"
registry=${AGENT_REGISTRY:-registry.almckay.io/agents}
revision=${REVISION:-$(git rev-parse HEAD)}
out=${OUT:-dist/$agent}
tlog=${COSIGN_TLOG_UPLOAD:-false}
predicate_type=https://agentplatform.io/attestations/release/v1
: "${COSIGN_KEY:?COSIGN_KEY is required}"

if [[ -n "$(git status --porcelain -- "agents/$agent")" ]]; then
  echo "agents/$agent has uncommitted changes; a release must be a commit" >&2
  exit 1
fi

tools() { uv run --project tools --locked zetra-agents "$@"; }
tools check "$agent"

tag="$registry/$agent:${revision:0:12}"
docker build --pull --platform linux/amd64 \
  --label "org.opencontainers.image.revision=$revision" \
  --label "org.opencontainers.image.source=https://github.com/X-McKay/zetra-agents" \
  -t "$tag" "agents/$agent"
docker push "$tag"
image=$(docker inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$tag" \
  | grep -m1 "^$registry/$agent@sha256:")
echo "pushed $image"

tools release "$agent" --image "$image" --revision "$revision" --out "$out"

cosign sign --yes --key "$COSIGN_KEY" --tlog-upload="$tlog" "$image"
cosign attest --yes --key "$COSIGN_KEY" --tlog-upload="$tlog" \
  --type "$predicate_type" --predicate "$out/predicate.json" "$image"

if [[ -n "${COSIGN_PUBLIC_KEY:-}" ]]; then
  ignore=()
  [[ "$tlog" == "true" ]] || ignore=(--insecure-ignore-tlog)
  cosign verify --key "$COSIGN_PUBLIC_KEY" "${ignore[@]}" "$image" >/dev/null
  cosign verify-attestation --key "$COSIGN_PUBLIC_KEY" "${ignore[@]}" \
    --type "$predicate_type" "$image" >/dev/null
  echo "verified signature and attestation"
fi

echo "$image" > "$out/image"
echo "release artifacts in $out"

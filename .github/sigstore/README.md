# Private Sigstore trust roots

Public keys and the root certificate of Kubani's private Sigstore. `scripts/release.sh`
signs and attests against `https://fulcio.almckay.io` and `https://rekor.almckay.io`
with these, and verifies its own output with them. Nothing here trusts public Sigstore.

Copied byte for byte from Kubani `main`
`infrastructure/gitops/infrastructure/kyverno/private-sigstore.yaml` (the ConfigMap
Kyverno Rule 1 verifies with), at 1f0c3935:

| File | ConfigMap key | SHA-256 of the file |
| --- | --- | --- |
| `fulcio-roots.pem` | `fulcio-roots.pem` | `f53085b4835e0b9c2e596a83b3ade17e998498e9f6792299c9aebc38b9aaaf7b` |
| `rekor.pub` | `rekor.pub` | `39b690130348c161a2406c3f1946cda471ac12a09c662f2145dd4f026057a036` |
| `ctlog.pub` | `ctlog.pub` | `abcdca33e3235a699acc01ed26833b235ec6f2baedda16936481a305ef5e8955` |

The Fulcio root is "kubani private Sigstore Fulcio root", valid to 2031-11-01, SHA-256
fingerprint `7A:2B:2F:90:D2:95:C8:1F:A2:CC:BF:7F:36:7A:FF:D9:F8:E1:F9:07:E2:2B:4E:52:57:E0:30:EB:95:60:65:29`.

When Kubani rotates a root or a log key it changes that ConfigMap; copy the new values
here in the same change window, or releases stop verifying. A change to these files is
a change of who this repository trusts, so it gets the same review as a Kubani change
to `tenant-signers.yaml`.

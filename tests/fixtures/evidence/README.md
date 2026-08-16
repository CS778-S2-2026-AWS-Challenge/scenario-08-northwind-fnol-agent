# Evidence Lifecycle Fixtures

`evidence-lifecycle.json` is a synthetic, reusable catalogue of the five Sprint
2 evidence entry states. Each case records its source through the domain
`EvidenceRecord`, plus explicit visibility, the next requirement, and the
expected state after that requirement is satisfied.

`pending` means an upload is already in flight (`incomplete` with a pending file
state). `not_yet_generated` means the external document does not exist yet
(`pending_generation` with no available file). Keeping these cases separate
prevents an unavailable document from being mistaken for a failed upload.

Validate the catalogue from the repository root with:

```powershell
py -3.12 scripts/run_evidence_fixtures.py
```

The catalogue defines lifecycle data only. Business-path entry scenarios and
claimant/internal visibility projection tests belong to the separate scenario
fixture work.

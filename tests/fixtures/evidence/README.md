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

## Path entry and visibility fixtures

`path-entry-visibility.json` defines complete effective evidence sets for the fast,
professional-review, urgent, human-request, and pending-evidence paths. Each
entry references the canonical catalogue in `backend/demo_data/scenarios` by
`scenario_id`; the loader derives the claim identifier, non-evidence Claim State,
customer next step, and evidence claim links from that record. It then derives
the effective Evidence State and Evidence Summary from the entry's complete
evidence set using the same precedence as the runtime evidence service. The
fixture source must not copy those derived fields, so scenario-facing state has
one runtime source and cannot contradict its evidence records.

Evidence is labelled `claimant_visible`, `shared`, or `internal_only`. The
claimant fixture projection includes the first two classes, removes internal
provenance, and always excludes internal-only evidence. Validate all five path
entries with:

```powershell
py -3.12 scripts/run_evidence_visibility_fixtures.py
```

## The shared evidence fixture service

`backend/services/evidence_fixtures.py` is the one place a business path asks
for evidence fixtures. It loads the lifecycle catalogue and the path entries,
and resolves every record through the single domain rule in
`backend/domain/evidence.py`, so no path can carry a private mapping from
status and file status to a lifecycle stage.

Validate all five business paths through the one service with:

```powershell
py -3.12 scripts/run_evidence_paths.py
```

### Entry stages and the conflict state

`lifecycle_stage_for()` answers for the five **entry** stages an evidence item
can start in. `inconsistent` is deliberately not one of them: it is reached
after two settled records disagree on a material fact, so it is a conflict
rather than an entry.

`is_registered_evidence_shape()` is the wider check used when sweeping
fixtures. It accepts the five entry stages plus a conflict on a `ready` file.

A conflict is established by comparing settled evidence, so `inconsistent` is
registered only with `ready`. The pending file states are rejected because
nothing has settled yet, and `failed` and `not_available` are rejected because
a file that never arrived, or never will, cannot be the thing another record
disagrees with.

`test_evidence_fixture_service.py` sweeps every evidence record in
`backend/demo_data/scenarios`, `tests/fixtures/professional_review`, the
lifecycle catalogue, and the path entries. Parsing already forces the domain
`EvidenceRecord`, so a private model fails at load; the sweep adds the subtler
check that no path invents an unregistered status and file-status combination.

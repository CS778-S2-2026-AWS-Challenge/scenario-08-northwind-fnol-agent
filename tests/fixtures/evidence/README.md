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

`path-entry-visibility.json` records the current clear, pending, urgent,
professional-review, and handoff entry baselines, and classifies the complete
canonical evidence set for each path. It does **not** own a second copy of any
`EvidenceRecord` or `HandoffRecord`.

Each entry names a canonical scenario in `backend/demo_data/scenarios`. Its
entry baseline records the expected workflow, Agent action, evidence state,
claimant status and responsibility, plus the bounded handoff shape when one is
required. Each visibility item stores only:

- a fixture/classification id;
- one visibility value (`claimant_visible`, `shared`, or `internal_only`);
- the canonical `evidence_id` it classifies.

`load_evidence_path_fixtures()` resolves the actual evidence and handoff payloads
from the canonical scenario. The loader rejects embedded evidence payloads,
unknown references, duplicate references, incomplete classifications, and a
scenario that drifts from its recorded entry baseline. Claim id, Claim State,
Evidence Summary, customer next step, and handoffs are projected from the
canonical scenario.

The fixture owns only entry expectations and visibility classifications.
Evidence and handoff values, source, lifecycle state, provenance, timing, and
relationship data remain owned by the canonical scenario.

The claimant fixture projection includes `claimant_visible` and `shared`, strips
internal provenance, and excludes `internal_only` evidence. Validate all five
path entries and print their workflow, action, evidence, and handoff baselines
with:

```powershell
py -3.12 scripts/run_evidence_visibility_fixtures.py
```

The live cross-check is stricter:

```powershell
py -3.12 scripts/run_evidence_path_defects.py
```

It seeds the canonical scenarios and compares the declared visibility with the
actual claimant and Workbench projections. The expected result is zero defects.

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
lifecycle catalogue, and the resolved path entries. Parsing already forces the
domain `EvidenceRecord`; the path loader additionally proves each entry points
back to the canonical record rather than a private copy.

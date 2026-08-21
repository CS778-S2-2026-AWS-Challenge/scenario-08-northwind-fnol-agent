# Day 4 evidence state and visibility check

Issue: #140

This is the `bdfa123` Day 4 check: compare the evidence state and visibility
each business path *declares* against what the runtime API actually projects to
a claimant and to staff, and record every difference with its owner.

The original check found one runtime claimant-visibility defect and a separate
fixture-to-scenario anchoring defect across all five paths. The runtime visibility
defect was resolved by Issue #219; the fixture anchoring defect remains open.

## Current status

- `PATH_FIXTURE_NOT_ANCHORED`: still open across all five paths.
- `INTERNAL_EVIDENCE_VISIBLE_TO_CLAIMANT`: resolved by Issue #219.

`tests/test_evidence_visibility_check.py` pins only the defect set that still
reproduces. A fixed defect is removed from that set in the same change that
updates this record.

## How to reproduce

```powershell
py -3.12 scripts/run_evidence_path_defects.py
```

The script seeds each canonical scenario named by
`tests/fixtures/evidence/path-entry-visibility.json`, calls
`GET /api/v1/claims/{claim_id}/evidence` as a claimant and
`GET /api/v1/workbench/claims/{claim_id}` as staff, and compares both against
the declared set. It exits non-zero while any defect is open.

## Why the existing verifiers did not catch these

`run_evidence_fixtures.py` and `run_evidence_visibility_fixtures.py` each check
a fixture family against its own schema. A fixture can satisfy its schema
completely while describing evidence the runtime has never held. This check is
the first one that compares a fixture against a live projection.

## Defect 1 — the path entries are not anchored to their scenarios

**Paths:** all five. **Code:** `PATH_FIXTURE_NOT_ANCHORED`.
**Responsible stack:** evidence fixtures — `bdfa123`.

`path-entry-visibility.json` states that each entry's evidence list is "the
complete effective evidence set" for the canonical scenario it names by
`scenario_id`. It is not.

| Path | Scenario | Scenario holds | Entry declares |
| --- | --- | --- | --- |
| fast | AT-01-clear-motor | *no evidence* | `evd_fixture_path_fast_image` |
| professional_review | AT-02-coverage-ambiguity | *no evidence* | `evd_fixture_path_review_shared`, `evd_fixture_path_review_internal` |
| urgent | AT-04-urgent | *no evidence* | `evd_fixture_path_urgent_image` |
| human_request | AT-05-human-request | *no evidence* | `evd_fixture_path_human_image` |
| pending_evidence | AT-06-pending-evidence | `evd_fixture_at06_police`, `evd_fixture_at06_agency`, `evd_fixture_at06_internal` | `evd_fixture_path_pending_report` |

Every declared `evd_fixture_path_*` identifier exists only inside the path
fixture. Four of the five referenced scenarios carry no evidence at all, and the
fifth carries three records, none of which the entry mentions.

The entry-level derivation added for Issue #110 works — the loader does derive
claim id, claim state, and next step from the canonical scenario, and refuses to
let the fixture restate them. Evidence was left outside that rule, so the one
field the fixture is *about* is the one it may still invent.

**Expected:** an entry describes the evidence of the scenario it names.
**Actual:** an entry describes an independent invented set.

Fixing it is a choice between two directions, which is why this is recorded
rather than patched: either the entries derive their evidence from the scenario
the way they already derive claim state, or the canonical scenarios gain the
evidence the paths are supposed to demonstrate. The second is the larger change
and affects everyone's scenario expectations.

## Defect 2 — claimant evidence list returned internal records — resolved by #219

**Path:** pending_evidence / AT-06-pending-evidence.
**Code:** `INTERNAL_EVIDENCE_VISIBLE_TO_CLAIMANT`.
**Original responsible stack:** evidence API and claimant projection.
**Status:** resolved by Issue #219.

At the time of the Day 4 check, `GET /api/v1/claims/{claim_id}/evidence`
returned every persisted record on the claim. For AT-06 the claimant received:

| Evidence | Kind | Source |
| --- | --- | --- |
| `evd_fixture_at06_police` | `police_report` | `claimant` |
| `evd_fixture_at06_agency` | `agency_incident_record` | `external_system` |
| `evd_fixture_at06_internal` | `internal_policy_history` | `staff` |

The last two were records the claimant never provided and could not act on. The
third is an internal Northwind archive lookup. Internal provenance was already
stripped, so the primary defect was the record-level projection boundary.

A stricter review of the same boundary found a related aggregate leak: the
claimant claim projection returned the authoritative internal `evidence_summary`
computed from all three records. Filtering only the list would therefore have
left a contradictory side channel — one visible evidence item but a claimant
summary reporting three pending items.

### Resolution

Issue #219 centralises the existing safe default in
`backend/services/evidence_visibility.py`:

```python
claimant source -> shared
non-claimant source -> internal_only
```

That policy is applied below HTTP routing in the evidence service, so direct
service callers receive the claimant-safe record set rather than relying on a
single route handler to remember the filter. The same policy remains the source
for handoff visibility through `default_handoff_visibility()`.

The claimant claim projection derives its `evidence_summary` from the same
visible record set. Under the current safe default, AT-06 therefore presents:

- claimant evidence list: only `evd_fixture_at06_police`;
- claimant `evidence_summary.pending`: `1`;
- Workbench evidence list: all three records;
- internal / staff `evidence_summary.pending`: `3`.

`tests/test_claimant_evidence_visibility_regression.py` directly verifies both
record and aggregate boundaries. `tests/test_day3_scenarios.py` now expects the
claimant-safe aggregate while preserving the authoritative internal count, and
`tests/test_evidence_visibility_check.py` asserts that
`INTERNAL_EVIDENCE_VISIBLE_TO_CLAIMANT` no longer reproduces.

This resolution deliberately does not change evidence persistence, lifecycle
state, canonical fixture data, or staff access.

### Longer-term policy boundary

The current rule is a safe MVP default, not an assertion that source and
visibility must always be identical in production. A later product decision may
introduce an explicit `claimant_visible` class or a richer rule for authorised
external-agency evidence. If that happens, it must replace the shared rule
across claimant projection and handoff consumers together rather than diverging
in a single endpoint.

## Not defects

- **Staff projection.** The Workbench returns every persisted record on every
  path, which is correct; staff are entitled to the full set.
- **Internal provenance.** Never present in a claimant response on any path.
- **Authoritative internal aggregate.** The persisted claim summary continues to
  reflect the full evidence set for internal workflow and staff operations; only
  the claimant projection is narrowed.
- **Derived state.** Evidence state and summary recompute correctly from the
  records on every path, checked by Issue #139's service.

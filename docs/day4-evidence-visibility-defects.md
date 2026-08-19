# Day 4 evidence state and visibility check

Issue: #140

This is the `bdfa123` Day 4 check: compare the evidence state and visibility
each business path *declares* against what the runtime API actually projects to
a claimant and to staff, and record every difference with its owner.

Nothing here is fixed in fixture data. Two of the findings are fixture problems
and one is not, and editing the fixture would have hidden the one that matters.

## How to reproduce

```powershell
py -3.12 scripts/run_evidence_path_defects.py
```

The script seeds each canonical scenario named by
`tests/fixtures/evidence/path-entry-visibility.json`, calls
`GET /api/v1/claims/{claim_id}/evidence` as a claimant and
`GET /api/v1/workbench/claims/{claim_id}` as staff, and compares both against
the declared set. It exits non-zero while any defect is open.

`tests/test_evidence_visibility_check.py` pins the recorded set. It fails if a
new defect appears **and** if a recorded one stops reproducing, so this document
cannot drift away from the code in either direction.

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

## Defect 2 — the claimant evidence list returns internal records

**Path:** pending_evidence / AT-06-pending-evidence.
**Code:** `INTERNAL_EVIDENCE_VISIBLE_TO_CLAIMANT`.
**Responsible stack:** evidence API and domain model — `liyang6620`, `bdfa123`.
**This one is not a fixture problem and must not be fixed in fixture data.**

`GET /api/v1/claims/{claim_id}/evidence` returns every persisted record on the
claim. For AT-06 the claimant receives:

| Evidence | Kind | Source |
| --- | --- | --- |
| `evd_fixture_at06_police` | `police_report` | `claimant` |
| `evd_fixture_at06_agency` | `agency_incident_record` | `external_system` |
| `evd_fixture_at06_internal` | `internal_policy_history` | `staff` |

The last two are records the claimant never provided and cannot act on. The
third is an internal Northwind archive lookup.

Internal **provenance** is correctly stripped — `internal_note` does not appear
in the response — so the field-level boundary added for Issue #110 works. The
gap is at record level: `EvidenceRecord` has no visibility field, so
`_claimant_evidence` has nothing to filter on and the claimant projection cannot
be narrower than the full list.

`tests/fixtures/evidence/README.md` already states the intended rule: the
claimant projection "includes the first two classes, removes internal
provenance, and always excludes internal-only evidence." The fixture layer
implements it with `FixtureVisibility`. The runtime has no equivalent.

**Expected:** the claimant evidence list excludes records the claimant did not
provide and cannot act on.
**Actual:** it returns all three, including a staff-sourced internal record.

This needs a domain decision before code: whether visibility is an explicit
field on `EvidenceRecord`, or derived from `source`. Deriving from `source`
would be smaller but would permanently couple "who supplied it" to "who may see
it", which is not obviously true for an external record a claimant is waiting
on. Recorded for the owning stacks rather than decided here.

## Not defects

- **Staff projection.** The Workbench returns every persisted record on every
  path, which is correct; staff are entitled to the full set.
- **Internal provenance.** Never present in a claimant response on any path.
- **Derived state.** Evidence state and summary recompute correctly from the
  records on every path, checked by Issue #139's service.

# Day 4 canonical scenario validation

Issue: #271

## Scope

This record validates the five canonical MVP business paths — clear, pending, urgent,
professional review, and claimant-requested handoff — on `main` at
`dfd0b722`, which is the merge of #312 and therefore the first commit where every MVP path
carries an explicit `business_path` assignment.

Each path is checked independently: a fresh fixture repository is seeded from the canonical
scenario, then the same claim is read through the public claimant API and the authorised
Workbench API and the two projections are compared. All claim data, evidence, retrievals,
messages, and handoffs are synthetic.

The check covers fixture anchoring, staff completeness, and the claimant/staff visibility
boundary. It does not cover live provider behaviour, and no result here is evidence of a
production integration.

## Repeatable checks

Any team member can repeat the whole record with three commands from the repository root:

```text
python scripts/run_evidence_visibility_fixtures.py
python scripts/run_evidence_path_defects.py
python scripts/run_canonical_path_validation.py
```

The first two already existed. The third was added for this issue because neither existing
runner compares the claimant and staff projections of the same claim, which is the specific
acceptance criterion here.

Environment for the recorded run: Python 3.12.10 on a clean Windows clone, backend composed
in explicit developer identity mode (`environment=test`, `identity_mode=developer`), fixture
repository, no external provider.

## Result matrix

`run_canonical_path_validation.py` on `dfd0b722`:

| Scenario | Business path | Claimant / staff evidence | Staff retrievals / handoffs | Own / internal ids |
| --- | --- | --- | --- | --- |
| `AT-01-clear-motor` | clear | 1 / 1 | 0 / 0 | 0 / 0 |
| `AT-06-pending-evidence` | pending | 1 / 3 | 0 / 0 | 0 / 0 |
| `AT-04-urgent` | urgent | 1 / 1 | 0 / 1 | 1 / 0 |
| `AT-02-coverage-ambiguity` | professional_review | 3 / 3 | 2 / 1 | 0 / 5 |
| `AT-05-human-request` | handoff | 1 / 1 | 0 / 1 | 1 / 0 |

Checked 5 business paths. No projection defects: staff see the complete canonical evidence set
on every path, and no internal identifier reaches the claimant.

`run_evidence_visibility_fixtures.py` on the same commit reports PASS for all five paths with
the declared entry baselines, and `run_evidence_path_defects.py` reports no evidence-path
defects across the same five paths.

## State and visibility findings

**Fixtures stay anchored to canonical scenarios.** Staff evidence count equals the canonical
scenario evidence count on every path, so no projection recreates or drops records.

**Claimant evidence is a bounded subset, not a copy.** `AT-06-pending-evidence` is the clearest
case: staff see three evidence records while the claimant sees one, because the two
pending-generation records are not claimant-visible. `AT-02-coverage-ambiguity` is the opposite
and equally correct: all three records are claimant-visible there, so both projections show
three.

**The handoff boundary is asymmetric by design, and the asymmetry is the point.** A handoff
carrying no `support_need` is internal routing and must never reach the claimant; a handoff the
claimant asked for is projected through `ClaimantHandoff`, which deliberately exposes its
identifier along with status, priority, and the promised next step.

`AT-02` exercises the internal case — its `professional_review` handoff has `support_need: null`
and its identifier does not appear in any claimant response, even though staff see the handoff
and both policy and claim-history retrievals. `AT-04` and `AT-05` exercise the claimant-requested
case, and in each the claimant can see their own support request. `claimant_handoff()` enforces
this by raising rather than projecting an internal handoff, so the distinction is a code
boundary and not a fixture convention.

An initial version of the validation script treated every handoff identifier as internal and
reported `AT-04` and `AT-05` as leaks. That was a defect in the check, not in the application;
the script now encodes the `support_need` rule and asserts both directions, so a future change
that hides a claimant's own support request also fails.

## Defect record

No defects found on the five canonical MVP paths at `dfd0b722`.

The validation script was confirmed to be load-bearing rather than vacuously passing: disabling
the internal-reference filter in the claimant form projection makes it fail with
`AT-02-coverage-ambiguity: internal identifiers reached the claimant: ['ret_fixture_at02_policy']`,
and restoring the filter returns it to a clean run.

One unrelated hazard found while auditing this area is filed separately as #356; it concerns
demo-seed scenario set overlap and does not affect any result recorded here.

## Boundaries and remaining limitations

- All records are synthetic. This validates projection and visibility boundaries against the
  fixture repository and proves nothing about a live provider, MongoDB, or MinIO.
- The check reads the claimant claim, evidence, and message routes and the Workbench claim
  detail. It does not exercise staff mutations, agent turns, resume, or handoff acceptance;
  those are covered by their own suites.
- Identifier leakage is detected by substring match over the serialised claimant responses.
  That is deliberately blunt: it catches an identifier appearing anywhere, including nested or
  newly added fields, but it cannot detect a leak that does not carry a known identifier.
- The recorded run uses explicit developer identity mode. Under the default normal mode the
  backend is fail-closed and these routes return 401, which is correct and is validated
  separately under #247.

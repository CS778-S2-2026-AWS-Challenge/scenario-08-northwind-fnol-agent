# Scenario evidence derivation guard

Issue: #140 (follow-up)

While working `PATH_FIXTURE_NOT_ANCHORED` from
`docs/day4-evidence-visibility-defects.md`, a second and previously unrecorded
class of drift turned up: **a canonical scenario could declare an evidence state
or summary that its own records could not produce.**

`EvidencePathEntry` has recomputed both from its records since Issue #110 and
rejected a mismatch. `ScenarioFixture` did not. It now does.

## What the guard found

Three scenarios were declaring evidence they did not hold.

| Scenario | Records held | Declared | Derived |
| --- | --- | --- | --- |
| `AT-02-coverage-ambiguity` | none | `needs_attention: 1` | `needs_attention: 0` |
| `AT-13-coverage-ambiguity` | none | `received`, `received: 1` | `not_started`, `received: 0` |
| `AT-14-history-signal` | none | `received`, `received: 1` | `not_started`, `received: 0` |

All three are reconciled to what their records actually support. AT-13 and
AT-14 demonstrate policy and history retrieval review; they carry retrievals,
not evidence, so `not_started` is the honest state for them.

## Why this matters for Defect 1

AT-02's declared `needs_attention: 1` is not random. That value is what
`evidence_summary_for` produces from exactly one `unofficial` record — and the
professional-review path entry declares exactly one such record,
`EV-VIS-02-review-shared-document`.

So the scenario's summary is corroborating evidence for what
`PATH_FIXTURE_NOT_ANCHORED` describes: **the path entry records were meant to
live in the canonical scenarios, and never got there.** The summary was written
as if they had.

That narrows the open question. Defect 1's fix is not a choice between two
equally plausible directions any more; the intended direction was for the
scenarios to hold this evidence.

## What is still open

Defect 1 itself. Moving the path entry records into `AT-01`, `AT-02`, `AT-04`,
and `AT-05`, and reducing the entries to the visibility classification they are
actually for, changes evidence counts and claim state on scenarios that other
people's tests assert against.

That migration is deliberately **not** done here. It is a shared-fixture change
landing on the last night of the sprint, and the dependent expectations belong
to other stacks. The guard added here makes the class of defect impossible to
reintroduce, and the three live inconsistencies are fixed; the migration should
be scheduled with the owners of the dependent scenario tests.

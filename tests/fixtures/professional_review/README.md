# Professional-review scenario fixtures

These synthetic scenarios cover the four repeatable review conditions required
by issue #130. Each fixture records the expected Agent action, evidence state,
review reason, and claimant/staff visibility outcome.

| Fixture | Review condition |
|---|---|
| `AT-13-coverage-ambiguity.json` | Policy wording requires professional interpretation |
| `AT-14-history-signal.json` | Relevant claim history requires a bounded staff review |
| `AT-15-conflicting-evidence.json` | Two received records disagree on a material fact |
| `AT-16-retrieval-unavailable.json` | A required provider is temporarily unavailable |

`tests/test_professional_review_scenarios.py` loads, seeds, and projects every
fixture without manual edits. Internal review reasons must remain visible to
staff but absent from claimant message responses.

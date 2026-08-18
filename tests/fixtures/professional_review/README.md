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

Policy and history scenarios use the provider-neutral retrieval records and
derived `ReviewSignalRecord` boundary established by issues #108 and #126.
Provider references, retrieval identifiers, uncertainty details, and review
signals remain outside Claim State and claimant responses. The generic
evidence-conflict scenario continues to use an internal-only message because
it does not originate from a policy or history retrieval. Exposing persisted
retrieval signals in the staff workbench remains the later #136 integration
boundary.

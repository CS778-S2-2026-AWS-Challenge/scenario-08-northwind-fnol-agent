# Day 5 Agent authority and visibility check

Issue: #148

This is the `bdfa123` third of Issue #148: run and check the ambiguity,
conflict, and visibility fixtures. `Ysoseri1224` checks the Agent authority
boundary and `LLL263` checks staff review actions and results.

## Demonstration

Run `tests/fixtures/presentation/test_agent_authority_and_visibility.py`. It is
parameterised over all four professional-review fixtures from Issue #130.

| Scenario | Condition | Next action | Coverage | Fraud signal |
| --- | --- | --- | --- | --- |
| AT-13-coverage-ambiguity | `COVERAGE_AMBIGUOUS` | `HANDOFF` | `ambiguous` | `none` |
| AT-14-history-signal | `RELEVANT_HISTORY_REVIEW` | `HANDOFF` | `not_assessed` | `none` |
| AT-15-conflicting-evidence | `EVIDENCE_CONFLICT` | `HANDOFF` | `review_required` | `none` |
| AT-16-retrieval-unavailable | `RETRIEVAL_UNAVAILABLE` | `HANDOFF` | `not_assessed` | `none` |

## Acceptance

**"The Agent does not make high-impact decisions outside its authority."**

The boundary shows in what these scenarios do *not* contain. Each one is a
situation where a system without a boundary would be tempted to resolve
something:

- coverage is never `clear` — it is either untouched or explicitly marked as
  needing a person;
- the fraud signal is `none` in all four, including the conflicting-evidence
  case, which is the one most likely to be mistaken for a fraud indicator;
- the workflow never reaches `created` and the next action is never
  `CREATE_CLAIM` from any of these states.

In every case the Agent's next action is to transfer to a person.

**"Staff can act and claimants cannot see internal signals."**

The claimant side asserts absence across the message list and the claim
projection together: the review reason code, every review signal's identifier,
summary, and reason codes, every retrieval identifier and provider reference,
and every handoff's reason codes, reason text, and requested action.

The staff side asserts the review reason reaches the Workbench — through a
persisted review signal for AT-13 and AT-14, and through the handoff reason
codes for AT-15 and AT-16 — and that the detail returns the same Claim State
dimensions the Agent reads, rather than a separate board record.

## Note on the two routes a reason travels

AT-13 and AT-14 carry their reason as a persisted `ReviewSignalRecord` derived
from retrieval uncertainty. AT-15 and AT-16 carry it on the handoff instead:
AT-15 because an evidence conflict does not originate from a retrieval, and
AT-16 because an unavailable provider produces no sourced record at all, per the
retrieval contract from Issue #124.

Both routes reach staff and neither reaches the claimant, which is what the
acceptance condition asks. It is recorded here because a reader checking only
for review signals would conclude, wrongly, that two of the four scenarios
never tell staff why review is required.

## Boundary

This third covers the fixtures and the two-sided visibility result. It does not
cover the Agent's runtime authority checks, which are `Ysoseri1224`'s part, or
staff review actions and their results, which are `LLL263`'s. Issue #148 stays
open until those land.

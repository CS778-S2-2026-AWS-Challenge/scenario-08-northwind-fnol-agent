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

## The reason travels three named routes

Corrected after review. An earlier version of this document said two routes and
the check allowed a repository-state fallback, which meant the assertion could
have passed while the Workbench exposed nothing. Reading the projection alone
showed there are three, and that AT-15 uses a route neither of the other two
does.

| Scenario | Route in the Workbench projection |
| --- | --- |
| AT-13-coverage-ambiguity | `signals[].reason_codes` |
| AT-14-history-signal | `signals[].reason_codes` |
| AT-15-conflicting-evidence | an `internal_only` message with `content.type: review_signal` |
| AT-16-retrieval-unavailable | `handoffs[].reason_codes` |

AT-13 and AT-14 derive a `ReviewSignalRecord` from retrieval uncertainty.
AT-16 has no sourced record to derive from — an unavailable provider produces
none under the Issue #124 contract — so its reason rides the handoff. AT-15 has
neither a retrieval nor, in the seeded state, a handoff, so it carries a
structured internal message instead.

The check now names the expected route per scenario and asserts the reason is
in that route **and only that route**, reading the response body rather than
repository state. A scenario that stops exposing its reason fails here instead
of passing because the string appears somewhere incidental in the response.

## Boundary

This third covers the fixtures and the two-sided visibility result. It does not
cover the Agent's runtime authority checks, which are `Ysoseri1224`'s part, or
staff review actions and their results, which are `LLL263`'s. Issue #148 stays
open until those land.

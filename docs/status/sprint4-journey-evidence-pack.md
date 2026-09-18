# Sprint 4 journey evidence pack

## Purpose and status

This status record states the Sprint 4 complete-journey evidence at one exact head, for the poster
and for Week 8 planning. It consolidates the 100-run baseline (#893, #927), the assessor failure
journeys (#933, #942), and the per-run metric coverage (#952), which were otherwise reported in
separate #771 comments on different heads.

Every count below comes from 105 records written by the merged runners at
`main@6fe149ecba9c95179fed8e895b68a460d0f53145` on 2026-09-18: 50 motor, 30 home, and 20 contents
baseline runs, and the five assessor failure journeys. The records are `northwind-journey-run/6`
and are kept outside the repository, as `tests/journey_runs/README.md` requires. This record creates
no contract and does not claim that any product-acceptance category is complete;
[the journey acceptance gap record](sprint4-journey-acceptance-gaps.md) maps the same runs to the
ten categories in #733.

To reproduce the counts on a given head:

```text
python -m tests.journey_runs --scenario motor --runs 50 --out <outside the repository>
python -m tests.journey_runs --scenario home --runs 30 --out <outside the repository>
python -m tests.journey_runs --scenario contents --runs 20 --out <outside the repository>
python -m tests.journey_runs --scenario motor-failures --runs 5 --out <outside the repository>
```

## Evidence level

Every record carries the same configuration: `runtime: fixture`, `provider_mode: simulated`,
`agent_runtime_profile: controlled`, and `model_profile_id: qwen-local`. The evidence is API
projections on the fixture runtime with simulated providers, read through the claimant, Workbench,
and integration routes.

Do not cite this record as any of the following:

- **Model-backed Agent behaviour.** The controlled profile applies fixed rules, and
  `docs/model-gateway.md` states that it "continues to use `ControlledAgent`".
- **AWS, live-provider, or production capability.** No provider is contacted; Definition of Done
  item 4 is not addressed.
- **Browser or user-experience evidence.** No claimant or Workbench screen was rendered.
- **Independent repetitions.** The controlled runtime is deterministic, so repeated runs of the same
  input and pack give the same result.
- **The Sprint 4 valid test benchmark.** `sprint/sprint4.md` section 2 asks for five metrics per
  run, and three of them cannot be measured here (see "Metric coverage").

## Scenario matrix

Each baseline run uses a distinct claimant input sequence with the complete material pack named
below. The motor packs are shared across the three motor scenarios.

| Family | Scenario | Material pack | Runs | Result class |
| --- | --- | --- | ---: | --- |
| Motor | AT-01 clear motor creation | `motor-collision-conflicting-v1` | 3 | `fixture-only` |
| Motor | AT-01 clear motor creation | `motor-collision-provisional-2` | 3 | `fixture-only` |
| Motor | AT-01 clear motor creation | `motor-collision-unreadable-v1` | 4 | `fixture-only` |
| Motor | AT-01 clear motor creation | `motor-collision-superseded-v1` | 3 | `partial` |
| Motor | AT-01 clear motor creation | `motor-collision-unavailable-v1` | 4 | `partial` |
| Motor | PRES-01 rear-end handoff | `motor-collision-conflicting-v1` | 3 | `partial` |
| Motor | PRES-01 rear-end handoff | `motor-collision-provisional-2` | 4 | `partial` |
| Motor | PRES-01 rear-end handoff | `motor-collision-superseded-v1` | 4 | `partial` |
| Motor | PRES-01 rear-end handoff | `motor-collision-unavailable-v1` | 3 | `partial` |
| Motor | PRES-01 rear-end handoff | `motor-collision-unreadable-v1` | 3 | `partial` |
| Motor | PRES-02 guided rear-end review | `motor-collision-conflicting-v1` | 4 | `partial` |
| Motor | PRES-02 guided rear-end review | `motor-collision-provisional-2` | 3 | `partial` |
| Motor | PRES-02 guided rear-end review | `motor-collision-superseded-v1` | 3 | `partial` |
| Motor | PRES-02 guided rear-end review | `motor-collision-unavailable-v1` | 3 | `partial` |
| Motor | PRES-02 guided rear-end review | `motor-collision-unreadable-v1` | 3 | `partial` |
| Home | Water ingress | `home-water-ingress-provisional-1` | 15 | `fixture-only` |
| Home | Water ingress, illegible note | `home-water-ingress-illegible-v1` | 15 | `fixture-only` |
| Contents | Damaged item | `contents-damaged-item-provisional-1` | 3 | `unavailable` |
| Contents | Damaged item, authority not held | `contents-damaged-item-authority-not-held-v1` | 4 | `unavailable` |
| Contents | Damaged item, conflicting ownership | `contents-damaged-item-conflicting-ownership-v1` | 3 | `unavailable` |
| Contents | Damaged item, expired valuation | `contents-damaged-item-expired-valuation-v1` | 3 | `unavailable` |
| Contents | Damaged item, illegible receipt | `contents-damaged-item-illegible-receipt-v1` | 3 | `unavailable` |
| Contents | Laptop theft | `contents-theft-laptop-v1` | 4 | `unavailable` |

The baseline uploaded 330 materials. It has no `failed` or `blocked` run and no `completed` run,
which the fixture runtime cannot produce.

## Result classes

| Set | Runs | Classes | Where the journeys end |
| --- | ---: | --- | --- |
| Motor | 50 | 10 `fixture-only`; 40 `partial` | AT-01: 13 at `assessor_result_under_review`, 4 at `assessor_assigned`. PRES-01: 17 at `human_support_queued`. PRES-02: 16 at `staff_update` |
| Home | 30 | 30 `fixture-only` | `claim_created`, owned by `system` |
| Contents | 20 | 20 `unavailable` | `more_information_needed`, owned by the `claimant` |
| Assessor failures | 5 | 3 `fixture-only`; 2 `partial` | See "Failure classification" |

A run is `partial` or `unavailable` for one of these recorded reasons:

| Runs | Family and packs | Recorded reason | Meaning |
| ---: | --- | --- | --- |
| 20 | PRES-01 and PRES-02 with the conflicting, provisional, or unreadable pack | Not delivered: `motor-consent-record.pdf`, `motor-assessment-v2.pdf` | The journey hands the Claim to staff before assessor consent, so the pack's assessor materials have a route that this journey never reaches |
| 7 | PRES-01 and PRES-02 with the superseded pack | No route in for `motor-assessment-v1.pdf`; not delivered: the consent record and `motor-assessment-v2.pdf` | As above, and the superseded assessment has no route at all |
| 3 | AT-01 with the superseded pack | No route in for `motor-assessment-v1.pdf` | Nothing in the system accepts a superseded assessment |
| 6 | PRES-01 and PRES-02 with the unavailable pack | No route in for `motor-assessment-unavailable-notice.pdf`; not delivered: the consent record | The assessor-unavailable notice has no route, and the journey ends before consent |
| 4 | AT-01 with the unavailable pack | No route in for `motor-assessment-unavailable-notice.pdf` | Nothing in the system accepts the notice |
| 16 | Contents, all packs except authority not held | Unavailable: contents item capture, needed to create the claim | Intake stops at `contents.items`, which the controlled runtime does not capture (Discussion #847) |
| 4 | Contents, authority not held | As above, and no route in for `contents-authority-outcome-not-held` | As above |

## Metric coverage

Each record states the five metrics in `sprint/sprint4.md` section 2 (#952). Coverage is identical
across all 105 records.

| Metric | State | What the records hold |
| --- | --- | --- |
| 1. Completed without follow-up (target 80% or more) | `not_measured` | Cites `docs/model-gateway.md`: a rule-driven Agent produces no judgement of its own to rate |
| 2. Blind severity classification | `not_measured` | Cites `docs/model-gateway.md`: with no configured model transport, no severity signal exists |
| 3. Fraud flag precision, no false positives | `not_measured` | Same limitation as metric 2 |
| 4. Claimant effort, under 5 minutes and under 10 questions | `partly_measured` | 1 to 7 claimant messages and 0 to 3 question marks in Agent replies per run, plus confirmations, uploads, and consents. The question-mark count is a lower bound. Elapsed claimant time has no served source; the documented metrics endpoint is not served (#953) |
| 5. Claim number, expected timeline, final state, evidence chain | `measured` | 52 of 105 records carry a claim number and expected timeline: all 17 AT-01 runs, all 30 home runs, and all 5 failure journeys. Every record carries its final state, next step, owner, and evidence count |

## Failure classification

Each failure journey drives AT-01 to assessor consent, routes the request against an adapter
scripted to fail one way, checks both ends before anyone recovers, and then recovers only through
the claimant's retry or the Workbench action the server projects (#933, #942). At the failure, all
four both-end checks agree in every case: who acts next, whether staff can find the work, whether
staff have a recovery action, and whether `can_request` matches what a resend does.

| Case | Failure | Routing response | Recovery | Class | Ends at |
| --- | --- | --- | --- | --- | --- |
| `retryable-unavailable` | Provider unavailable before submission | `503 DEPENDENCY_UNAVAILABLE` | Claimant retry `201`; result `201` | `fixture-only` | `assessor_result_under_review` |
| `terminal-access-denied` | Access denied | `502 DEPENDENCY_FAILED` | Resend refused `409`; staff accept the review `201` | `partial` (no assessment) | `assessor_request_under_review` |
| `terminal-not-required` | Unusable routing answer | `502 DEPENDENCY_FAILED` | Same as access denied | `partial` (no assessment) | `assessor_request_under_review` |
| `unknown-outcome` | Sent, answer lost | `409 INVALID_STATE_TRANSITION` | Resend refused `409`; staff reconcile `200`; result `201` | `fixture-only` | `assessor_result_under_review` |
| `interrupted-dispatch` | Process stops after reservation | `500 INTERNAL_ERROR` | Resend refused `409`; staff reconcile `200`; result `201` | `fixture-only` | `assessor_result_under_review` |

The claimant owns the retryable case and staff own the other four, matching the external-service
lifecycle registry after #942. Every journey ends with `claims_professional` as the next-step owner.

## Poster screenshot list

The poster needs the recorded states rendered in the claimant and Workbench applications. This
record does not provide the screenshots; each can be produced by driving the named journey in a
browser, and #964 tracks capturing them.

| Application | Screen | State to show | Journey that produces it |
| --- | --- | --- | --- |
| Claimant (@LLL263) | Assessor permission | `external_service_action.status` `consent_required` | AT-01 before consent |
| Claimant (@LLL263) | Request routed | `queued` or `assigned` | AT-01 after routing |
| Claimant (@LLL263) | Retry offered | `retryable_failure` with `can_request` true | `retryable-unavailable` |
| Claimant (@LLL263) | Northwind reviewing | `terminal_failure` | `terminal-access-denied` |
| Claimant (@LLL263) | Outcome not confirmed | `awaiting_reconciliation` | `unknown-outcome` |
| Claimant (@LLL263) | Claim created | Claim number and expected timeline | Home water ingress |
| Claimant (@LLL263) | More information needed | Intake stopped at `contents.items` | Any contents run |
| Claimant (@LLL263) | Human support queued | `human_support_queued` | PRES-01 |
| Workbench (@jxu316-arch) | Queue item | External wait and attention signals | `unknown-outcome` before reconciliation |
| Workbench (@jxu316-arch) | External-service records | Lifecycle row with pending owner and attention | Any failure journey |
| Workbench (@jxu316-arch) | Accept review | `external.accept_review` for a terminal failure | `terminal-access-denied` |
| Workbench (@jxu316-arch) | Reconcile | `external.reconcile_response` for an unknown outcome | `unknown-outcome` or `interrupted-dispatch` |
| Workbench (@jxu316-arch) | Missing information | Responsible party per item | Any failure journey |

## Week 8 gaps

| Gap | Effect on this evidence | Tracking | Owner |
| --- | --- | --- | --- |
| The journey runners cannot select the model-backed Agent runtime, and the journey environment has no model credential | Metrics 1 to 3 and real effort figures stay unmeasured; contents stays `unavailable` | #962 | @bdfa123 for the runners; @Ysoseri1224 for model access |
| Contents item capture needs the model-backed runtime | All 20 contents runs stop before claim creation | #962; Discussion #847 records that contents behaviour is model-backed, so contents is rerun on `model_gateway` | @bdfa123 for the runners; @Ysoseri1224 for model access |
| No served source for elapsed claimant time | Metric 4 stays `partly_measured` | #953 | @Ysoseri1224 |
| Real AWS access and calls | Definition of Done item 4 has no evidence | #786 | @liyang6620 |
| An `unknown_outcome` missing-information item names `external_party` while its lifecycle names `claims_professional` | One Workbench projection disagrees for the unknown-outcome case | Raised on #945 | @liyang6620 |
| Red tests on `main`: two `tests/test_backend_quality_profiles.py` cases and one `tests/test_demo_reset.py` case | Full-suite runs cannot be fully green | Reported on #903 and #915 | @Ysoseri1224, @liyang6620 |
| The atomic initial claimant bootstrap changes intake | Every journey start must be rerun after merge | #816 | @liyang6620 |
| Poster screenshots of the recorded states | Definition of Done item 6 lacks screens | #964, which captures the list above | @bdfa123; @LLL263 and @jxu316-arch confirm their screens |
| Ten rubric anchors with complete input, output, state, and metric evidence | Definition of Done item 2 is not started | #963 | @bdfa123 |

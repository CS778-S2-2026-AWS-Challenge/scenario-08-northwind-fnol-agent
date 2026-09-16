# Sprint 4 journey acceptance gap record

## Purpose and status

This status record maps the merged 100-run fixture baseline to the ten product-acceptance
categories in issue #733. It identifies evidence that can be reused, evidence that remains
partial or unavailable, and the exact inputs required before the next ten-scenario run.

The record observes `main@2f4e980a61c6c6e66ff99812ec948eeeb990821a` on 2026-09-16. It does not
freeze a new scenario oracle, redefine product acceptance, or claim that any target category is
complete.

## Authority and evidence

This record applies the following authority order:

1. [Product Delivery issue #733](https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/issues/733)
   defines the target 5 motor / 3 home / 2 contents categories and product-level gates.
2. [Sprint 4](../../sprint/sprint4.md) sections 7 and 8 define the journey-record fields and
   Sprint-level evidence requirements.
3. [Fixtures and Test Conventions](../fixtures_convention.md) separates scenario data,
   executable assertions, runtime doubles, and verification evidence.
4. [Complete-journey runs](../../tests/journey_runs/README.md) defines the implemented
   `northwind-journey-run/3` record and result classes.
5. [Pull request #894](https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/pull/894)
   and its [consolidated result](https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/issues/771#issuecomment-5696256792)
   provide the merged baseline evidence.

The final source head exercised by the baseline was
`969764c47985ceb3cf672dff4375b0880daae169`. The batch wrote 100 records outside the
repository: 50 motor, 30 home, and 20 contents.

## Baseline result

The baseline establishes breadth and evidence integrity, but it does not satisfy the ten-scenario
product gate.

| Family | Runs | Result classes | Reusable evidence | Principal limitation |
| --- | ---: | --- | --- | --- |
| Motor | 50 | 10 `fixture-only`; 40 `partial` | 50 distinct claimant/staff input sequences; five typed material packs; executable AT-01, PRES-01, and PRES-02 oracles | Fixture runtime and simulated assessor; no deployed or live-provider evidence |
| Home | 30 | 30 `partial` | Water-ingress Claim creation; registered home fields; received and invalid material conditions | The disclosure-consent record has no route; no burglary journey |
| Contents | 20 | 20 `unavailable` | Six material variants with received, invalid, expired, disputed, and unavailable conditions | Intake stops at `contents.items`; no contents Claim creation |

Across all records, 426 recorded Agent turns equal 426 recorded claimant messages. The average
claimant effort is 4.26 messages, 2.28 confirmations, 3.30 uploads, and 0.17 consents. The batch
contains no failed run, blocked run, or oracle mismatch. Those zero counts describe this batch;
they do not prove the independent failure and recovery paths required by #733.

## Ten-category acceptance map

The rows below use the required business differences in #733. A baseline fixture or material
variant is evidence only for the behavior it actually exercises.

| Target | Required difference | Matching baseline evidence | Current classification and stop | Missing proof | Owner or dependency | Next-rerun entry condition |
| --- | --- | --- | --- | --- | --- | --- |
| M1 | Collision and fast progression | AT-01 clear motor creation with received and four non-default material packs | `fixture-only` with the complete simulated pack; `partial` when a material has `no_route` or is not delivered | Frozen M1 oracle, deployed Runtime trace, claims-adapter provenance, and browser projection | #733 for the final oracle; #901 / PR #903 and #904–#910 for Agent Runtime v7; #769 for backend/AWS evidence | The exact M1 scenario and oracle are published, relevant v7 work is merged, and the configured claims adapter can return a traceable result |
| M2 | Injury or continuing danger | None in the 100-run batch | Not yet run | Complete natural-language trajectory, urgent authority boundary, preserved progress, claimant/staff projection, and recovery result | #733 and Agent owner for the oracle; #770 for behavior; #771 for cross-end validation | The approved injury/danger scenario has an executable oracle and the final Runtime path is on `main` |
| M3 | Another party or Police | AT-01 includes a Police event report supplied manually by the claimant | `fixture-only` or `partial`; the report is material input, not a dedicated another-party or Police-service journey | Another-party facts, Police responsibility and access form, consent/visibility, and claims-adapter result | #733 for the scenario; #769 for confirmed integration capability; #771 for role projections | The scenario distinguishes claimant-supplied Police material from any real or unavailable Police integration and has an executable next-step oracle |
| M4 | Vehicle damage with assessor or repair | AT-01 assessor request/result and five motor material packs | `fixture-only` for the complete simulated-assessor path; variants can be `partial` | Live or truthfully unavailable provider evidence, unknown/retry behavior, repair responsibility, and browser state | #769 for provider/AWS boundary; #771 for claimant and Workbench projections | Provider mode and authority are fixed, failure states are observable, and both role projections consume the same external-task state |
| M5 | Fact or evidence conflict and professional review | PRES-02 guided review and staff resolution; separate AT-01 records preserve disputed and superseded pack metadata | `partial` in all 16 PRES-02 runs; the consent and assessment materials remain undelivered after the professional-review path | Final conflict oracle, internal-versus-claimant visibility, revision/idempotency readback, and browser evidence; AT-01 pack metadata alone does not prove professional-review behavior | #733 and #770 for the behavior oracle; #771 for browser and cross-role evidence | The v7 proposal/Runtime contract is published and the professional-review action can be verified from both role projections |
| H1 | Burglary | None; the home batch contains water ingress only | Not yet run | Burglary facts, Police/evidence boundary, safety state, handoff or next safe action, and Claim creation | #733 for the frozen scenario; #770 for behavior; #769 for required backend capability | A registered-field-compatible burglary scenario and executable oracle are published |
| H2 | Weather, water, or other property damage | Home water-ingress base path | 30 `partial`; registered intake reaches Claim creation, but the consent record has `no_route` | Final H2 oracle, claims-adapter provenance, browser evidence, and an accepted disclosure/repair boundary | #769 for backend/external boundary; #771 for browser evidence | The consent or explicit unavailable path is authoritative and the exact scenario is selected for the ten-case suite |
| H3 | Evidence, safety, repair, or review difference | Water-ingress path with ongoing-risk/habitable fields and an illegible attendance-note variant | `partial`; the invalid condition is recorded, but material content is not interpreted by the controlled Agent | Behavior that responds to the evidence condition, safety/review outcome, repair responsibility, and role projections | #733/#770 for the oracle; #769 for repair/provider state; #771 for cross-end evidence | The selected H3 difference has an executable expected state change rather than only typed material metadata |
| C1 | Damaged items with ownership, value, and purchase evidence | Base damaged-laptop path with photos, receipt, and replacement assessment | `unavailable` at `contents.items` | Item capture, item-level ownership/value state, Evidence association, Claim creation, and claims-adapter result | #769 for the shared backend boundary; #770 for behavior; #771 for projections | `contents.items` is captured through the authoritative contract and the runner can reach the next safe action without a private schema |
| C2 | Item-level evidence or fact conflict | Theft, illegible receipt, expired valuation, conflicting ownership, and authority-not-held variants | `unavailable` at `contents.items`; material conditions are preserved but not consumed into item behavior | Executable item conflict/authority oracle, review or unavailable outcome, claimant/staff visibility, and Claim result | #733/#770 for the oracle; #769 for item/Evidence capability; #771 for cross-role evidence | C1 item capture exists and one selected conflict path has an authoritative expected Runtime and projection outcome |

## Cross-cutting gaps

The following gaps apply across more than one target row.

| Evidence area | Baseline result | Acceptance gap | Required source or owner |
| --- | --- | --- | --- |
| Claims-adapter result | Some fixture journeys create a Claim and record a synthetic result | The ten target categories do not each have a traceable claims-adapter request/result | #733 acceptance; #769 backend owner |
| Claimant and staff agreement | Records include visibility and seam checks where the runner can read both projections | No browser evidence exists, and not every target row reaches both role projections | #771 claimant/workbench owners |
| Agent and Runtime trace | API-level records retain observable proposals, next steps, and declared trace limitations | Internal proposal-to-execution evidence must be re-established after the v7 chain | #901 / PR #903 and #904–#910, with #910 as the publication boundary |
| Browser journey | None; the baseline is API projection evidence | No screenshot or rendered interaction proves loading, pending, retry, unavailable, stale, or professional-review states | #771 claimant and Workbench slices; #902 only for evidence that specifically requires durable SSE reconnect or resynchronisation |
| AWS and provider capability | Fixture runtime and simulated provider only | No real AWS permission, call, provider result, or production-integration claim | #769; unavailable remains an acceptable honest result |
| Claimant effort | Exact 100-run totals and per-run records exist | The final ten-scenario question budget and repeated-question metrics have not been calculated | #733 metric definition and final ten-run batch |
| Severity and fraud evaluation | Not measured by the 100-run baseline | No frozen blind severity labels, confusion matrix, or fraud TP/FP/FN/TN evidence | #733 and the authorized business-review boundary |
| Failure and recovery | Zero baseline failures and blocks; oracle mismatches serialize correctly when injected by regression tests | Required timeout, malformed, unknown, unavailable, duplicate, resume, and professional-review trajectories are not one reviewed evidence set | #770 behavior and #769 backend failure semantics; #771 validates the cross-end result |

## Dependency and rerun order

The next ten-scenario execution must not begin merely because the runner exists. It needs the
following inputs in order:

1. **Scenario and oracle input:** #733 must identify the exact ten scenario IDs and expected
   product outcomes. The categories above are not a substitute for executable oracles.
2. **Runtime input:** the relevant #901 / PR #903 and #904–#910 changes must be merged, with #910
   publishing one coherent Agent Runtime v7 Release Set. An in-flight Runtime head is not a stable
   baseline. Issue #902 is separate realtime synchronisation work, not a general v7 prerequisite;
   only a browser/reconnect claim that uses its durable SSE behavior must wait for #902.
3. **Backend input:** #769 must identify which claims-adapter, AWS, external-task, contents-item,
   and failure semantics are implemented, simulated, or unavailable.
4. **Projection input:** #771 owners must identify the claimant and Workbench routes that render
   each selected target state without local lifecycle inference.
5. **Evidence execution:** the journey-validation owner can then run one motor, one home, and one
   contents smoke trajectory on the exact merged head. Expansion to all ten follows only after the
   smoke records agree with their executable oracles.

The bounded next validation slice is therefore a three-family exact-head smoke rerun after the
first four inputs exist. It reuses `northwind-journey-run/3`, adds no private fields or behavior,
and stops with an honest unavailable record when a required capability remains absent.

## Limitations

This record is a source-and-test evidence map. It does not include browser execution, live model
or provider calls, AWS permissions, Northwind policy authority, blind staff labels, or a final
ten-scenario result. Issue and pull request states can change after the named baseline; the next
runner issue must re-read their exact delivered evidence rather than treating this map as proof of
completion.

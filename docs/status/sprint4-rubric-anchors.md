# Sprint 4 rubric anchors

## Purpose and status

Sprint 4's Definition of Done item 2 asks for ten rubric anchors drawn from the complete-journey
tests, each with complete input, output, state, and metric evidence (`sprint/sprint4.md`, section
8). The ten are the frozen evaluation set in
[issue #733](https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/issues/733):
five motor, three home, and two contents categories, each with a required business difference.

This record gives every category one entry. Seven name a run from the 50/30/20 baseline; three
record that no run exercises the category, with what is missing and its owner. The runs were
produced at `main@d396cf00d02e903cfe63bcabfa7ea4d27771b602` on 2026-09-21 and are
`northwind-journey-run/6` records kept outside the repository, as `tests/journey_runs/README.md`
requires.

This record does not freeze scenarios, define product acceptance, or claim that any category
meets the quantitative gates in #733. [The journey evidence pack](sprint4-journey-evidence-pack.md) holds the
scenario matrix and totals; [the gap record](sprint4-journey-acceptance-gaps.md) maps the same runs
to the ten categories at a category level.

**Evidence level.** Every run is `runtime: fixture`, `provider_mode: simulated`, and
`agent_runtime_profile: controlled`: API projections on the fixture runtime with simulated
providers. Not browser, AWS, live-provider, model-backed, or production evidence.

**Main-path rule.** #733 states that "independent failure/unknown/professional-review trajectories
are also required and do not substitute for main-path results". The five assessor failure journeys
are therefore cited only as supporting evidence under M4, never as an anchor.

## Anchor summary

| Category | Required difference (#733) | Anchor | Result class | Where it ends |
| --- | --- | --- | --- | --- |
| M1 | Collision and fast progression | `AT-01-clear-motor-creation` with `motor-collision-provisional-2` | `fixture-only` | Assessment received and under staff review |
| M2 | Injury or continuing danger | No run | — | — |
| M3 | Another party or Police | No run | — | — |
| M4 | Vehicle damage with assessor or repair | `AT-01-clear-motor-creation` with `motor-collision-unavailable-v1` | `partial` | Assessor assigned, external party owns the next step |
| M5 | Fact or evidence conflict and professional review | `PRES-02-guided-rear-end-review` with `motor-collision-provisional-2` | `partial` | Staff update owned by a claims professional |
| H1 | Burglary | No run | — | — |
| H2 | Weather, water, or other property damage | `home-water-ingress` with `home-water-ingress-provisional-1` | `fixture-only` | Claim created |
| H3 | Evidence, safety, repair, or review difference | `home-water-ingress-illegible-note` with `home-water-ingress-illegible-v1` | `fixture-only` | Claim created |
| C1 | Damaged items with ownership, value, and purchase evidence | `contents-damaged-item` with `contents-damaged-item-provisional-1` | `unavailable` | Intake stops at `contents.items` |
| C2 | Item-level evidence or fact conflict | `contents-damaged-item-conflicting-ownership` with `contents-damaged-item-conflicting-ownership-v1` | `unavailable` | Intake stops at `contents.items` |

Metric coverage is identical in all seven anchors, as it is across the whole baseline: the
follow-up rate, blind severity rating, and fraud precision are `not_measured` on the controlled
runtime; claimant effort is `partly_measured`; the claim result is `measured`.

## M1. Collision and fast progression

**Anchor:** `AT-01-clear-motor-creation-input-01`, pack `motor-collision-provisional-2`,
`fixture-only`, all 14 steps succeeded.

- **Input.** One claimant message reports a rear-end collision at Queen Street with no injury and a
  safe, driveable scene. Pack: two incident photos and a Police event report (`received`, uploaded
  by the claimant), the consent record (`received`, through the consent route), and the assessment
  report (`received`, from the simulated assessor).
- **Output.** The Agent structures what happened, the subtype, location, damage, injury or danger,
  and other parties, then asks the claimant to confirm. Steps: working claim, description, three
  upload pairs, confirmation, claim creation `201`, assessor consent `201`, routing `201`, task
  lookup, and assessment receipt `201`.
- **State.** Claim `NWF-2026-...` with an expected-by timestamp, workflow state `created`, next step
  `assessor_result_under_review` owned by a claims professional, three evidence records, and one
  external task. Four seam checks and three visibility checks hold.
- **Metrics.** One claimant message, no Agent question turn, one confirmation, three uploads, one
  consent. Claim result `measured`.
- **Why it anchors M1.** The claimant reports once and the journey reaches claim creation and an
  assessor result without further questions, which is the "fast progression" difference.

## M2. Injury or continuing danger

**No run.** The 50 motor runs use scenarios whose claimant states no injury and a safe scene.

- **Missing.** A frozen injury or continuing-danger scenario, its urgent authority boundary, the
  claimant and staff projections for it, and a runner.
- **Owner.** #733 for the frozen scenario; #770 for the Agent and Runtime behaviour.
- **Evidence.** The gap record's M2 row records the same absence.

## M3. Another party or Police

**No run.** AT-01 carries a Police event report as a claimant-supplied material, and the runs
record another party in the structured facts, but no journey exercises a Police or another-party
service path.

- **Missing.** A journey where the Police or another-party interaction is the business difference,
  with its own authority boundary and third-party state.
- **Owner.** #733 for the frozen scenario; #769 for any Police-service boundary.
- **Evidence.** The gap record's M3 row states that the report is material input, not a dedicated
  journey.

## M4. Vehicle damage with assessor or repair

**Anchor:** `AT-01-clear-motor-creation-input-10`, pack `motor-collision-unavailable-v1`,
`partial`, all 13 steps succeeded.

- **Input.** As M1, except the pack's assessment report is the `unavailable` notice, which no route
  accepts.
- **Output.** The same intake, creation, consent, and routing steps. The run stops before an
  assessment arrives because the notice has no route in.
- **State.** Claim created with a claim number and expected-by, next step `assessor_assigned` owned
  by the external party, three evidence records, one external task. Four seam checks and three
  visibility checks hold.
- **Metrics.** One claimant message, no question turn, one confirmation, three uploads, one consent.
  Claim result `measured`.
- **Why it anchors M4.** It shows the assessor request, the consent that authorises it, and an
  honest third-party state: the run is `partial` because the assessment never arrives, and the
  record says so rather than presenting the claim as complete.
- **Supporting evidence, not anchors.** The five assessor failure journeys (#933, #942) record
  retryable, terminal, unusable-answer, unknown-outcome, and interrupted-dispatch failures with
  their recoveries. Under #733 they do not substitute for this main-path result.

## M5. Fact or evidence conflict and professional review

**Anchor:** `PRES-02-guided-rear-end-review-input-12`, pack `motor-collision-provisional-2`,
`partial`, all 13 steps succeeded.

- **Input.** Four claimant messages: an uncertain first report, a safety answer, an approximate
  time, and "The police report will be ready next week."
- **Output.** The Agent asks about injury and danger, then the time, then whether a Police report is
  available. It records the report as expected later and hands the facts and policy wording to a
  claims specialist. Three question turns, no repeats.
- **State.** No claim number: the journey ends before creation at workflow state `ready_for_next`,
  next step `staff_update` owned by a claims professional, four evidence records. The consent record
  and the assessment are `not_delivered`, because this journey ends before assessor consent, which
  is why the run is `partial`. The assessor seams are `unavailable` rather than contradictory.
- **Metrics.** Four claimant messages, three Agent question turns, no repeats, three uploads, no
  consent. Claim result `measured` as "no claim number: this journey ends before claim creation".
- **Why it anchors M5.** A pending Police report is an evidence gap the Agent does not resolve on
  its own: it routes the claim to professional review and says so to the claimant.

## H1. Burglary

**No run.** The 30 home runs are water ingress only.

- **Missing.** A frozen burglary scenario, its Police and evidence boundary, the safety state, and
  the handoff or next safe action.
- **Owner.** #733 for the frozen scenario; #770 for the behaviour.
- **Evidence.** The gap record's H1 row records the same absence.

## H2. Weather, water, or other property damage

**Anchor:** `home-water-ingress-input-01`, pack `home-water-ingress-provisional-1`, `fixture-only`,
all 20 steps succeeded.

- **Input.** Seven claimant messages: the water ingress report, no injury, the location, the
  property address, the affected areas, an active leak, and that the house is still habitable. Pack:
  two incident photos and a repair assessment (`received`, uploaded), and the consent record, which
  is `not_applicable` under the selected manual repairer form (#927).
- **Output.** The Agent structures each answer and asks for confirmation; two question turns, no
  repeats. Steps: working claim, description, three upload pairs, five confirmations, and claim
  creation `201`.
- **State.** Claim created with a claim number and expected-by, next step `claim_created` owned by
  the system, three evidence records. Its seam and visibility checks hold.
- **Metrics.** Seven claimant messages, two question turns, five confirmations, three uploads.
  Claim result `measured`.
- **Why it anchors H2.** It is the home property-damage path that reaches claim creation, including
  the registered ongoing-risk and habitability facts.

## H3. Evidence, safety, repair, or review difference

**Anchor:** `home-water-ingress-illegible-note-input-01`, pack `home-water-ingress-illegible-v1`,
`fixture-only`, all 20 steps succeeded.

- **Input.** The same seven-message intake. The pack replaces the repair assessment with an
  attendance note whose condition is `invalid` (illegible), uploaded by the claimant.
- **Output and state.** As H2: the claim is created with a claim number, and the illegible note is
  recorded as an evidence record with its declared condition.
- **Metrics.** Seven claimant messages, two question turns, five confirmations, three uploads.
- **Why it anchors H3.** It is the evidence-difference variant of the home path: the material is
  accepted and recorded with its condition rather than silently treated as usable. The run is
  `fixture-only` because the runtime, not the material, limits it.
- **Limitation.** The record preserves the declared condition; it does not prove that the Agent read
  the document's content. Material content is not consumed on this runtime.

## C1. Damaged items with ownership, value, and purchase evidence

**Anchor:** `contents-damaged-item-input-01`, pack `contents-damaged-item-provisional-1`,
`unavailable`, all 15 steps succeeded.

- **Input.** Four claimant messages describing the damaged item and the incident. Pack: two item
  photos, a purchase receipt, and a replacement assessment (`received`, uploaded), and the consent
  record, `not_applicable` under the selected contents-evidence form (#927).
- **Output.** The Agent structures the report and asks for one damaged item. Two question turns, no
  repeats.
- **State.** No claim number: workflow state `collecting`, next step `more_information_needed` owned
  by the claimant, four evidence records. The run records one unavailable capability, contents item
  capture, needed for claim creation, citing `docs/model-gateway.md` and Discussion #847.
- **Metrics.** Four claimant messages, two question turns, two confirmations, four uploads.
- **Why it anchors C1.** Ownership, value, and purchase evidence all arrive and are recorded; the
  journey then stops at `contents.items`, which this runtime does not capture. The class is
  `unavailable`, not `failed`: the capability is missing, not broken.

## C2. Item-level evidence or fact conflict

**Anchor:** `contents-damaged-item-conflicting-ownership-input-01`, pack
`contents-damaged-item-conflicting-ownership-v1`, `unavailable`, all 17 steps succeeded.

- **Input.** The C1 intake plus a sixth material: identity and ownership evidence whose declared
  condition is `disputed`, uploaded by the claimant.
- **Output and state.** As C1, with five uploads and the disputed material recorded. The journey
  stops at the same unavailable capability.
- **Metrics.** Four claimant messages, two question turns, two confirmations, five uploads.
- **Why it anchors C2.** The item-level conflict is carried into the record with its condition and
  its own evidence identity. What cannot be shown here is how the Agent resolves the conflict,
  because intake stops before claim creation.

## What these anchors do not show

- **Three categories have no run.** M2, M3, and H1 stay open; #733 owns the frozen scenarios.
- **No category meets #733's gates.** Ten of ten claim creations, the follow-up rate, severity, and
  fraud evaluation all need the model-backed runtime (#962) and frozen evaluation data.
- **Contents never reaches creation.** C1 and C2 stop at `contents.items` until #962.
- **Material content is not read.** Conditions are declared by the pack and preserved; no anchor
  proves the Agent used a document's content.

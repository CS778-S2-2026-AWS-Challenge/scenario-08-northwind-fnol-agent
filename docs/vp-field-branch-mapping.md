# VP Field and Branch Mapping

## Scope and authority

This document is the executable mapping for Week 6 P2.1. It maps every field in the
current backend Field/Branch Registry (version 8) to the three VP family branches.
The registry and API/persistence contracts remain authoritative for names and types;
this document records scenario applicability, projection boundaries, confirmation
needs, and lifecycle use. It does not add fields, define policy coverage, or replace
the Dynamic Form evaluator.

## Mapping rules

- `common` fields are available to all three family branches.
- A family field is active only after the corresponding `claim.product_family` branch
  is selected. `incident.type` is an event subtype, not a second family selector.
- `claimant.client_number` is system-owned and Workbench-only.
- Contents-specific repeated facts are represented by the independent
  `WorkingClaim.contents_items` record, not by flattened form fields.
- `required_now` is selected by the current safe action and published branch rules; no
  field in this table is globally mandatory.
- `confirmation` describes the normal acceptance boundary: `yes` means claimant or
  authorised staff confirmation is required before a material action; `conditional`
  means the rule depends on source, conflict, or the active action.

## Executable field matrix

| Field code | Applies to | Branch | Type | Source / authority | Confirmation | Claimant visibility | Lifecycle use |
|---|---|---|---|---|---|---|---|
| `policy.policy_number` | all | `common` | text | claimant or bounded lookup | conditional | claimant/staff | policy lookup and routing |
| `claimant.client_number` | all | `common` | text | identity/system | no | staff only | ownership and audit |
| `claimant.role` | all | `common` | text | claimant | yes | claimant/staff | reporter context |
| `claimant.contact_preference` | all | `common` | enum | claimant/profile | yes | claimant/staff | support and follow-up |
| `claimant.relationship_to_policyholder` | all | `common` | enum | claimant | conditional | claimant/staff | reporter authority |
| `policyholder.identity_ref` | all | `common` | text | account/policy | conditional | staff; claimant-safe name only | non-policyholder reporter |
| `policyholder.name` | all | `common` | text | claimant/policy | conditional | claimant/staff | policyholder fallback |
| `claim.product_family` | all | `family.*` | enum | claimant plus deterministic routing | yes | claimant/staff | family activation |
| `incident.type` | all | `common` | enum | claimant; staff may correct | conditional | claimant/staff | safety and conditional branches |
| `incident.occurred_at` | all | `common` | temporal | claimant/evidence | conditional | claimant/staff | chronology and next action without invented precision |
| `incident.location` | all | `common` | location | claimant/evidence | conditional | claimant/staff | safety, routing, service scope |
| `incident.description` | all | `common` | text | claimant natural account | conditional | claimant/staff | intake summary |
| `incident.injury_or_danger` | all | `common` + `safety.injury_or_danger` | boolean | claimant; staff may verify | conditional | claimant/staff | urgent interruption and safe action |
| `incident.cause` | all | `common` | text | claimant/evidence | conditional | claimant/staff | triage; never coverage conclusion |
| `loss.description` | all | `common` | text | claimant/evidence | conditional | claimant/staff | loss scope and summary |
| `parties.other_parties` | all | `common` + `participant.another_party` | boolean | claimant | conditional | claimant/staff | consent, participant, and handoff work |
| `incident.liability_position` | all | `common`; `required_now` once `parties.other_parties` is confirmed true | enum | claimant | yes | claimant/staff | intake triage (third-party recovery or unresolved liability); never a liability decision |
| `loss.estimated_amount` | all | `common` | number (NZD) | claimant estimate or quote/assessment total | conditional | claimant/staff | intake triage amount threshold; never a settlement value |
| `claim.cover_disagreement` | all | `common` | enum | claimant | yes | claimant/staff | intake triage (complex when the claimant disputes the excess or cover) |
| `authorities.police_report_reference` | motor | `family.motor` + `authority.police` | text | claimant/evidence/staff | conditional | claimant/staff | authority evidence and waiting work |
| `authorities.emergency_services_notified` | motor | `family.motor` + `authority.police` | boolean | claimant/staff | conditional | claimant/staff | safety and authority context |
| `vehicle.registration` | motor | `family.motor` | text | claimant/evidence | conditional | claimant/staff | vehicle identification and provider routing |
| `vehicle.damage_description` | motor | `family.motor` | text | claimant/evidence | conditional | claimant/staff | damage triage and assessment preparation |
| `vehicle.drivable` | motor | `family.motor` | boolean | claimant; evidence/staff may verify | conditional | claimant/staff | safety, towing, and next action |
| `vehicle.use` | motor | `family.motor` | enum | claimant/policy | conditional | claimant/staff | use at incident |
| `vehicle.towing_required` | motor | `family.motor` | enum | claimant/staff | conditional | claimant/staff | recovery routing |
| `vehicle.towing_location` | motor | `family.motor` | location | claimant/staff | conditional | claimant/staff | recovery routing |
| `driver.identity_ref` | motor | `family.motor` | text | claimant/account | conditional | staff; claimant-safe projection | actual driver identity |
| `driver.name` | motor | `family.motor` | text | claimant | conditional | claimant/staff | actual driver |
| `driver.phone` | motor | `family.motor` | text | claimant | conditional | claimant/staff | driver contact |
| `driver.email` | motor | `family.motor` | text | claimant | conditional | claimant/staff | driver contact |
| `driver.relationship_to_policyholder` | motor | `family.motor` | enum | claimant | conditional | claimant/staff | driver authority |
| `driver.owner_permission` | motor | `family.motor` | enum | claimant | conditional | claimant/staff | permission fact only |
| `driver.licence_number` | motor | `family.motor` | protected text | claimant | conditional | masked staff only | licence verification |
| `driver.licence_status` | motor | `family.motor` | enum | claimant/staff | conditional | staff; claimant-safe status | bounded review routing |
| `other_party.insurer_name` | motor | `family.motor` | text | claimant/evidence | conditional | claimant/staff | third-party routing |
| `other_party.policy_number` | motor | `family.motor` | protected text | claimant/evidence | conditional | masked staff only | third-party routing |
| `other_party.claim_reference` | motor | `family.motor` | text | claimant/evidence | conditional | claimant/staff | third-party routing |
| `witness.present` | motor | `family.motor` | enum | claimant | conditional | claimant/staff | witness branch |
| `witness.name` | motor | `family.motor` | text | claimant | conditional | claimant/staff | repeatable witness record |
| `witness.phone` | motor | `family.motor` | text | claimant | conditional | claimant/staff | repeatable witness record |
| `witness.email` | motor | `family.motor` | text | claimant | conditional | claimant/staff | repeatable witness record |
| `police.status` | all | `common` + `authority.police` | enum | claimant/evidence/staff | conditional | claimant/staff | police workflow state |
| `property.address` | home | `family.home` | location | claimant/bounded lookup | conditional | claimant/staff | property routing |
| `property.affected_areas` | home | `family.home` | text list | claimant/evidence | conditional | claimant/staff | triage and evidence requests |
| `property.ongoing_risk` | home | `family.home`; may trigger `mitigation.emergency` | enum | claimant; staff may verify | conditional | claimant/staff | urgent safety interruption |
| `property.habitable` | home | `family.home`; may trigger `accommodation.temporary` | boolean | claimant/staff | conditional | claimant/staff | support and accommodation work |
| `property.occupancy_relationship` | home | `family.home` | enum | claimant/policy | conditional | claimant/staff | authority and routing |
| `property.occupancy` | home | `family.home` | enum | claimant | conditional | claimant/staff | safety and routing |
| `contents.police_reference` | contents | `family.contents` + `authority.police` | text | claimant/evidence/staff | conditional | claimant/staff | authority evidence for stolen or damaged items |
| `incident.discovered_at` | all | `common` | temporal | claimant/evidence | conditional | claimant/staff | discovery chronology |
| `injury.persons_affected` | all | `injury.details` | text_list | claimant | source-dependent | claimant/staff | required now |
| `injury.severity_reported` | all | `injury.details` | enum: minor / needs_medical_attention / serious / unknown | claimant | source-dependent | claimant/staff | required now |
| `injury.medical_attention` | all | `injury.details` | enum: none / self_treated / gp_or_clinic / ambulance_called / hospitalised / unknown | claimant/staff | source-dependent | claimant/staff | before creation |
| `theft.entry_context` | home/contents | `contents.theft` | enum: forced_entry / unlocked / unknown / not_applicable | claimant/evidence | source-dependent | claimant/staff | required now |

## Contents record boundary

The `contents` family activates the independent `WorkingClaim.contents_items` list
introduced by the minimum-field contract. Each `ContentsItem` carries item identity,
description, opaque display category, quantity, loss type, ownership, optional
currency-qualified estimated value, source references, status, needed-for, confidence,
and updater provenance. Claimant projections use `ClaimantContentsItem` and expose only
claimant-safe fields; Workbench retains the authorised full record. Item-to-Evidence
association remains a separate follow-up boundary and is not invented by this mapping.

## Remaining non-goals and ownership

The following catalogue candidates remain outside this executable catalogue:

- additional motor facts such as vehicle make/model, driver, collision detail, witness,
  repairer, and towing records;
- additional home facts such as occupancy, building/fixture damage, utilities,
  mitigation, accommodation detail, and weather;
- additional contents item facts such as brand/model, serial number, purchase details,
  replacement need, discovery time, and item evidence links;
- retained Registry version on `WorkingClaim` (the evaluated Branch record retains the
  registry coordinates); and
- scenario seed records, field examples/state values, and full projections, which are
  owned by #583 and #585 respectively.

These remain non-goals and do not justify duplicate field names.

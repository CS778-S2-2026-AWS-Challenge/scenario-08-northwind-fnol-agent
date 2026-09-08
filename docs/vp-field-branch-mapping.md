# VP Field and Branch Mapping

## Scope and authority

This document is the executable mapping for Week 6 P2.1. It maps every field in the
current backend Field/Branch Registry (version 5) to the three VP family branches.
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
| `claim.product_family` | all | `family.*` | enum | claimant plus deterministic routing | yes | claimant/staff | family activation |
| `incident.type` | all | `common` | enum | claimant; staff may correct | conditional | claimant/staff | safety and conditional branches |
| `incident.occurred_at` | all | `common` | text | claimant/evidence | conditional | claimant/staff | chronology and next action |
| `incident.location` | all | `common` | location | claimant/evidence | conditional | claimant/staff | safety, routing, service scope |
| `incident.description` | all | `common` | text | claimant natural account | conditional | claimant/staff | intake summary |
| `incident.injury_or_danger` | all | `common` + `safety.injury_or_danger` | boolean | claimant; staff may verify | conditional | claimant/staff | urgent interruption and safe action |
| `incident.cause` | all | `common` | text | claimant/evidence | conditional | claimant/staff | triage; never coverage conclusion |
| `loss.description` | all | `common` | text | claimant/evidence | conditional | claimant/staff | loss scope and summary |
| `parties.other_parties` | all | `common` + `participant.another_party` | boolean | claimant | conditional | claimant/staff | consent, participant, and handoff work |
| `authorities.police_report_reference` | motor | `family.motor` + `authority.police` | text | claimant/evidence/staff | conditional | claimant/staff | authority evidence and waiting work |
| `authorities.emergency_services_notified` | motor | `family.motor` + `authority.police` | boolean | claimant/staff | conditional | claimant/staff | safety and authority context |
| `vehicle.registration` | motor | `family.motor` | text | claimant/evidence | conditional | claimant/staff | vehicle identification and provider routing |
| `vehicle.damage_description` | motor | `family.motor` | text | claimant/evidence | conditional | claimant/staff | damage triage and assessment preparation |
| `vehicle.drivable` | motor | `family.motor` | boolean | claimant; evidence/staff may verify | conditional | claimant/staff | safety, towing, and next action |
| `property.address` | home | `family.home` | location | claimant/bounded lookup | conditional | claimant/staff | property routing |
| `property.affected_areas` | home | `family.home` | text list | claimant/evidence | conditional | claimant/staff | triage and evidence requests |
| `property.ongoing_risk` | home | `family.home`; may trigger `mitigation.emergency` | enum | claimant; staff may verify | conditional | claimant/staff | urgent safety interruption |
| `property.habitable` | home | `family.home`; may trigger `accommodation.temporary` | boolean | claimant/staff | conditional | claimant/staff | support and accommodation work |

## Contents record boundary

The `contents` family activates the independent `WorkingClaim.contents_items` list
introduced by the minimum-field contract. Each `ContentsItem` carries item identity,
description, opaque display category, quantity, loss type, ownership, optional
currency-qualified estimated value, source references, status, needed-for, confidence,
and updater provenance. Claimant projections use `ClaimantContentsItem` and expose only
claimant-safe fields; Workbench retains the authorised full record. Item-to-Evidence
association remains a separate follow-up boundary and is not invented by this mapping.

## Explicit gaps and ownership

The following catalogue candidates are intentionally not executable fields in version 5:

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

These are named so downstream work cannot silently treat design candidates as registered
fields. They do not block the current executable mapping or justify duplicate field names.

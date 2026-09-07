# Demonstration Material Catalogue

The materials a Validation Prototype demonstration needs for the `motor`, `home`, and
`contents` lines: what each one is, why the journey needs it, what it is called, and what
state it is demonstrated in.

This is the catalogue only. The material files themselves are produced separately, and the
Claim and Evidence associations are added after that.

## What belongs here, and what does not

**Status: planned, not implemented.** Nothing in this catalogue exists yet. No material file has
been produced, and no loader reads this directory. `backend/services/demo_seed.py` reads
`backend/demo_data/scenarios/` only, through `SCENARIO_DIRECTORY` and `seed_scenario()`; it has no
materials path.

These materials are **intended to become product runtime data**: once P8.2 produces the files and
P8.3 associates them with Claim and Evidence records, they are to be seeded into a running demo and
read by the same code paths a real claimant and a real staff member use. Until then this document
is a specification of what will be produced, and every statement about seeding below describes that
intent rather than current behaviour.

They are **not test fixtures**. `docs/fixtures_convention.md` reserves `tests/fixtures/` for
static fixture data, and keeps runtime demo data, static fixtures, executable assertions, and
test doubles under independent ownership so that none of them stands in for another. A material
in this catalogue must never be the thing a test asserts against, and a fixture under
`tests/fixtures/media/` must never be shown in a demonstration.

The current scenario records under `backend/demo_data/scenarios/` blur that line: every evidence
record there carries `provenance.fixture_storage_ref` of the form `fixture://path/...`, and no
material file exists behind it. Closing that gap is what this catalogue is written for.

## Naming rules

```text
<family>-<scenario>-<kind>-<sequence>.<extension>
```

| Part | Rule |
| --- | --- |
| `family` | `motor`, `home`, or `contents`. From `backend/domain/branch_registry.py` `FAMILY_NAMES`. No other value. |
| `scenario` | The stable scenario identifier in lower case with the `AT-` prefix folded in, for example `at01`, `at06`, `at10`. New demonstration-only scenarios use `vp` plus a two-digit number. |
| `kind` | The evidence `kind` exactly as it is persisted, with underscores kept: `incident_image`, `police_report`, `assessment_report`, `repair_quote`, `other_document`, `agency_incident_record`, `internal_policy_history`. |
| `sequence` | Two digits from `01`, unique within one scenario and kind. |
| `extension` | `jpg` for photographs, `png` for screenshots or diagrams, `pdf` for documents and reports. It must agree with the record's `media_type`. |

`kind` is an unconstrained string on `EvidenceRecord`, so this catalogue does not invent a
schema for it, but it does introduce one value the repository has not used before:
**`repair_quote`**. Existing records use `incident_image`, `other_document`, `police_report`,
`agency_incident_record`, `internal_policy_history`, and `assessment_report`. A repair or
replacement quotation does not fit any of those without stretching `other_document` past
usefulness, and it appears on all three lines, so it is named here rather than hidden. If the
value should be something else, this catalogue is the place to change it before fifteen files
carry it.

Lower case, hyphen separated between parts, underscores only inside `kind`. No claimant name,
address, registration, policy number, or date in a filename: the file name is shown in staff and
claimant surfaces, and a name is not a place to carry claim facts.

Examples: `motor-at01-incident_image-01.jpg`, `home-vp02-repair_quote-01.pdf`,
`contents-vp03-other_document-02.pdf`.

## Vocabulary each entry must use

Every material maps onto one persisted `EvidenceRecord`, so the catalogue uses that record's own
vocabulary rather than inventing labels.

- **Source** (`EvidenceSource`): `claimant`, `staff`, `external_system`
- **Status** (`EvidenceStatus`): `received`, `unofficial`, `incomplete`, `pending_generation`, `inconsistent`
- **File status** (`EvidenceFileStatus`): `not_available`, `awaiting_upload`, `uploading`, `uploaded`, `processing`, `ready`, `failed`
- **Related fields**: registered field codes from `branch_registry`, never free text

A material with `file_status: not_available` has no file by design; it demonstrates something the
claimant does not have yet. Those rows are listed here without a filename on purpose.

## Motor

Registered fields available: `vehicle.registration`, `vehicle.damage_description`,
`vehicle.drivable`, `authorities.police_report_reference`,
`authorities.emergency_services_notified`.

| Material | Scenario | Kind | Purpose in the journey | Source | Status | File status | Filename |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Rear bumper damage photograph | `at01` | `incident_image` | Supports `vehicle.damage_description` so the Agent can propose the damage fact rather than ask for it | `claimant` | `received` | `ready` | `motor-at01-incident_image-01.jpg` |
| Wider scene photograph | `at01` | `incident_image` | Shows position and surroundings; demonstrates two images on one claim | `claimant` | `received` | `ready` | `motor-at01-incident_image-02.jpg` |
| Police event reference, not yet issued | `at06` | `police_report` | Demonstrates claimant-owned future evidence that must not block safe work | `claimant` | `pending_generation` | `not_available` | none, by design |
| Police report, issued | `vp01` | `police_report` | The same claim after the report arrives, so the state change is demonstrable | `claimant` | `received` | `ready` | `motor-vp01-police_report-01.pdf` |
| Assessor assessment report | `at10` | `assessment_report` | The result of the controlled assessor route, labelled as a fixture provider answer | `external_system` | `received` | `ready` | `motor-at10-assessment_report-01.pdf` |
| Repair quotation | `vp01` | `repair_quote` | Staff-facing cost document; demonstrates a document that is not a claim fact | `claimant` | `unofficial` | `ready` | `motor-vp01-repair_quote-01.pdf` |
| Damaged vehicle, unreadable photograph | `vp01` | `incident_image` | Demonstrates `inconsistent`: a file that arrived but does not support the stated fact | `claimant` | `inconsistent` | `ready` | `motor-vp01-incident_image-03.jpg` |

## Home

Registered fields available: `property.address`, `property.affected_areas`.

| Material | Scenario | Kind | Purpose in the journey | Source | Status | File status | Filename |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Water damage to ceiling and wall | `vp02` | `incident_image` | Supports `property.affected_areas` | `claimant` | `received` | `ready` | `home-vp02-incident_image-01.jpg` |
| Affected room, second angle | `vp02` | `incident_image` | Shows extent across one room | `claimant` | `received` | `ready` | `home-vp02-incident_image-02.jpg` |
| Plumber attendance note | `vp02` | `other_document` | Third-party attendance record; demonstrates a document with no official status | `claimant` | `unofficial` | `ready` | `home-vp02-other_document-01.pdf` |
| Repair quotation | `vp02` | `repair_quote` | Cost document for the affected areas | `claimant` | `received` | `ready` | `home-vp02-repair_quote-01.pdf` |
| Building report, awaiting inspection | `vp02` | `assessment_report` | Demonstrates a pending external answer on the home line | `external_system` | `pending_generation` | `not_available` | none, by design |

## Contents

Registered fields available: **none yet.** `branch_registry` carries no `contents` fields, so the
`related_fields` for every row below is unresolved. Filling it is P2.1's mapping work, and the
rows here name the material and its purpose so that mapping has something concrete to attach to.

| Material | Scenario | Kind | Purpose in the journey | Source | Status | File status | Filename |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Damaged item photograph | `vp03` | `incident_image` | Identifies the item claimed for | `claimant` | `received` | `ready` | `contents-vp03-incident_image-01.jpg` |
| Item in situ before the incident | `vp03` | `incident_image` | Demonstrates a supporting image that is not damage evidence | `claimant` | `received` | `ready` | `contents-vp03-incident_image-02.jpg` |
| Purchase receipt | `vp03` | `other_document` | Ownership and value support | `claimant` | `received` | `ready` | `contents-vp03-other_document-01.pdf` |
| Replacement quotation | `vp03` | `repair_quote` | Replacement cost for the item | `claimant` | `unofficial` | `ready` | `contents-vp03-repair_quote-01.pdf` |
| Receipt for a second item, illegible | `vp03` | `other_document` | Demonstrates `incomplete`: a file arrived but does not carry the needed detail | `claimant` | `incomplete` | `ready` | `contents-vp03-other_document-02.pdf` |
| Police event reference for a burglary | `vp03` | `police_report` | Demonstrates the same pending-report pattern outside the motor line | `claimant` | `pending_generation` | `not_available` | none, by design |

## What exists today

Nine scenario records exist under `backend/demo_data/scenarios/`. Their coverage against the three
lines is uneven:

| Line | Scenario records today |
| --- | --- |
| `motor` | 8 |
| `home` | 0 |
| `contents` | 0 |
| neither, `incident_type: property` | 1, `AT-02-coverage-ambiguity.json` |

`AT-02` uses `property`, which is not one of the three `FAMILY_NAMES`. Whether it is renamed to
`home` or kept as a separate coverage-ambiguity case is a scenario decision rather than a material
one, and it is recorded here because the catalogue cannot claim `home` coverage while the only
non-motor record sits outside the family list.

Every existing evidence record carries `provenance.fixture_storage_ref` and no file. Eighteen
materials are catalogued above; three of them are deliberately file-less, so fifteen files are to
be produced.

## Open dependency

`contents` has no registered fields, so `related_fields` cannot be filled for the six rows in that
section. Everything else in this catalogue is independent of that.

# Demonstration Material Catalogue

What material a Validation Prototype demonstration must be able to show, what each class of
material has to carry, and what the `motor`, `home`, and `contents` paths must each demonstrate.

## 1. Purpose and non-goals

**Purpose.** Establish the material classes, their required attributes, their lifecycle and
visibility semantics, and the coverage each claim path must reach, so that asset production and
runtime association have a specification to satisfy rather than a list to copy.

**Non-goals.** This document does not produce assets, does not associate anything with a Claim or
an Evidence record, does not define filenames or a directory layout, and does not decide how a
material class maps onto a persisted backend field. Those are P8.2, P8.3, and the contract work
named in section 9.

**Status.** Specification only. Nothing described here exists yet. No asset has been produced, no
loader reads a material directory, and `backend/services/demo_seed.py` currently reads
`backend/demo_data/scenarios/` alone.

**Authority.** This document is normative for *what a demonstration must be able to show*. It is
not normative for backend field names, enum values, scenario identifiers, or storage layout; where
it refers to any of those it is describing an unresolved mapping, not fixing one.

## 2. Material taxonomy

Six classes. A material belongs to exactly one class; the class determines which attributes in
section 3 are required.

| Class | What it is | Why the journey needs it |
| --- | --- | --- |
| **Incident evidence** | Direct depiction of the loss or damage | Lets the Agent propose a material fact instead of interrogating the claimant for it |
| **Identity and ownership evidence** | Establishes who is claiming and that the thing claimed for was theirs | Required before value or entitlement can be discussed at all |
| **Authority or official report** | Issued by a body outside Northwind and outside the claimant's control | Carries weight the claimant cannot supply alone, and arrives on the issuer's timetable, not ours |
| **Assessment or estimate** | A professional judgement of damage, cost, or repairability | The output of a third-party service request, and the input to any cost conversation |
| **Communication and consent record** | Evidence of what was disclosed, agreed, or authorised | Makes an authorisation auditable rather than assumed |
| **Expected but unavailable material** | A material the journey needs that does not exist yet, or cannot be obtained | The demonstration must show honest waiting, not a blank space |

The sixth class is deliberately a class rather than a status. A demonstration that only shows
material which arrived is not demonstrating the product; the absence cases are where claimant trust
is won or lost, and they need their own coverage.

## 3. Required attributes for every material

Every catalogued material must answer all of these before it is produced. An unanswered attribute
is an open decision, recorded in section 9, not a blank to be filled in during production.

| Attribute | What it must state |
| --- | --- |
| **Purpose** | The claimant or staff decision this material supports. Not "supporting evidence" — which decision |
| **Applicable paths and trigger** | Which of `motor`, `home`, `contents` it applies to, and at what point in the journey it becomes relevant |
| **Source and stakeholder** | Who provides it, and whether that is the claimant, Northwind staff, or an external party |
| **Lifecycle states** | Which of the states in section 4 this material can occupy, and what each means for this material specifically |
| **Media and quality requirements** | What makes an instance usable: legibility, what must be visible, what makes it insufficient |
| **Provenance and verification** | Where it came from, what is known about its origin, and what checking it has or has not received |
| **Consent and visibility** | Whether disclosure to a third party requires claimant consent, and what claimant and staff each may see |
| **Linkage** | What claim fact, registered field, staff action, or third-party request it attaches to |
| **Absent or unusable behaviour** | What the claimant and staff interfaces must show when it is missing, unreadable, disputed, or unavailable |
| **Retention** | How long it is kept and what deletion means for it, where the class implies any such rule |

## 4. Lifecycle, provenance, quality, consent, visibility, retention

### 4.1 Lifecycle states

These are semantic states for the catalogue. Mapping them onto persisted values is section 9's
unresolved work, not a decision made here.

| State | Meaning |
| --- | --- |
| **Missing** | The journey needs it and nothing has been offered |
| **Unavailable** | It has been sought and cannot currently be obtained; the reason matters and must be shown |
| **Pending** | It is expected, and the wait is on someone identifiable — the claimant, an authority, a service |
| **Received** | An instance exists and is attached |
| **Invalid** | An instance exists but does not serve its purpose: unreadable, wrong subject, or inconsistent with what it is meant to support |
| **Superseded** | A later instance replaces it, and the earlier one remains part of the record |
| **Expired** | It was valid and no longer is, because time or a claim change has invalidated it |

A demonstration must be able to reach **Missing**, **Pending**, **Received**, and **Invalid** on at
least one material. **Unavailable**, **Superseded**, and **Expired** are required only where a class
in section 5 marks them.

### 4.2 Provenance and confidence

Every material carries where it came from. A material whose origin is a controlled simulation must
say so wherever it is shown; no surface may present simulated material as though a real provider
supplied it. Structural checks — the file exists, it is the right type, it is attached to the right
claim — never amount to verification of content. A material that has only been placed is not a
material that has been checked, and the two must be distinguishable in the record and on screen.

### 4.3 Consent and visibility

Disclosure of a material outside Northwind requires a recorded claimant authorisation naming what is
shared and for what purpose. Internal assessment of a material is not disclosure. Claimant-visible
surfaces carry the material, its state, and its next step; they never carry internal review signals,
staff notes, or authorisation references. Staff surfaces carry the authorisation basis, because
staff need to know why a disclosure was permitted.

### 4.4 Retention

Material follows the claim it belongs to. Where a class carries identity or financial detail beyond
what the claim needs, section 5 marks it, and the retention question is recorded in section 9 rather
than answered here.

## 5. Coverage matrix for motor, home, and contents

What each path must be able to demonstrate. This is stated as classes and situations so that it
stays valid when scenarios are renamed, added, or replaced.

| Class | motor | home | contents |
| --- | --- | --- | --- |
| Incident evidence | Required, at least two instances so extent is demonstrable | Required, at least two instances covering more than one affected area | Required, at least two instances covering the item and its context |
| Identity and ownership evidence | Optional; ownership is usually established by policy | Optional; established by policy and address | **Required**; ownership of a specific item cannot be assumed |
| Authority or official report | **Required**, including a pending instance | Optional | **Required**, including a pending instance |
| Assessment or estimate | **Required**, produced through a third-party service request | Required | Required |
| Communication and consent record | **Required**, because a third-party disclosure occurs | Required where a third party is involved | Required where a third party is involved |
| Expected but unavailable material | **Required** | **Required** | **Required** |

Every path must additionally demonstrate at least one **Invalid** material, because a material that
arrives and does not serve its purpose is the case most likely to be handled badly.

## 6. Claimant and staff journey touchpoints

| Moment | Claimant must see | Staff must see |
| --- | --- | --- |
| Material requested | What is needed, why, and what happens if it cannot be provided | That it is outstanding and who it is waiting on |
| Material provided | That it arrived, and what it now unblocks | The material, its provenance, and whether it has been checked |
| Material pending on a third party | Who is being waited on and that the claim is preserved meanwhile | The request, its state, and the responsible party |
| Material invalid | What is wrong in plain terms and what to do next | The reason, and the action available to them |
| Material disclosed to a third party | What was shared, with whom, and for what purpose | The same, plus the authorisation that permitted it |

## 7. Missing, unavailable, and disputed material

A material that is absent must never read as an ordinary claim with nothing outstanding. The
absence, the reason, the responsible party, and the next step are all part of what a surface must
show.

- **Missing** must not block work that does not depend on it.
- **Unavailable** must state why, and must not silently degrade into a claim of unavailability where none was established.
- **Pending** must name who is being waited on. "Waiting" without an owner is not an acceptable state to display.
- **Invalid** must say what is wrong in terms the claimant can act on, and must not silently overwrite the fact it was meant to support.
- **Disputed**, meaning a material inconsistent with another material or with a stated fact, must keep both sides visible to staff and must not resolve itself automatically.

## 8. Boundary with P8.2 and P8.3

| Card | Owns |
| --- | --- |
| **P8.1**, this document | The taxonomy, the required attributes, the lifecycle and visibility semantics, the three-path coverage matrix, and the list of open decisions |
| **P8.2** | Producing assets that satisfy the classes and attributes here, including their naming, format, and directory layout, which this document deliberately does not fix |
| **P8.3** | Associating assets with Claim and Evidence records, seeding them through the runtime path, and verifying the claimant and staff projections |

P8.1's acceptance is document-level: the catalogue is reviewable, internally coherent, covers all
three paths, and records what remains undecided. API, persistence, and browser evidence belong to
P8.2 and P8.3.

## 9. Open decisions and backend mapping notes

These are unresolved. None of them is decided by this document, and each needs the named upstream
work before it can be.

| Open decision | Blocked on |
| --- | --- |
| How the lifecycle states in 4.1 map onto persisted evidence status and file-status values | Backend contract work; the current enums were not designed against this taxonomy |
| Which registered field each material class links to | **P2**, the field and Dynamic Form mapping. `contents` currently has no registered fields at all |
| Which stakeholder issues each authority report and assessment, and what access exists | **P3**, the stakeholder and service catalogue |
| What consent copy and disclosure scope each class requires | **P5**, the service-level consent and shared-data contract |
| Whether an assessment or estimate needs a distinct persisted kind, or fits an existing one | Backend contract work, after P3 defines the services that produce them |
| Retention rules for identity and ownership material | Privacy review; not raised by any current card |
| Naming, format, and directory layout for produced assets | **P8.2**, which owns them |

## 10. Appendix: current repository gap, non-normative

A snapshot of the repository as of `main@eaad036`, recorded so the distance to the coverage matrix
is visible. It describes what exists, not what is required, and nothing here is a requirement.

Nine scenario records exist under `backend/demo_data/scenarios/`:

| Path | Scenario records |
| --- | --- |
| `motor` | 8 |
| `home` | 0 |
| `contents` | 0 |
| Neither, recorded as `property` | 1 |

The single non-motor record, `AT-02-coverage-ambiguity.json`, uses `property`, which is not one of
the three paths. Whether it is renamed, replaced, or kept as a separate coverage case is a scenario
decision for P8.2 or the scenario owner.

Every evidence record in those scenarios references a fixture storage location and no asset exists
behind it. No path currently reaches the **Unavailable**, **Superseded**, or **Expired** states, and
only `motor` reaches **Pending**.

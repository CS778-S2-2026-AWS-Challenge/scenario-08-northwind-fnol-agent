# Demonstration Material Catalogue

What material a Validation Prototype demonstration must be able to show, what each class of
material has to carry, which conditions each class must be demonstrated in, and what the `motor`,
`home`, and `contents` paths must each cover.

## 1. Purpose and non-goals

**Purpose.** Establish the material classes, their required attributes, the condition model that
applies across all of them, and the coverage each claim path must reach, so that asset production
and runtime association have a specification to satisfy rather than a list to copy.

**Non-goals.** This document does not produce assets, does not associate anything with a Claim or an
Evidence record, does not define filenames, extensions, or a directory layout, and does not decide
how a material class or condition maps onto a persisted backend field. Those are P8.2, P8.3, and the
contract work named in section 9.

**Status.** Specification only. Nothing described here exists yet. No asset has been produced, no
loader reads a material directory, and `backend/services/demo_seed.py` currently reads
`backend/demo_data/scenarios/` alone.

**Authority.** This document is normative for *what a demonstration must be able to show*. It is not
normative for backend field names, enum values, scenario identifiers, or storage layout; where it
refers to any of those it is describing an unresolved mapping, not fixing one.

## 2. Material taxonomy

Five classes, on one axis only: what the material **is**. A material belongs to exactly one class.
What state a material is in is a separate axis, defined in section 4.

| Class | What it is | Why the journey needs it | Retention sensitivity |
| --- | --- | --- | --- |
| **Incident evidence** | Direct depiction of the loss or damage | Lets the Agent propose a material fact instead of interrogating the claimant for it | Standard |
| **Identity and ownership evidence** | Establishes who is claiming and that the thing claimed for was theirs | Required before value or entitlement can be discussed at all | **Elevated** |
| **Authority or official report** | Issued by a body outside Northwind and outside the claimant's control | Carries weight the claimant cannot supply alone, and arrives on the issuer's timetable | Standard |
| **Assessment or estimate** | A professional judgement of damage, cost, or repairability | The output of a third-party service request, and the input to any cost conversation | **Elevated** |
| **Communication and consent record** | Evidence of what was disclosed, agreed, or authorised | Makes an authorisation auditable rather than assumed | **Elevated** |

**Retention sensitivity** marks classes that carry identity or financial detail beyond what the
claim itself needs. It is a marker, not a rule: the rule is unresolved and is recorded in section 9.
Classes marked Standard follow the claim they belong to.

Material that the journey needs and that does not exist is **not a class**. It is a condition, and
it is covered by section 4.2 and the state-coverage requirement in section 5.2.

## 3. Required attributes for every material

Every catalogued material must answer all of these before it is produced. An unanswered attribute is
an open decision, recorded in section 9, not a blank to be filled in during production.

| Attribute | What it must state |
| --- | --- |
| **Purpose** | The claimant or staff decision this material supports. Not "supporting evidence" — which decision |
| **Applicable paths and trigger** | Which of `motor`, `home`, `contents` it applies to, and at what point in the journey it becomes relevant |
| **Source and stakeholder** | Who provides it, and whether that is the claimant, Northwind staff, or an external party |
| **Conditions it can occupy** | Which of the conditions in section 4 apply to this material, and what each means for it specifically |
| **Media and quality requirements** | What makes an instance usable: legibility, what must be visible, what makes it insufficient |
| **Provenance and verification** | Where it came from, what is known about its origin, and what checking it has or has not received |
| **Consent and visibility** | Whether disclosure to a third party requires claimant consent, and what claimant and staff each may see |
| **Linkage** | What claim fact, registered field, staff action, or third-party request it attaches to |
| **Behaviour when not usable** | What the claimant and staff interfaces must show in each condition from section 4.2 that applies |
| **Retention** | For a class marked Elevated in section 2, what is kept and for how long, once section 9's open decision is resolved |

## 4. Condition model

Conditions are the second axis. They apply across classes: any class can be missing, any received
material can turn out invalid. This section defines them once rather than per class.

### 4.1 Conditions

Semantic conditions for this catalogue. Mapping them onto persisted values is section 9's unresolved
work, not a decision made here.

| Condition | Group | Meaning |
| --- | --- | --- |
| **Missing** | Absence | The journey needs it and nothing has been offered |
| **Pending** | Absence | It is expected, and the wait is on someone identifiable — the claimant, an authority, a service |
| **Unavailable** | Absence | It has been sought and cannot currently be obtained; the reason matters and must be shown |
| **Received** | Present | An instance exists and is attached |
| **Invalid** | Present | An instance exists but does not serve its purpose: unreadable, wrong subject, or insufficient |
| **Superseded** | Present | A later instance replaces it, and the earlier one remains part of the record |
| **Expired** | Present | It was valid and no longer is, because time or a claim change has invalidated it |
| **Disputed** | Reconciliation | An instance is inconsistent with another material or with a stated fact, and neither side has been resolved |

**Disputed** is grouped separately because it is not a property of one material. It is a relationship
between a material and something else, it always involves at least two things, and it is resolved by
a decision rather than by an arrival or the passage of time. A material can be Received and Disputed
at once; it cannot be Received and Missing at once.

### 4.2 Which conditions must be demonstrated

Section 5.2 states this per class and path. The rule for reading it: a condition is required only
where 5.2 marks it, and a marked condition must be reachable in that path's demonstration, not merely
describable.

### 4.3 Provenance and confidence

Every material carries where it came from. A material whose origin is a controlled simulation must
say so wherever it is shown; no surface may present simulated material as though a real provider
supplied it. Structural checks — the file exists, it is the right type, it is attached to the right
claim — never amount to verification of content. A material that has only been placed is not a
material that has been checked, and the two must be distinguishable in the record and on screen.

### 4.4 Consent and visibility

Disclosure of a material outside Northwind requires a recorded claimant authorisation naming what is
shared and for what purpose. Internal assessment of a material is not disclosure. Claimant-visible
surfaces carry the material, its condition, and its next step; they never carry internal review
signals, staff notes, or authorisation references. Staff surfaces carry the authorisation basis,
because staff need to know why a disclosure was permitted.

### 4.5 Retention

Material follows the claim it belongs to. Classes marked **Elevated** in section 2 carry identity or
financial detail beyond what the claim needs, so they need a rule of their own. That rule does not
exist yet and is recorded as an open decision in section 9; this document marks which classes need
it rather than inventing one.

## 5. Coverage

### 5.1 Which classes each path must demonstrate

| Class | motor | home | contents |
| --- | --- | --- | --- |
| Incident evidence | Required, at least two instances so extent is demonstrable | Required, at least two instances covering more than one affected area | Required, at least two instances covering the item and its context |
| Identity and ownership evidence | Optional; ownership is usually established by policy | Optional; established by policy and address | **Required**; ownership of a specific item cannot be assumed |
| Authority or official report | **Required** | Optional | **Required** |
| Assessment or estimate | **Required**, produced through a third-party service request | Required | Required |
| Communication and consent record | **Required**, because a third-party disclosure occurs | Required where a third party is involved | Required where a third party is involved |

### 5.2 Which conditions each path must demonstrate

`R` means the condition must be reachable on that class in that path's demonstration. A blank means
it is not required, and a class marked Optional in 5.1 carries no condition requirement unless the
path includes it.

| Condition | motor | home | contents |
| --- | --- | --- | --- |
| Missing | R, on any class | R, on any class | R, on any class |
| Pending | R, on the authority report | R, on the assessment | R, on the authority report |
| Unavailable | R, on the assessment | | R, on the authority report |
| Received | R, on incident evidence | R, on incident evidence | R, on incident evidence and on ownership evidence |
| Invalid | R, on incident evidence | R, on any received class | R, on ownership evidence |
| Superseded | R, on the assessment | | |
| Expired | | | R, on ownership evidence |
| Disputed | R, between incident evidence and a stated fact | | R, between two ownership materials |

Every path must reach **Missing**, **Pending**, **Received**, and **Invalid**. The remaining
conditions are required only in the cells marked above, so that each is demonstrated somewhere
without requiring all three paths to carry all eight.

A cell is reached in one of three ways, and they are not interchangeable:

- **By absence** — `Missing` and `Pending`. Nothing was offered, or the wait is on someone
  identifiable. No artefact exists because nothing came back, so the cell is reached by a material
  of that class recording the condition among those it can occupy.
- **By artefact** — `Received`, `Invalid`, `Superseded`, `Expired`, `Disputed`. Something arrived,
  and the demonstration shows it.
- **By record** — `Unavailable`. Section 7 requires it to be established rather than inferred, and
  what establishes it is a received answer. So the cell is reached by a material that holds no bytes
  and cites that answer. Neither half reaches the cell alone: the answer on its own is a received
  document, and the record on its own is an assertion with nothing behind it.

## 6. Claimant and staff journey touchpoints

| Moment | Claimant must see | Staff must see |
| --- | --- | --- |
| Material requested | What is needed, why, and what happens if it cannot be provided | That it is outstanding and who it is waiting on |
| Material provided | That it arrived, and what it now unblocks | The material, its provenance, and whether it has been checked |
| Material pending on a third party | Who is being waited on and that the claim is preserved meanwhile | The request, its condition, and the responsible party |
| Material invalid | What is wrong in plain terms and what to do next | The reason, and the action available to them |
| Material disputed | That a check is in progress, without being told which side is doubted | Both sides, their sources, and the decision that would resolve it |
| Material disclosed to a third party | What was shared, with whom, and for what purpose | The same, plus the authorisation that permitted it |

## 7. Behaviour when material is absent or not usable

A material in an absence condition must never read as an ordinary claim with nothing outstanding.
The condition, the reason, the responsible party, and the next step are all part of what a surface
must show.

- **Missing** must not block work that does not depend on it.
- **Pending** must name who is being waited on. "Waiting" without an owner is not an acceptable state to display.
- **Unavailable** must state why, and must not silently degrade into a claim of unavailability where none was established. What establishes it is an answer that arrived — an assessor or issuer saying that the material cannot be produced — and that answer is a *received* material of its own. The unavailable material is the one the answer refuses, and it has no artefact, because a material that cannot be obtained is precisely the one there is nothing to open. A demonstration that labels the answer as the unavailable material has produced a legible document and called it an absence.
- **Invalid** must say what is wrong in terms the claimant can act on, and must not silently overwrite the fact it was meant to support.
- **Superseded** must keep the earlier instance in the record and name what replaced it; replacement is not deletion, and an earlier instance that cannot say what superseded it is indistinguishable from one that was simply set aside.
- **Expired** must say what expired and what would restore it.
- **Disputed** must keep both sides visible to staff and must not resolve itself automatically, which means it must name its other side: either the material it conflicts with or the stated claim fact it contradicts. The claimant is told a check is in progress, not which side is doubted.

## 8. Boundary with P8.2 and P8.3

| Card | Owns |
| --- | --- |
| **P8.1**, this document | The taxonomy, the required attributes, the condition model, the coverage requirements, and the list of open decisions |
| **P8.2** | Producing assets that satisfy the classes, attributes, and coverage here, including their naming, format, and directory layout, which this document deliberately does not fix |
| **P8.3** | Associating assets with Claim and Evidence records, seeding them through the runtime path, and verifying the claimant and staff projections |

P8.1's acceptance is document-level: the catalogue is reviewable, internally coherent, covers all
three paths, and records what remains undecided. API, persistence, and browser evidence belong to
P8.2 and P8.3.

## 9. Open decisions

None of these is decided by this document, and each needs the named upstream work before it can be.

| Open decision | Blocked on |
| --- | --- |
| How the conditions in 4.1 map onto persisted evidence status and file-status values | Backend contract work; the current enums were not designed against this model. Direction was given on discussion #692: `EvidenceStatus` carries the business condition and `EvidenceFileStatus` the upload lifecycle alone, with conflict, supersession, and established unavailability carried by typed references rather than by a status word. `Disputed`, `Superseded`, and `Unavailable` now name their other side in the manifest, in the shape that mapping will take |
| Which registered field each material class links to | **P2**, the field and Dynamic Form mapping. `contents` currently has no registered fields at all |
| Which stakeholder issues each authority report and assessment, and what access exists | **P3**, the stakeholder and service catalogue |
| What consent copy and disclosure scope each class requires | **P5**, the service-level consent and shared-data contract |
| Whether an assessment or estimate needs a distinct persisted kind, or fits an existing one | Backend contract work, after P3 defines the services that produce them |
| The retention rule for the three classes marked **Elevated** in section 2 | Privacy review; not raised by any current card, and section 2 marks the classes rather than inventing the rule |
| Naming, format, extensions, and directory layout for produced assets | **P8.2**, which owns them |

## 10. Appendix: current repository gap, non-normative

A snapshot of the repository as of `main@417d82b`, recorded so the distance to the coverage
requirements is visible. It describes what exists, not what is required, and nothing here is a
requirement.

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
behind it. Against section 5.2, only `motor` currently reaches **Pending**, no path reaches
**Unavailable**, **Superseded**, **Expired**, or **Disputed**, and no path demonstrates ownership
evidence at all.

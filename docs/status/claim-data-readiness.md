# Claim data readiness inventory

## Purpose and status

This status record inventories the identity, Claim, session, message, and Evidence data that
exists on `main@61e21cdb` as observed on 2026-09-07. It identifies reusable records and fields,
relationship and visibility boundaries, and unresolved inputs for issue #583 and later Week 6
cards. It does not define a second schema, promote candidate fields, or prove a runnable journey.

The principal finding is that the repository has a durable, source-aware Claim graph and a
working 20-code Field Registry, but it does not yet have one coherent runnable seed graph for
normal-mode identities, online staff, and representative motor, home, and contents Claims.

## Authority and evidence

This record applies the following authority order:

1. Product behaviour and visibility come from
   [Claim State and Data](../../SPEC/04-claim-state-and-data.md),
   [Workbench and Handoff](../../SPEC/05-workbench-and-handoff.md), and
   [Safety and Governance](../../SPEC/06-safety-and-governance.md).
2. Implemented transport and persistence boundaries come from the
   [API contract](../api.md), [Persistence contract](../persistence-schema.md), and
   [Identity and developer-mode contract](../identity-and-developer-mode.md).
3. Executable shapes come from
   [`backend/domain/models.py`](../../backend/domain/models.py),
   [`backend/domain/identity.py`](../../backend/domain/identity.py),
   [`backend/domain/staff_identity.py`](../../backend/domain/staff_identity.py), and
   [`backend/domain/field_registry.py`](../../backend/domain/field_registry.py).
4. The [FNOL information model](../fnol-field-model.md) is design input. Its `candidate` and
   `record` rows are not implemented fields unless the executable contracts above contain them.
5. Demo scenarios and fixtures are coverage evidence only. They do not create product fields or
   runtime authority.

The evidence was re-derived with source inspection and these non-mutating commands:

```powershell
git rev-parse origin/main
rg -n "class (WorkingClaim|SessionRecord|MessageRecord|EvidenceRecord)" backend/domain/models.py
rg -n "REGISTERED_FIELD_CODES|FIELD_REGISTRY_VERSION" backend/domain
rg -n "CustomerAccountRecord|StaffAccountRecord" backend/domain backend/adapters
Get-ChildItem backend/demo_data/scenarios/*.json
```

## Readiness summary

The following table separates implemented data from gaps that a later card must own.

| Area | Implemented and reusable | Missing or ambiguous | Downstream owner |
| --- | --- | --- | --- |
| Claimant identity | Fixture and SQLite account/session repositories; profile and communication-preference API projections | Seed scenarios are not inserted into the normal-mode SQLite identity store | #583 |
| Staff identity | Fixture and SQLite account/session repositories; role and enabled-account fields | `active` means account enabled, not online or available; no availability, capacity, or last-seen record exists | #583 and #617 |
| Claim | Revisioned `WorkingClaim`, one authoritative `ClaimState`, source-aware form, assignee, active session, external-service state, and next step | Top-level `incident_type` is a compatibility projection; Registry version is not retained on `WorkingClaim` | #584, #585, and #596 |
| Session | Claim/customer ownership, active/closed state, resume summary, unresolved work, commitments, and context revision | `claim_id` is mandatory and no interaction-intent field represents a non-claim session | #596 and #629 |
| Message | Claim/session linkage, client idempotency key, actor class, explicit visibility, evidence links, reply linkage, and timestamp | The durable record has an actor class but no actor identifier | #625 |
| Evidence | Claim ownership, lifecycle, file metadata, source, related fields, provenance, waiting responsibility, timing, and context | No direct session link; record visibility is derived from source; object key and checksum remain generic provenance members | #602, #603, and #604 |
| Dynamic fields | Registry version `5` with 22 codes; source, status, current/later need, confidence, actor, and source references; three-family mapping is documented in [VP Field and Branch Mapping](../vp-field-branch-mapping.md) | Candidate fields beyond the executable subset remain explicitly unregistered; contents uses the independent `ContentsItem` record | #584 and #585 |
| Seed graph | Nine loadable Claim scenarios and deterministic fixture identities | All scenarios belong to `cus_demo`; eight are motor and one uses legacy `property`; no exact home/contents trio or online-staff data exists | #583 |

## Implemented record inventory

### Claimant identity

`CustomerAccountRecord` is the identity source of truth for the following stored fields:

| Field | Status | Visibility and use |
| --- | --- | --- |
| `customer_id` | Reusable | Stable subject and Claim ownership key; claimant and authorised services may receive the identifier. |
| `email` | Reusable | Claimant profile data; not copied into Claim State. |
| `password_hash` | Reusable internal field | Identity repository only; never returned by the API. |
| `display_name` | Reusable | Claimant profile projection. |
| `phone` | Reusable | Claimant profile projection. |
| `communication_preferences.email` | Reusable | Claimant preference; it is not consent to disclose Claim data. |
| `communication_preferences.sms` | Reusable | Claimant preference; it is not consent to disclose Claim data. |

`ClaimantAuthSessionRecord` stores `token_hash`, `customer_id`, `created_at`, `expires_at`, and
`revoked_at`. Authentication responses return a newly issued access token, subject, and expiry;
the stored token hash remains internal.

The identity repositories are selected independently from the Claim data profile. Explicit
developer mode uses `FixtureIdentityRepository`; normal mode uses `SQLiteIdentityRepository`.
MongoDB therefore does not become the identity source of truth when `local_mvp` is selected.

### Staff identity

`StaffAccountRecord` is the staff identity source of truth for the following stored fields:

| Field | Status | Visibility and use |
| --- | --- | --- |
| `staff_id` | Reusable | Stable staff subject and assignment actor identifier. |
| `email` | Reusable | Staff profile data. |
| `password_hash` | Reusable internal field | Staff identity repository only. |
| `display_name` | Reusable | Staff profile projection. |
| `roles` | Reusable | Coarse identity roles; Claim/task authority still requires resource checks. |
| `active` | Ambiguous for #583 | Implemented as account enabled. It must not be interpreted as online, available, or below capacity. |

`StaffAuthSessionRecord` stores `token_hash`, `staff_id`, `created_at`, `expires_at`, and
`revoked_at`. Authentication responses return a newly issued access token, subject, and expiry;
the stored token hash remains internal. The repository has no online-presence or queue-capacity
record. Issue #583 cannot invent that shape while issue #617 owns the online staff pool and Claim
responsibility action.

### Claim and Claim State

`WorkingClaim` is the authoritative mutable Claim record. Its current fields are:

| Field group | Fields | Status and boundary |
| --- | --- | --- |
| Identity | `claim_id`, `customer_id` | Reusable immutable ownership identity. |
| Concurrency | `revision` | Reusable optimistic-concurrency boundary. |
| Entry context | `channel`, `locale` | Reusable Claim entry metadata. |
| Family compatibility | `incident_type` | Reusable compatibility projection; `claim.product_family` is the source-aware form field. |
| Authoritative state | `claim_state` | Reusable state dimensions; not duplicated in sessions, fixtures, or frontends. |
| Dynamic facts | `form` | Reusable mapping from a registered field code to `StructuredFormField`. |
| Evidence roll-up | `evidence_summary` | Derived summary; Evidence records remain authoritative. |
| Work routing | `route`, `assignee_id` | Reusable routing and current-assignee references. |
| Conversation | `active_session_id` | Reusable pointer to the one active Claim session. |
| External Claim | `external_claim`, `external_claim_source_revision`, `external_claim_fingerprint` | Reusable integration result and replay provenance. |
| External service | `external_service_consents`, `assessor_routing`, `assessor_routing_fingerprint` | Reusable bounded consent and assessor compatibility state. |
| Claimant progress | `customer_next_step` | Reusable server-owned next-step projection input. |
| Time | `created_at`, `updated_at` | Reusable lifecycle timestamps. |

`ClaimState` already separates `severity`, `coverage`, `evidence`, `fraud_signal`,
`customer_support`, `urgency`, `workflow_state`, and `next_action`. No downstream card should
create a second status record for these dimensions.

Each `StructuredFormField` already stores `value`, `source`, `source_refs`, `status`,
`needed_for`, `confidence`, `updated_at`, and `updated_by`. The available statuses are
`proposed`, `confirmed`, `disputed`, `missing`, and `pending_generation`. These fields are the
reusable basis for #585; scenario data must not flatten a fact to an un-sourced primitive.

### Registered Dynamic Form fields

The executable Field Registry is version `5` and contains 22 codes. The branch evaluator requires
an exact matching value contract for every code, so adding a name to only one collection is not a
valid field implementation.

| Scope | Registered codes | Readiness |
| --- | --- | --- |
| Common | `policy.policy_number`, `claimant.client_number`, `claimant.role`, `claimant.contact_preference`, `claim.product_family`, `incident.type`, `incident.occurred_at`, `incident.location`, `incident.description`, `incident.injury_or_danger`, `incident.cause`, `loss.description`, `parties.other_parties` | Reusable, subject to branch selection and role visibility. |
| Motor | `authorities.police_report_reference`, `authorities.emergency_services_notified`, `vehicle.registration`, `vehicle.damage_description`, `vehicle.drivable` | Reusable bounded motor subset. |
| Home | `property.address`, `property.affected_areas`, `property.ongoing_risk`, `property.habitable` | Minimum executable home subset; broader home catalogue candidates remain unregistered. |
| Contents | Independent `WorkingClaim.contents_items` record; no flattened family fields | Item-level fields are executable through the typed record and role-safe projections; item-to-Evidence association remains a later boundary. |

`claimant.client_number` is system-owned and marked claimant-hidden in the Branch Registry.
`claim.product_family` accepts `motor`, `home`, or `contents`. The separate `incident.type`
describes the event subtype and must not be used as a second family field.

### Session

`SessionRecord` contains the following fields:

| Field group | Fields | Status and boundary |
| --- | --- | --- |
| Identity and ownership | `session_id`, `claim_id`, `customer_id` | Reusable; every session belongs to one Claim and customer. |
| Lifecycle | `status`, `started_at`, `last_active_at`, `closed_at` | Reusable active/closed lifecycle. |
| Resume context | `summary`, `unresolved_questions`, `pending_items`, `prior_commitments` | Reusable bounded continuity data; not a second Claim State. |
| Freshness | `context_revision` | Reusable; cannot exceed the authoritative Claim revision. |

The current record cannot represent a pre-Claim or non-claim conversation because `claim_id` is
required. That is an explicit gap, not permission for #583 to create an unregistered session
variant.

### Message

`MessageRecord` contains `message_id`, `claim_id`, `session_id`, `client_message_id`, `actor`,
`visibility`, `content`, `evidence_refs`, `in_reply_to`, and `created_at`.

The record supports duplicate-request protection through `client_message_id`, role-safe history
through `visibility`, and same-conversation reply and Evidence links. `actor` records only the
actor class (`claimant`, `agent`, `staff`, or `system`). It does not identify the specific actor.
Staff mutations and audit records carry actor identifiers elsewhere, but that does not make the
message field unambiguous.

### Evidence

`EvidenceRecord` contains the following fields:

| Field group | Fields | Status and boundary |
| --- | --- | --- |
| Identity | `evidence_id`, `claim_id` | Reusable; Evidence belongs to one Claim. |
| Classification | `kind`, `source` | Reusable, but `kind` is an open string rather than a shared registry. |
| Lifecycle | `status`, `file_status` | Reusable Evidence and byte-processing states. |
| File metadata | `original_filename`, `media_type`, `size_bytes` | Reusable metadata; original bytes remain in object storage. |
| Fact links | `related_fields`, `needed_for` | Reusable registered-field and action-need links. |
| Provenance | `provenance` | Reusable generic container; storage key, checksum, extraction, and processing members are not typed on the record. |
| Claimant context | `claimant_note` | Reusable optional claimant statement. |
| Waiting context | `wait_type`, `responsible_party`, `expected_by`, `expected_timing`, `context_summary` | Reusable next-action and Workbench inputs. |
| Time | `created_at`, `updated_at` | Reusable lifecycle timestamps. |

Evidence has no direct `session_id`. A message may link Evidence through `evidence_refs`, but that
does not prove which session created every Evidence record. Evidence also has no explicit
visibility field. The current projection derives `shared` for claimant-sourced Evidence and
`internal_only` for staff or external-system Evidence.

## Record relationships and enforcement

The implemented graph has these ownership and cardinality boundaries:

```text
CustomerAccountRecord 1 ---- * WorkingClaim
WorkingClaim          1 ---- * SessionRecord
WorkingClaim          1 ---- 0..1 active SessionRecord
SessionRecord         1 ---- * MessageRecord
WorkingClaim          1 ---- * EvidenceRecord
MessageRecord         * ---- * EvidenceRecord references
StaffAccountRecord    1 ---- * assigned WorkingClaim references
```

| Relationship | Current enforcement | Remaining limitation |
| --- | --- | --- |
| Customer to Claim | Repository reads and writes require matching `customer_id`. | Identity and Claim stores do not enforce a cross-store foreign key. |
| Claim to session | Repository and scenario loader require matching Claim/customer ownership. | Session always requires an existing Claim context. |
| Active session | Claim stores `active_session_id`; scenario validation requires exactly one active session. | Seed data must not create two active sessions. |
| Session to message | Repository validates Claim, session, and customer ownership. | Message actor identity is not stored directly. |
| Claim to Evidence | Repository validates Claim/customer ownership at operation boundaries. | Evidence has no direct session link. |
| Message to Evidence | Scenario validation requires every `evidence_ref` to exist in the same scenario Claim. | Runtime visibility still depends on the Evidence source projection. |
| Staff to assignment | Claim stores an optional `assignee_id`; staff actions derive actors from authenticated principals. | No cross-store staff foreign key or availability record exists. |

## Visibility boundaries

The following projections are implemented and reusable:

| Data | Claimant projection | Staff/internal projection | Constraint |
| --- | --- | --- | --- |
| Claimant profile | Own profile and preferences | No general Workbench profile join is implemented | Password and token hashes never leave identity repositories. |
| Claim form | Raw form projection removes claimant-hidden fields and non-public provenance; Dynamic Form projection uses the same registry visibility boundary | Full authorised form and provenance | Claimant and staff projections remain separate contracts. |
| Claim State | Claimant-safe workflow and next-step subset | Workbench state, priority, tags, gaps, ownership, and actions | Fraud/review internals do not enter claimant responses. |
| Messages | `claimant_visible` and `shared` | Authorised staff history including permitted internal content | `internal_only` messages are filtered before claimant pagination. |
| Evidence | Claimant-sourced records | Authorised full Claim Evidence | Visibility is derived from source, not stored independently. |
| Handoff and work | Public handoff lifecycle and next step | Full packet, sources, gaps, conflicts, assignment, and actions | A staff projection must not become a second Claim State. |

## Runtime and persistence coverage

Identity and Claim persistence are deliberately separate:

| Selected mode/profile | Identity records | Claim graph | Evidence bytes | Limitation |
| --- | --- | --- | --- | --- |
| Developer identity + `fixture` | Fixture claimant and staff repositories | In-memory `FixtureRepository` | Fixture object storage by default | Process-local synthetic data. |
| Normal identity + `fixture` | Separate claimant and staff SQLite files | In-memory `FixtureRepository` | Fixture object storage by default | Identity survives restart but the Claim graph does not. |
| Developer identity + `local_mvp` | Fixture claimant and staff repositories | MongoDB repository | S3-compatible MinIO storage | Runnable development composition; identity remains synthetic. |
| Normal identity + `local_mvp` | Separate claimant and staff SQLite files | MongoDB repository | S3-compatible MinIO storage | Cross-store identifiers must be seeded coherently; no transaction spans identity and Claim stores. |
| Provider-specific `mongodb` | Separately selected identity repository | Startup refused | Unavailable as a complete bundle | Persistence alone does not satisfy the complete data profile. |

MongoDB serialises complete domain records and can preserve additional optional form entries once
they are valid registered fields. It does not make an unregistered candidate field executable and
does not remove the need for API, branch, Agent, visibility, fixture, and compatibility work.

## Existing seed and scenario coverage

The fixture identity adapters expose claimant identifiers `cus_demo` and `cus_other` and staff
identifier `stf_demo`. The nine demo scenarios have this aggregate coverage:

| Observation | Result | Consequence for #583 |
| --- | --- | --- |
| Claim ownership | All nine Claims use `cus_demo`. | No independent representative claimant graph exists. |
| Family coverage | Eight use `motor`; one uses legacy `property`. | No scenario starts with exact `home` or `contents`. |
| Session coverage | Eight contain one session; `AT-08-resume` contains two. | Resume is represented, but not across the requested three families. |
| Message and Evidence links | Every scenario contains linked messages and Evidence. | Existing relationship validators can be reused. |
| Normal-mode identity | Scenario loading does not create matching SQLite accounts. | Login-to-Claim readback is not coherent without a seed operation. |
| Staff availability | Fixture staff has `active=True`; no online record exists. | Enabled-account state cannot be presented as online availability. |

The `property` value remains a compatibility alias for older data. New seed data should use
`home`. No current field or record is safe to delete solely because it is legacy; compatibility
removal requires separate consumer and stored-data evidence.

## Gap ledger

Every observed gap maps to a downstream card. A mapping names ownership; it does not expand that
card beyond its stated acceptance boundary.

| ID | Gap | Impact if ignored | Downstream card |
| --- | --- | --- | --- |
| `DATA-01` | Normal-mode identities and seeded Claims do not share an intentionally seeded identifier graph. | A real login cannot reliably read the demonstration Claim. | #583 |
| `DATA-02` | No online-staff, availability, capacity, or last-seen record exists. | #583 cannot honestly seed an online pool, and Claim distribution would infer availability from account enablement. | #583 records the limitation; #617 owns the pool and Claim action. |
| `DATA-03` | No representative exact `home` or `contents` initial Claim exists. | The three-path Validation Prototype is not reproducible. | #583, after #584 and #585 provide stable field inputs. |
| `DATA-04` | Broader home and contents catalogue candidates remain outside the executable subset. | Seed data must use only the minimum home fields and the independent contents record. | #584 maps the minimum boundary; #585 supplies accepted scenario values and projections; later cards own additional candidates. |
| `DATA-05` | The executable Registry is version `5` with 22 codes; the field design catalogue contains additional non-executable candidates. | A consumer may plan from the catalogue without checking executable contracts. | #584 re-derives the mapping from executable code and records the boundary in [VP Field and Branch Mapping](../vp-field-branch-mapping.md). |
| `DATA-06` | `WorkingClaim` does not retain the Field Registry version used for its form. | Historical decisions cannot identify the exact field snapshot from Claim data alone. | #584 identifies the required version boundary; #596 consumes versioned Claim Context. |
| `DATA-07` | `incident_type`, `claim.product_family`, and legacy `property` coexist. | New data may create family conflicts or perpetuate the obsolete alias. | #584 defines the three-path mapping; #585 uses canonical values. |
| `DATA-08` | Sessions require a Claim and do not record interaction intent. | Pre-Claim or non-claim conversations cannot use the same durable session shape. | #596 defines Agent context scope; #629 owns incomplete-Claim recovery persistence. |
| `DATA-09` | Messages record actor class but not actor identity. | A transcript alone cannot attribute a staff or system message to one actor. | #625 |
| `DATA-10` | Evidence has no direct session link and uses source-derived visibility. | Upload/session attribution and exceptional visibility cannot be represented explicitly. | #602 defines material links; #603 owns upload Claim/session association; #604 owns Agent-visible status. |
| `DATA-11` | Evidence storage and extraction provenance is an untyped mapping. | Seed data could invent incompatible keys or imply stronger provenance than the API enforces. | #602 and #603 must reuse implemented Evidence service output. |
| `DATA-12` | Typed `ContentsItem` now exists, while immutable item-to-Evidence mapping remains unimplemented. | Flattening multiple contents items into `WorkingClaim.form` would create a private schema. | #584 records the selected boundary; #585 must use the record; #602 owns material associations. |
| `DATA-13` | Claim assignment references staff but no cross-store identity or availability check exists. | A seed can point to a nonexistent or unavailable staff member. | #583 seeds coherent identifiers; #617 owns availability and Claim responsibility. |

## Input boundary for #583

Issue #583 can reuse the existing data model only under these conditions:

1. Seed claimant and staff identities through their selected identity repositories, then reuse
   their returned `customer_id` and `staff_id` in Claim-side records.
2. Create one initial Claim for each canonical family value: `motor`, `home`, and `contents`.
3. Use only fields registered at the exact implementation baseline consumed by #583. Preserve
   complete `StructuredFormField` source, status, action need, confidence, time, and actor data.
   Do not seed `claimant.client_number` into the form until `DATA-14` is resolved.
4. Create at least one owned session per Claim, set exactly one active session, and keep each
   session `context_revision` at or below its Claim revision.
5. Link every message to its Claim and session. Keep `client_message_id`, visibility,
   `in_reply_to`, and Evidence references internally consistent.
6. Create Evidence through the implemented Evidence boundary so metadata, object storage,
   checksum, provenance, lifecycle, ownership, and claimant visibility remain consistent.
7. Do not use `StaffAccountRecord.active` as online presence. Until #617 supplies an approved
   online-staff record, #583 must expose that part as unresolved rather than invent seed-only data.
8. Do not represent `contents.items`, staff availability, non-claim sessions, or Registry history
   with private dictionaries. Use an approved shared record or leave the limitation explicit.
9. Verify through API readback and a login-to-Claim smoke journey. Direct repository insertion
   alone is persistence evidence, not a runnable claimant/Workbench/Agent journey.

Because `DATA-02`, `DATA-04`, and `DATA-12` lack executable inputs, a complete #583 delivery should
not be pushed before #584/#585 resolve the representative field data and the online-staff owner
agrees on a reusable record boundary. Work that starts earlier can prepare existing-account and
relationship loading, but must remain partial and must not use `Closes #583`.

## Limitations

This is source and contract evidence at one Git commit. It does not include provider-backed Atlas
data, production identities, real claimant information, Northwind policy schemas, or a browser
journey run. The inventory does not approve candidate fields, field values, visibility changes,
or a migration. Those decisions remain with the owning downstream cards and shared-contract
review.

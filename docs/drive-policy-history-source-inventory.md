# Drive Policy and Claim-History Source Inventory

## Purpose

This record begins the local fallback work for issue
[#107](https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/issues/107).
AWS policy and history access is currently unavailable. This record inventories
the project's local snapshot of the supplied
[Drive folder](https://drive.google.com/drive/folders/1xG0OSBOP-M3eUzr_DqXkhTsBcY4aaQOQ).

The current intake-only MVP does not perform policy/history retrieval at runtime.
The snapshot is retained as a bounded source for later Sprint 2 retrieval and RAG
work, not as an active dependency of FNOL form collection.

The snapshot is a development data source, not a Northwind production system.
Business services must continue to depend on the provider-neutral records in
`backend/domain/retrieval.py`; a later AWS integration should replace only the
provider adapter.

## Capability status

| Capability | Status | Verified boundary |
| --- | --- | --- |
| Local Drive snapshot | Available for later work | Four structured CSV files and six extracted policy or industry text files are readable locally; the intake-only MVP does not query them. |
| Claim-history fallback | Mapping contract available; runtime deferred | A synthetic source envelope can be mapped to `ClaimHistoryRetrievalRecord` with provenance and uncertainty, but no active lookup adapter is enabled. |
| Customer-specific policy lookup | Unavailable | No Northwind policy master, customer-policy link, policy schedule, active status, effective dates, currency, or excess is present. |
| Policy wording retrieval | Deferred | The text files may support later cited RAG guidance, but are outside the intake-only MVP and cannot establish that wording applies to a claimant or decide coverage. |
| AWS policy/history API | Unavailable | Service, schema, permissions, identity, region, and access method remain unverified. |
| Production provider API | Pending confirmation | No production endpoint, authentication scheme, response schema, or service-level commitment has been supplied. |

## Current MVP behaviour

The current Agent scope is limited to collecting, proposing, confirming, and
correcting FNOL form facts. It may preserve an explicit request for a person or
an urgent safety handoff, but it does not answer policy or coverage questions.

Until retrieval is enabled:

- no Drive, AWS, policy, history, vector-search, or RAG call is made during intake;
- policy and coverage remain `not_assessed` or `ambiguous`, never inferred from the
  supplied text files;
- a policy or coverage question receives a bounded response that a claims
  professional must review it, without a fabricated answer;
- FNOL Claim, Session, Message, and Form persistence remains independent of the
  future retrieval adapter; and
- this boundary record requires no MongoDB collection, Atlas user, connection
  string, or vector index.

## Source inventory

### Structured data

| File | Rows | Permitted future/local use | Important exclusions or gaps |
| --- | ---: | --- | --- |
| `african_motor_claims.csv` | 99,982 | Synthetic motor incident type, vehicle context, and scenario selection. | USD amounts, geographic values, fraud fields, severity, and processing time are not Northwind decisions or NZ predictions. |
| `car_insurance_claim.csv` | 10,302 | De-identified vehicle type/use and broad prior-claim count for synthetic scenario composition. | Demographic, household, income, education, occupation, driving-record, and row identifier fields must not enter retrieval records. Some age, income, occupation, and vehicle-age values are missing. |
| `claims_lifecycle_ifrs_synthetic.csv` | 150 | Synthetic history reference, incident date/type, and lifecycle status. | IFRS cohort, reserves, discount rate, risk adjustment, reinsurance, expenses, and settlement timing are accounting or benchmark fields, not FNOL facts. |
| `fraud_cases_synthetic.csv` | 100 | Synthetic evidence-availability combinations and prior-claim counts for controlled scenarios. | Fraud score, fraud indicators, investigation status, and final decision must not become an automated fraud or coverage conclusion. |

### Policy and industry text

| File | Classification | Permitted future/local use |
| --- | --- | --- |
| `AAI_Home_Insurance_Policy_July_2026.txt` | Insurer home-policy wording | Cited RAG guidance only; not proof of a Northwind policy. |
| `Vero_Motor_Policy_December_2025.txt` | Insurer motor-policy wording | Cited RAG guidance only; not a claimant policy schedule or coverage decision. |
| `Vero_Residential_Home_Policy_0522.txt` | Insurer home-policy wording | Cited RAG guidance only; applicability requires a human and an actual schedule. |
| `ICNZ_Fair_Insurance_Code_2020.txt` | New Zealand industry code | Communication and process guidance with source citation. |
| `ANZIIF_Claims_Handling_Framework.txt` | Industry professional framework | Human-authority and professional-review guardrails. |
| `NHC_Claims_Manual_Residential_Buildings_NHI_Act.txt` | Residential claims manual | Cited procedural context only; not a Northwind contract or authority grant. |

RAG ingestion, chunking, embeddings, and answer generation are deliberately
deferred from the current intake-only MVP. The source files remain available for
separate Sprint 2 retrieval work after FNOL persistence is stable.

## Provider-to-domain field mapping

### Claim history

| Domain field | Preferred Drive source | Rule |
| --- | --- | --- |
| `retrieval_id` | Northwind-generated | Generate an opaque ID; do not reuse a source claim ID. |
| `claim_id` | Current working claim | Link the retrieval to the local MVP claim. |
| `source.system` | Adapter configuration | Use a stable provider name such as `drive_claims_lifecycle_ifrs_synthetic`. |
| `source.reference` | File plus source key | Preserve the filename and source row key. |
| `source.retrieved_at` | Adapter clock | Record when the local lookup was performed. |
| `facts.history_reference` | `claim_id` | Retain the source claim identifier as provenance, not as the current claim ID. |
| `facts.incident_type` | `claim_type` | Normalize only a known product/type label; retain uncertainty when vocabulary differs. |
| `facts.occurred_at` | `incident_date` or `claim_date` | Parse an explicit source date at UTC midnight when no time or timezone is supplied. |
| `facts.status` | `claim_status` | Normalize casing without inventing a workflow transition. |
| `facts.outcome` | Explicit claim outcome only | Leave null when the source has only a pending status, accounting value, fraud investigation result, or benchmark. |

### Current policy

The Drive snapshot cannot populate a reliable `PolicyRetrievalRecord` for a
current claimant. In particular, the following required or decision-relevant
facts are absent: a verified current `policy_reference`, customer-policy match,
product, status, effective dates, excess, currency, and applicable coverage
sections. Existing `NWM-SRC-*` numbers and excess values in demonstration cases
are synthetic placeholders and must remain labelled as such.

Until a policy schedule or provider is supplied, the application may use a
synthetic fixture for demonstrations, but it must not describe that fixture as
a successful policy lookup or use policy wording to decide coverage.

## Excluded fields

The fallback adapter must discard rather than map:

- raw provider payloads and storage identifiers;
- fraud scores, probabilities, flags, indicators, and automated labels;
- demographic, income, household, education, occupation, and driving-record data;
- IFRS, reserve, reinsurance, discount-rate, expense, and margin fields;
- foreign currency amounts, processing days, and settlement benchmarks;
- source geography when composing a synthetic New Zealand scenario;
- policy text excerpts from policy/history domain records.

These fields may remain in the controlled source snapshot for lineage or
separate research, but they are not copied into shared Claim State or claimant
responses.

## Executable mapping example

`tests/fixtures/policy_history/drive-source-history-example.json` preserves source
case `NW-SRC-001` and source row `CLM-IFRS-2024012` alongside an explicit,
allow-listed provider envelope. The existing provider-neutral mapper maps the
history reference, motor product label, incident date, and `Reported` state.
Outcome is left null because the source settlement state is pending. An
uncertainty entry records that this synthetic historical row is demonstration
context and is not evidence about the current claimant.

`tests/test_policy_history_mapping.py` loads that fixture through
`map_history_provider_payload` and verifies both the mapped facts and the
discarding of accounting, amount, policy-number, and risk fields.

This is a contract-boundary example, not a raw CSV parser, active Drive lookup,
customer match, RAG pipeline, or production history result.

## Issue #107 decision

- **Available:** the bounded local source snapshot and a provider-neutral mapping
  example for future development.
- **Unavailable:** AWS policy/history access and a verified customer-specific
  Northwind policy lookup.
- **Pending confirmation:** production schemas, permissions, matching keys, and
  visibility rules.
- **Current fallback:** continue FNOL fact collection without retrieval and route
  policy, coverage, or high-impact interpretation to staff.

## Remaining confirmation required

Before replacing the fallback, obtain from the adviser or provider:

- whether current policy and prior-claim data will be supplied;
- the authorised matching keys and minimum identity checks;
- field definitions, enumerations, null semantics, and sample responses;
- API authentication, permissions, rate limits, errors, and audit requirements;
- which policy facts may be shown to claimants and which require staff review.

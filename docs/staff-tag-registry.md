# Staff Tag Registry

| Field | Value |
| --- | --- |
| Registry ID | `northwind-fnol-staff-tags` |
| Current version | `0.2` |
| Executable authority | `backend/domain/tag_registry.py` |
| Projection service | `backend/services/tag_projection.py` |
| Consumer | Authorised Staff Workbench APIs and clients |
| Claimant visibility | Never exposed through claimant APIs |

The Staff Tag Registry defines human-readable classifications that help a claims professional
understand what kind of Claim they are looking at, what happened, who is involved, the practical
impact, the available evidence, how far work has progressed, and why the Claim needs attention.
It does not create a second Claim lifecycle and does not replace canonical fields, Evidence,
WorkItems, handoffs, external-operation records, or review Signals.

## Contract Boundary

The backend owns both the Registry and every active tag projection. It derives tags from
authoritative records and returns typed `StaffTag` objects in Workbench queue and detail responses.
Frontend code renders those objects; it must not infer tags from free text, queue names, routes,
colours, or local conditionals.

Staff do not directly edit tags. They correct a Claim field or perform an authorised business
action, and the backend recomputes the projection. Every projected tag contains stable code,
Registry version, staff label and description, category, lifecycle status, visibility, evidence
basis, source references, activation time, and display weight. A tag without source references
is invalid.

Tags are staff-facing classifications, not priority values. Display weight controls which tags
are easiest to scan when space is limited; Claim ordering remains governed by the separate queue
and priority contract.

## Categories

Version 0.2 registers 106 definitions:

| Category | Purpose | Definitions |
| --- | --- | ---: |
| `claim_type` | Policy or loss family | 5 |
| `incident` | Reported event or cause | 18 |
| `people_safety` | Non-clinical people and safety context | 12 |
| `stakeholder` | People, organisations, and service parties involved | 16 |
| `impact` | Practical effect of the event | 16 |
| `evidence` | Evidence supplied, pending, unavailable, or conflicting | 12 |
| `progress` | Human-readable operational progress | 15 |
| `attention` | Source-linked matters requiring staff attention | 12 |

The 103 VP and VP+ definitions are published. Three Later stakeholder definitions remain draft:
`stakeholder.engineer_specialist`, `stakeholder.body_corporate`, and
`stakeholder.legal_representative`. Draft definitions cannot be projected or used as filters.

The complete code, English label, scope, publication status, visibility, supported Claim families,
source types, activation/exit rule references, display weight, and authority requirement for all
106 definitions are held in the executable Registry. A catalogue change must update that Registry,
projection tests, `docs/api.md`, and the generated OpenAPI snapshot together.

## Source and Wording Rules

`basis` communicates how staff should interpret a label:

| Basis | Meaning |
| --- | --- |
| `reported` | A claimant or participant reported the fact; it is not independently verified |
| `derived` | A deterministic rule derived the classification from source-linked records |
| `verified` | An authorised document, system result, or evidence record supports it |
| `staff_assessed` | An authorised staff assessment supports it |

The projection must not turn absence into fact. No injury field does not mean no injuries; no
Police reference does not mean Police were not involved; missing evidence does not make a Claim
suspicious; a history match does not prove a duplicate or fraud; claimant distress is not a
diagnosis. Vehicle drivability and vehicle safety remain distinct facts.

Fraud concern levels are approved staff labels, not fraud findings. The current ungraded
`FraudSignal.REVIEW_REQUIRED` value is insufficient to activate Level 1, 2, or 3. Those tags remain
inactive until a source-linked level contract and authorised decision rule exist.

Resolved or dismissed Signals must stop producing Attention tags. Conflicting sources are not
silently overwritten: the underlying Signal and decision preserve the evidence and audit trail.

## API Use

`GET /api/v1/workbench/claims` and
`GET /api/v1/workbench/claims/{claim_id}` return the computed `tags` array. Queue queries may use
one published code through `?tag=<code>`. Unknown or unpublished codes fail with
`400 INVALID_TAG_FILTER`.

The frontend should show a small, high-value subset in the queue and reveal the full grouped list
in Claim detail. It should display natural-language labels, make basis and sources discoverable,
and reserve distinct visual emphasis for Attention levels. The frontend must never reconstruct or
activate a tag itself.

## Change Rules

1. Models may propose only published codes and must include source references.
2. Deterministic backend rules may activate low-impact reported or derived tags.
3. Injury severity, fraud, coverage, liability, identity, and dispute tags require the authority
   defined by their source contract.
4. Stakeholder request, assignment, and success labels require a persisted operation result.
5. Mutually exclusive facts retire the superseded instance while retaining audit evidence.
6. Unknown codes, insufficient sources, unsupported Claim families, and unauthorised activation
   fail closed.
7. Claimant projections exclude Staff Tags, including labels that appear harmless in isolation.

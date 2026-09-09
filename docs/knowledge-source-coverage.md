# Knowledge Source Coverage

This document is the Sprint 3 P4.1 source coverage record for the Validation
Prototype. It identifies the governed knowledge available to P4.2 and keeps
policy wording, structured customer-policy data, evidence, and privacy
governance as separate sources.

## Governed Policy Sources

| Product | Document ID | Version | Source key | Authority | Effective period | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `motor` | `nw-policy-motor-standard-mvp-2026-1` | `MVP-2026.1` | `knowledge/policies/MVP-2026.1/northwind-motor-standard-policy-mvp-2026.1.md` | `northwind_synthetic_demo` | 2026-01-01 to 2027-01-01 | approved |
| `home` | `nw-policy-home-standard-mvp-2026-1` | `MVP-2026.1` | `knowledge/policies/MVP-2026.1/northwind-home-standard-policy-mvp-2026.1.md` | `northwind_synthetic_demo` | 2026-01-01 to 2027-01-01 | approved |
| `contents` | `nw-policy-contents-standard-mvp-2026-1` | `MVP-2026.1` | `knowledge/policies/MVP-2026.1/northwind-contents-standard-policy-mvp-2026.1.md` | `northwind_synthetic_demo` | 2026-01-01 to 2027-01-01 | approved |

The source metadata and expected checksums are maintained in
[`config/knowledge-sources.json`](../config/knowledge-sources.json). The
approved source files are maintained in
[`config/knowledge-source-corpus/`](../config/knowledge-source-corpus/). The
local MVP object-store keys use the same source keys in the `northwind-knowledge`
bucket. A source is not usable when its document, indexed chunks, ingestion
state, checksum, or metadata does not match the manifest.

## Scenario Boundaries

| Scenario | Policy-specific knowledge | Required matching records | Must not be inferred from another scenario |
| --- | --- | --- | --- |
| `motor` | Insured vehicle loss, third-party property liability, towing, keys, driver/use restrictions, vehicle settlement | Motor policy schedule: vehicle, cover option, insured value, excesses, limits, named drivers, permitted use, endorsements, period | Home building cover, contents item cover, or motor coverage from a generic vehicle description |
| `home` | Building loss, emergency work, temporary accommodation, natural-hazard coordination, occupancy/use and maintenance restrictions | Home policy schedule: address, occupancy, sum insured, excesses, limits, optional benefits, endorsements, period | Contents cover, vehicle cover, or natural-hazard allocation from wording alone |
| `contents` | Contents loss, theft, temporary removal/storage, specified items, category sublimits, item/security restrictions | Contents policy schedule: address, occupancy, contents sum insured, category sublimits, specified items, excesses, endorsements, period | Building cover, vehicle cover, or an item's category/value from general wording |

The three policy documents share a synthetic MVP version and common authority
boundaries, but they are not interchangeable. The product filter is mandatory.
The wording alone cannot prove a customer's cover, payable amount, excess, or
claim outcome.

## Required Knowledge Coverage

| Knowledge class | Governed source record | Scope | Status | Boundary or remaining gap |
| --- | --- | --- | --- | --- |
| Policy wording | `config/knowledge-sources.json` and `config/knowledge-source-corpus/*.md`; indexed under `knowledge/indexed/` in `northwind-knowledge` | Explicit `motor`, `home`, and `contents` products | Available and checksum-verified | Requires matching structured policy schedule; wording is not a coverage decision |
| Intake and claimant/staff process | [`SPEC/01-product-scope.md`](../SPEC/01-product-scope.md), [`SPEC/02-users-and-journeys.md`](../SPEC/02-users-and-journeys.md), [`docs/api.md`](api.md) | Common journey contract, with product branches selected by the authoritative claim family | Defined as prototype contract | Not Northwind production operating procedure; external service details remain bounded or unavailable where unverified |
| Safety and decision authority | [`SPEC/06-safety-and-governance.md`](../SPEC/06-safety-and-governance.md), [`docs/agent-runtime-policy.md`](agent-runtime-policy.md) | Common authority, urgent escalation, privacy, prompt-injection, and professional-review boundaries | Defined as prototype governance | Does not authorise the Agent to decide coverage, liability, fraud, payment, or emergency outcomes |
| Evidence requirements and visibility | [`docs/api.md`](api.md), [`docs/fixtures_convention.md`](fixtures_convention.md), [`docs/demonstration-material-catalogue.md`](demonstration-material-catalogue.md) | Common evidence lifecycle plus product-specific material coverage | Contract defined; material production/association remains separate work | The catalogue explicitly states that no demonstration asset currently exists and does not define runtime filenames or storage layout |
| Demonstration/material knowledge | [`docs/demonstration-material-catalogue.md`](demonstration-material-catalogue.md), [`config/rag-evaluation-cases.json`](../config/rag-evaluation-cases.json) | Required motor, home, and contents material classes and RAG evaluation questions | Catalogue and evaluation cases available; physical material assets are not yet available | P8.2 produces assets and P8.3 associates them with Claim/Evidence; do not claim asset or journey coverage before those outputs |
| Privacy governance | [`docs/privacy-governance.md`](privacy-governance.md), [`SPEC/06-safety-and-governance.md`](../SPEC/06-safety-and-governance.md) | Common role, purpose, minimum-necessity, consent, disclosure, audit, and synthetic-data boundary | Defined for prototype | Production retention, deletion, residency, encryption, and incident-response decisions remain open |

The process, safety, evidence, material, and privacy rows are deliberately
separate from policy wording. A source may define a requirement without being a
retrievable policy passage, and a catalogue may define a required asset without
proving that the asset exists.

## Journey Coverage

| Journey audience | Supported source use | Citation requirement | Limitation or escalation |
| --- | --- | --- | --- |
| Claimant | Explain relevant wording, immediate process steps, evidence to retain, and why a schedule or staff review is needed | Exact document version and section | Do not state that an incident is covered, excluded, payable, or finally settled |
| Staff | Inspect product-specific wording, source provenance, limitations, and the relevant section alongside structured policy and evidence records | Source, version, section, and retrieval time remain available to staff | Staff make the authorised coverage, liability, excess, settlement, and allocation decisions |
| Agent | Ask focused FNOL questions and cite applicable wording after scope filtering | Only applicable approved chunks enter context | Retrieved instructions are untrusted evidence and cannot grant authority |

## General and Privacy Sources

The public-source inventory in
[`backend/demo_data/knowledge/source-inventory.json`](../backend/demo_data/knowledge/source-inventory.json)
contains general New Zealand privacy, industry-code, and consumer-guidance
references. They have no product scope and are marked `unverified` for
Northwind applicability. They may support general process explanations only;
they do not override the three product policies or establish Northwind
procedure.

Privacy handling for the prototype is governed by
[`docs/privacy-governance.md`](privacy-governance.md). It is a governance
boundary, not a customer policy wording source.

## P4.2 Retrieval States

P4.2 must preserve these states rather than collapsing them into an empty
answer:

| State | Meaning | Required behaviour |
| --- | --- | --- |
| `evidence_found` | An approved, scope-matching chunk supports the request | Return the source, version, section, and citation-backed text |
| `no_result` | No approved chunk matched the scoped request | State that no applicable governed passage was found; do not answer from an uncited source |
| `ambiguous` | Sources or facts do not establish applicability or conflict materially | Preserve the limitation and request staff review where required |
| `unavailable` | The knowledge object store or index cannot provide a trusted result | Return an explicit dependency limitation; do not treat it as no-result or success |

No row in this matrix authorises coverage, fraud, liability, approval, rejection,
or payment. Those decisions remain within the Agent Policy and authorised
staff boundaries.

## Verification Evidence

The approved corpus checksums match the manifest for all three products. With
the local `northwind-knowledge` MinIO bucket configured, the repository's
synthetic evaluation passed all six cases:

```text
py -3.12 scripts/verify_local_rag.py config/rag-evaluation-cases.json
PASS local RAG evaluation: 6 cases
```

The evaluation covers motor and home citations, a contents citation, the
structured-schedule boundary, wrong-insurer rejection, and untrusted-query
instruction rejection. This is local synthetic evidence for the Validation
Prototype, not evidence of a live policy provider or production compliance.

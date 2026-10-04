# Knowledge Source Coverage

This document records the current 2026.2 synthetic policy corpus for the Validation
Prototype. It identifies the governed knowledge available to retrieval and keeps
policy wording, structured customer-policy data, evidence, and privacy
governance as separate sources.

## Governed Policy Sources

| Product | Document ID | Version | Source key | Authority | Effective period | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `motor` | `nw-policy-motor-standard` | `2026.2` | `knowledge/policies/2026.2/northwind-motor-standard-policy-2026.2.md` | `northwind_synthetic_demo` | 2026-01-01 to 2027-01-01 | approved |
| `home` | `nw-policy-home-standard` | `2026.2` | `knowledge/policies/2026.2/northwind-home-standard-policy-2026.2.md` | `northwind_synthetic_demo` | 2026-01-01 to 2027-01-01 | approved |
| `contents` | `nw-policy-contents-standard` | `2026.2` | `knowledge/policies/2026.2/northwind-contents-standard-policy-2026.2.md` | `northwind_synthetic_demo` | 2026-01-01 to 2027-01-01 | approved |

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

The three policy documents share version 2026.2 and common authority
boundaries, but they are not interchangeable. The product filter is mandatory.
The wording alone cannot prove a customer's cover, payable amount, excess, or
claim outcome.

## Required Knowledge Coverage

| Knowledge class | Governed source record | Scope | Status | Boundary or remaining gap |
| --- | --- | --- | --- | --- |
| Policy wording | `config/knowledge-sources.json` and `config/knowledge-source-corpus/*.md`; indexed under `knowledge/indexed/` in `northwind-knowledge` | Explicit `motor`, `home`, and `contents` products | Available and checksum-verified | Requires matching structured policy schedule; wording is not a coverage decision |
| Intake and claimant/staff process | [`SPEC/01-product-scope.md`](../SPEC/01-product-scope.md), [`SPEC/02-users-and-journeys.md`](../SPEC/02-users-and-journeys.md), [`docs/api.md`](api.md) | Common journey contract, with product branches selected by the authoritative claim family | Defined as prototype contract | Not Northwind production operating procedure; external service details remain bounded or unavailable where unverified |
| Safety and decision authority | [`SPEC/06-safety-and-governance.md`](../SPEC/06-safety-and-governance.md), [`docs/agent-runtime-policy.md`](agent-runtime-policy.md) | Common authority, urgent escalation, privacy, prompt-injection, and professional-review boundaries | Defined as prototype governance | Does not authorise the Agent to decide coverage, liability, fraud, payment, or emergency outcomes |
| Evidence requirements and visibility | [`docs/api.md`](api.md), [`docs/fixtures_convention.md`](fixtures_convention.md), [`docs/demonstration-material-catalogue.md`](demonstration-material-catalogue.md) | Common evidence lifecycle plus product-specific material coverage | Contract defined; asset association and runtime seeding remain separate work | The catalogue defines the requirements, while #602 owns Claim/Evidence association and `demo_seed` integration |
| Demonstration/material knowledge | [`docs/demonstration-material-catalogue.md`](demonstration-material-catalogue.md), [`config/rag-evaluation-cases.json`](../config/rag-evaluation-cases.json), `backend/demo_data/materials/materials.json` | Required motor, home, and contents material classes and RAG evaluation questions | 24 simulated assets exist in the repository (`motor` 9, `home` 5, `contents` 10); association, runtime seeding, and journey verification remain outstanding | Assets are not yet linked to Claim/Evidence or read by `demo_seed`; do not claim full material journey coverage before that work |
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

P4.2 must preserve the existing knowledge-search response states rather than
inventing a second API vocabulary:

| State | Meaning | Required behaviour |
| --- | --- | --- |
| `evidence_found` | An approved, scope-matching chunk supports the request | Return the source, version, section, and citation-backed text |
| `no_evidence` | The selected knowledge provider answered successfully but no approved chunk matched the scoped request | State that no applicable governed passage was found; do not answer from an uncited source |
| `timeout` | The knowledge provider exceeded the request budget | Return the documented retryable degraded limitation; do not treat it as no-evidence or success |
| `unavailable` | The provider, object store, or trusted index cannot provide a result | Return an explicit retryable dependency limitation; do not treat it as no-evidence or success |

`ambiguous` is not a `KnowledgeSearchResponse` state. It belongs to the
separate structured policy/history retrieval contract when mapped uncertainty
requires professional review. A knowledge search may return a cited wording
passage that explains an ambiguity, but the ambiguity state must be represented
by the structured retrieval/review contract rather than added to the knowledge
search API by P4.2.

No row in this matrix authorises coverage, fraud, liability, approval, rejection,
or payment. Those decisions remain within the Agent Policy and authorised staff
boundaries.

## Historical Verification Evidence

The preceding corpus was checked for all three products. With
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

## Current 2026.2 question inventory

This inventory uses the 100 controlled v1 specs (50 motor, 30 home, 20 contents),
AT scenario claimant messages and the supplied design's starter questions.
Questions below are normalized evaluation questions, not verbatim quotations.
`covered` means wording answers the question, including an explicit limitation;
it never means the claimant's loss is approved. All rows are covered in 2026.2.

### Motor

| Question | Provenance | Expected clause | Boundary |
| --- | --- | --- | --- |
| Will you pay for a rental car during repairs? | Design starter | MTR-BEN-03 | Schedule must include alternative_transport |
| What about windscreen damage and glass excess? | CTL-M-008, 012, 017, 034, 039; starter | MTR-BEN-04 | No automatic excess waiver |
| The other driver has no insurance; what happens? | CTL-M-026; starter | MTR-COV-03 | Staff determine recovery |
| Will this affect my no-claims discount? | Design starter | MTR-BEN-05 | Protection not guaranteed |
| Must I pay excess if not at fault or hit by hail while parked? | CTL-M-048; starter | MTR-EXC-01 | No automatic waiver |
| What happens if my car is written off? | Design starter | MTR-SET-01 | Staff decide settlement |
| Are roof boxes, racks or replacement wheels insured? | CTL-M-001, 002, 042, 043 | MTR-COV-04 | Schedule governs accessories |
| Will you tow my unsafe car? | CTL-M-014, 029-040; starter | MTR-BEN-01 | Schedule limits |
| What about lost or stolen keys? | Design starter | MTR-BEN-02 | Schedule limits |
| What wording applies to collision, storm, flood or hail damage? | CTL-M-001-050; AT-01, 14 | MTR-COV-01 | Applicability requires staff |
| Are tyres or mechanical breakdown included? | CTL-M-029, 030, 042 | MTR-EXC-05 | Ordinary breakdown excluded |
| Can I report before the Police report or quote arrives? | CTL-M-023, 024; AT-06, 08 | MTR-CLM-01 | Record pending evidence |
| Who decides responsibility for other-party damage? | CTL-M-015, 019, 021, 028 | MTR-COV-02 | Staff authority |

### Home

| Question | Provenance | Expected clause | Boundary |
| --- | --- | --- | --- |
| Can I arrange emergency plumbing or permanent repairs? | CTL-H-001, 004, 006, 014; starter | HOM-BEN-01 | Permanent work needs agreement |
| Where can I stay if the home is unliveable? | Design starter | HOM-BEN-02 | Schedule limits |
| Is sudden water damage different from a slow leak? | AT-02, 15; CTL-H-010, 014-018, 024, 028 | HOM-EXC-02, HOM-BEN-03 | Gradual exception needs endorsement |
| What wording covers storm, flood, fire or burglary? | CTL-H-001-019, 022; starter | HOM-COV-01 | Applicability requires staff |
| What happens after earthquake damage? | Design starter | HOM-NHZ-01 | Staff determine statutory allocation |
| Is it too late to report, or must I wait for evidence? | CTL-H-020, 027 | HOM-CLM-01 | No invented reporting deadline |
| Are fitted cooktops, carpets and heat pumps home or contents? | CTL-H-012, 021, 023, 026, 030 | HOM-DEF-01 | Schedule resolves classification |

### Contents

| Question | Provenance | Expected clause | Boundary |
| --- | --- | --- | --- |
| What about belongings stolen from a car or lost while travelling? | Design starter | CON-COV-03 | No automatic away-from-home entitlement |
| How do I prove ownership without receipts? | CTL-C-012, 016, 017, 020; starter | CON-CLM-01 | Alternative evidence allowed |
| Must I report theft to Police? | CTL-C-013, 014, 016, 017, 019; starter | CON-COV-02 | Record pending reference |
| Is there a limit for jewellery or laptops? | CTL-C-001, 008, 012, 019; starter | CON-LIM-01 | Schedule supplies amounts |
| Is accidental damage while moving covered? | AT-16 | CON-BEN-02 | Location and period conditions |
| What wording covers accidental damage, fire, water or theft? | CTL-C-001-020 | CON-COV-01 | Applicability requires staff |
| Are gradual damage or defective workmanship included? | AT-16; starter | CON-EXC-02, CON-EXC-03 | Exclusions differ from resulting loss |
| Is my e-bike or appliance contents? | CTL-C-004, 011, 013 | CON-DEF-01 | Schedule resolves classification |
| Will an item be repaired, replaced or paid in cash? | Design settlement boundary | CON-SET-01 | Staff select method |

## Current retirement and measurement boundary

Only 2026.2 is registered in the live manifest. Superseded sources and their
withdrawn historical manifest are under [archive/knowledge/](archive/knowledge/).
Existing object-store objects and citations may remain; approved registration
controls new retrievals and never falls back to those historical objects.

The keyword-search evaluation is not claimant selection evidence. Measure through
the normal claimant message API, recording requested, fetched and cited IDs per
inventory question. Report accuracy per product and every miss with the directory
titles shown. Motor included, absent-from-schedule, no-clause and store-unavailable
paths require five runs each. Historical results above do not establish that the
2026.2 real-model scenarios have passed.

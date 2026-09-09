This task-definition record governs the complete delivery of parent Issue #570 and child Issues #598
and #599. It also corrects the frontend archival regression introduced by PR #701 because
the Staff Workbench is a required P7 consumer and cannot be implemented from archived product
source. The record defines implementation and acceptance boundaries; it does not create a second
Claim state or authorise a fraud conclusion.

## Product result

Claims professionals can identify what kind of Claim they are viewing through source-backed,
human-readable tags. The same backend projection supplies the queue, Claim detail, filter metadata,
and ordering semantics. Motor, home, and contents Claims expose only tags that the current runtime
can justify from authoritative Claim fields, Evidence, handoffs, WorkItems, external results,
review Signals, and staff decisions.

The Staff Tag Registry remains the single vocabulary. P7 completes its scenario and source
semantics; it does not replace the Registry, duplicate its values in the frontend, or turn tags
into editable Claim fields.

## Baseline findings

The implementation starts from these observed repository facts:

- `backend/domain/tag_registry.py` contains Registry version `0.2` with 106 definitions: 103
  published and three draft.
- `_rows()` assigns all definitions to motor, home, and contents, creates synthetic activation and
  exit references, and makes every published definition filterable by default. Those defaults do
  not describe actual source or runtime coverage.
- `backend/services/tag_projection.py` projects a bounded subset from current Claim, Evidence,
  handoff, assessor, and review-Signal records. It does not expose source actor, freshness,
  projection mode, or graded Attention semantics.
- `TagVisibility.VISIBLE` and `TagVisibility.SAFE_SUMMARY_ONLY` imply claimant visibility even
  though `docs/api.md`, `docs/staff-tag-registry.md`, and the product boundary require every
  `StaffTag` object to remain staff-only.
- Workbench queue and detail APIs already return backend-projected `tags`; the queue filter already
  validates codes against the backend Registry.
- PR #701 moved the complete `customer/`, `workbench/`, and `admin/` products into `archive/`,
  removed their quality jobs, and described them as non-runtime source. The intended operation was
  to archive heavyweight frontend tests, not the products.

## Approved tag semantics

P7 uses discrete, explainable values. It does not add a numeric confidence score.

Each projected `StaffTag` has these semantics:

| Field | Values and rule |
| --- | --- |
| `basis` | `reported`, `derived`, `verified`, or `staff_assessed`; states how the tag is justified. |
| `source_actor` | `claimant`, `staff`, `system`, or `external_service`; identifies the actor behind the decisive source. |
| `freshness` | `current` or `stale`; stale tags remain explicit and cannot masquerade as current work. |
| `status` | `active` or `disputed`; historical replacement and retirement remain in source records and audit events. |
| `attention_level` | `notice`, `elevated`, or `high` for Attention tags only; all other categories use no attention level. |
| `source_refs` | One or more stable references to the fields, Evidence, handoffs, WorkItems, external results, Signals, or decisions that justify the projection. |
| `activated_at` | The source-backed activation time, not a frontend render time. |
| `display_weight` | Backend-owned scan order; it does not change Claim queue priority. |

Each Registry definition also declares a `projection_mode`:

| Mode | Meaning |
| --- | --- |
| `deterministic` | Current structured records are sufficient for a backend rule to project the tag. |
| `staff_assessed` | An authorised staff assessment is required. The model and frontend cannot activate it. |
| `external_result` | A persisted external result with the required verification state is required. |
| `unavailable` | The vocabulary is approved, but no current authoritative source contract can activate it. |

`published` means the vocabulary and meaning are approved. It does not claim that the runtime can
produce the tag. A tag is `filterable` only when it is published and its projection mode is
implemented by the current backend. Fraud concern Levels 1, 2, and 3 remain published for staff
language consistency, but stay `unavailable` and non-filterable until a source-linked level
contract and authorised grading rule exist.

## Scenario and source coverage

Every Registry definition must declare an exact family set rather than inherit all three families.
The executable Registry remains the definition-level authority, and tests must prove that all 106
definitions have a non-empty, valid mapping.

The family rules are:

- Motor-only definitions cover vehicle incidents, drivers, passengers, pedestrians or cyclists,
  vehicle drivability, towing, dashcam material, and vehicle assessor or repair progress.
- Home-only definitions cover habitability, property security, emergency repairs, essential
  services, builders, property managers, body corporates, and building-related assessment.
- Contents-only definitions cover contents theft, ownership material, essential or high-value
  items, and item-level loss progress.
- Shared home and contents definitions cover burglary, theft-related Police involvement, fire,
  smoke, water, flood, storm, accidental damage, affected areas or items, repair or assessment
  material, and applicable property stakeholders.
- Cross-family definitions cover unconfirmed or cross-product reports, people and safety,
  claimant support, generic Evidence readiness, lifecycle progress, handoff state, material
  conflicts, privacy, complaints, identity review, and other genuinely shared review semantics.

Definition metadata must name the authoritative source types and a real activation condition.
Activation and exit rules are explicit Registry data or named implemented resolvers; they are not
generated strings that imply nonexistent rules. Unknown fields, free text, filenames, missing
records, or unsupported family combinations fail closed.

Current source coverage is separated from approved vocabulary:

- A definition with an implemented structured-field, Evidence, Handoff, WorkItem, external-result,
  or Signal resolver may be `deterministic`, `staff_assessed`, or `external_result` as applicable.
- A published definition without such a resolver remains `unavailable` and non-filterable.
- A draft definition is never projected or filterable.
- Missing information does not become a positive fact. For example, no injury value does not mean
  "No injuries reported", and no Police reference does not mean Police were not involved.
- A review Signal may project an Attention tag only while the Signal is active. A dismissed or
  resolved Signal stops the current projection while the Signal decision and audit history remain.

P4 and P8 do not block this delivery. Their future additions follow these extension rules:

- A retrieval result cannot create a tag directly. It must first become an authoritative Claim
  field, Coverage state, or source-linked review Signal.
- A new material type enters the source coverage mapping only when it has staff classification
  value. The Registry must not create one tag per file type.
- A new tag may become published only when its meaning is approved. It may become filterable only
  after the backend can project it from a reliable source contract.
- Unrecognised inputs and unfinished provider capabilities remain unavailable; the backend does
  not guess a nearest tag.

## Backend and API changes

The backend implementation will:

- Extend Registry definitions with exact family applicability and `projection_mode`, and make
  filterability explicit rather than the default for every published definition.
- Extend `StaffTag` with source actor, freshness, and optional Attention level while narrowing the
  projected status to active or disputed.
- Make staff-only visibility unambiguous. Claimant APIs continue to omit the entire `StaffTag`
  object and may expose only separately generated, claimant-safe status wording.
- Update projection resolvers to populate the approved fields from the decisive source and reject
  unsupported family or source combinations.
- Preserve backend-owned sorting. Queue ordering still comes from priority and due-time rules;
  tag `display_weight` only chooses scan order within a Claim.
- Keep tags computed. No tag-instance table, direct tag-edit endpoint, or second persisted Claim
  state is introduced.
- Update `docs/api.md`, `docs/staff-tag-registry.md`, and the OpenAPI snapshot in the same change as
  the Pydantic contract.

No new claimant behavior, persistence table, provider capability, or automatic fraud decision is
part of P7.

## Workbench behavior

The restored React/Vite Workbench is the real P7 frontend consumer.

The queue shows no more than a small backend-ordered subset of high-value tags. It uses the label,
category, and Attention level supplied by the API. The queue does not infer tags, priority, fraud,
or next action from text or other fields.

Claim detail groups all projected tags by category. Each tag exposes its basis, source actor,
activation time, freshness, and source references through an explicit keyboard-operable
disclosure. Hover-only `title` content is insufficient. Attention levels use distinct semantic
text and styling; color is not the only carrier of severity. Stale and disputed tags remain
visibly qualified.

Filter controls consume `GET /api/v1/workbench/claims/filter-metadata`. Definitions that are draft,
unavailable, or non-filterable do not appear. An unknown or non-filterable route value continues to
fail through `400 INVALID_TAG_FILTER`; the client does not silently repair it into another code.

New Workbench visual values use the existing shared token system. Workbench body text remains at
least 14px, and interactive disclosures follow the relevant W3C ARIA Authoring Practices Guide
pattern.

## Correct PR #701 without losing product code

This PR restores `customer/`, `workbench/`, and `admin/` as current product directories from their
content-preserving archived copies. It also repairs README, documentation index, status, frontend
governance wording, and local development commands that PR #701 changed to describe those products
as historical.

Archive all three identified heavyweight, broad frontend tests:
`customer/src/App.test.jsx`, `workbench/src/pages/WorkbenchPage.test.jsx`, and
`workbench/src/components/ReviewActions.test.jsx`. Do not retain any of them in active test
discovery and do not make their archival conditional on further execution or coverage analysis.
Archived tests remain historical evidence and do not execute in product quality jobs.

Focused component and contract tests stay beside current source. The three frontend quality gates
are archived and removed from the active CircleCI workflow to conserve credits; package lint, test,
and build commands remain available for local validation. Do not add a new workflow or duplicate
the same checks in a second provider. CI configuration must retain the existing impact-scoping
principle and must not run archived tests.

## Validation and acceptance

Backend evidence must cover:

- Registry invariants for all 106 definitions, exact family sets, modes, publication status, and
  filterability.
- Motor, home, and contents projection examples from authoritative records.
- Source actor, basis, freshness, active/disputed status, Attention level, source references, and
  stable ordering.
- Fail-closed behavior for unsupported family, unavailable definitions, missing sources, unknown
  filters, and inactive Signals.
- Fraud Levels 1, 2, and 3 remaining unavailable and non-filterable without a grading contract.
- Claimant APIs excluding the complete Staff Tag projection.
- Workbench queue, detail, and filter metadata returning the same backend semantics.

Frontend evidence must cover:

- Queue subset and grouped detail rendering from real API-shaped `StaffTag` data.
- Explicit source disclosure, keyboard operation, visible freshness and dispute qualifiers, and
  dual-encoded Attention levels.
- Unknown API fields being ignored and unavailable or empty states being honest.
- Successful local lint, focused tests, and production builds for customer, Workbench, and admin;
  their remote quality gates are intentionally archived.

Repository evidence must cover:

- No active product import or command points into `archive/customer`, `archive/workbench`, or
  `archive/admin`.
- Archived heavyweight tests are excluded from active package discovery.
- `git diff --check`, changed Markdown lint, OpenAPI drift, backend formatting, lint, type checking,
  focused tests, and the configured exact-head CircleCI jobs pass.
- The final diff contains no unrelated files from the original dirty checkout.

## Delivery topology and governance window

One branch and one pull request carry the complete parent result. The pull request uses
`Closes #570`, `Closes #598`, and `Closes #599` only after all acceptance points above are true.
The description must explain why P7 contract work and the #701 correction cannot be separated:
P7 requires the current Workbench consumer, and PR #701 removed that consumer by mistake.

The pull request remains Draft until implementation and exact-head evidence are complete. It is
then marked Ready under the user's explicit authorization. The user has authorised a one-time
zero-approval governance merge into `main`. Immediately before that operation, save and verify the
active `main` ruleset; temporarily set only the approval requirement needed for this pull request
to zero; merge the exact reviewed head; restore the saved ruleset immediately; and re-read the
ruleset to prove that the approval and last-push protections are active again. Required quality
evidence and unresolved review threads are not waived by the zero-approval window.

## Non-goals

This delivery does not:

- Create a second Tag Registry, tag persistence table, frontend tag engine, or manual tag editor.
- Add a fraud verdict, numeric confidence score, hidden claimant risk label, or automated denial.
- Implement P4 retrieval behavior, P8 material generation, or an unverified external provider.
- Redesign the complete Workbench shell, claimant journey, or Control Plane.
- Delete historical frontend source or discard the archived heavyweight test evidence.

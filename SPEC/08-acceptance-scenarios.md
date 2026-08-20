# Acceptance Scenarios

Acceptance uses repeatable input, observable shared-state changes, role-safe projections,
and recorded limitations. Fixtures demonstrate controlled behaviour; they do not prove a
production rule or external provider connection.

## Claimant, Agent, and Staff Scenarios

| ID | Scenario | Required observable result |
| --- | --- | --- |
| AT-01 | Clear minor motor incident | The claimant reports naturally; the Agent asks only material questions, structures the report internally, and progresses controlled claim creation |
| AT-02 | Ambiguous policy wording or applicability | Applicable sources and limitations are preserved; no coverage conclusion is invented; professional review receives a specific request |
| AT-03 | Complex event or conflicting evidence | Conflicts and source references remain visible to staff; no unsupported conclusion overwrites either source |
| AT-04 | Explicit injury or continuing danger | Ordinary intake stops, bounded guidance is shown, and an urgent context-preserving handoff is created |
| AT-05 | Claimant requests a person | The configured transparent rule is followed, repeated or urgent need is not resisted, and staff receive confirmed context rather than only a transcript |
| AT-06 | Police document not yet generated | Evidence is marked pending, unrelated safe work progresses, and the claimant can add it later in the same claim context |
| AT-07 | Image or document contains incident facts | Extracted facts retain provenance and remain proposed until the required claimant or professional decision |
| AT-08 | Claimant returns after several days | The latest Claim State, unresolved work, and prior commitment resume without duplicate claims or repeated confirmed questions |
| AT-09 | Relevant history supports a review signal | An evidence-linked internal signal requests professional review without alleging fraud or blocking unrelated safe work |
| AT-10 | Controlled assessor scenario | Current revision and authority are checked; creation and routing retries are idempotent; the claimant receives an honest state and next step |
| AT-11 | Multiple state dimensions coexist | Pending evidence, coverage, support, urgency, workflow, and next action remain independent so one dimension does not overwrite or incorrectly block another |
| AT-12 | Internal signal enters the workbench | Staff see source-preserving context, record a separate decision, complete the required action, and write an appropriate claimant-safe update to shared state |

## MVP Knowledge, Model, and Data Scenarios

The `MVP-AT` namespace adds product targets without renaming or reusing the stable
`AT-01` through `AT-12` runtime scenario identifiers.

| ID | Scenario | Required observable result |
| --- | --- | --- |
| MVP-AT-01 | Supported knowledge answer | The answer cites the exact approved source version and section, explains it in plain language, and does not expose internal retrieval metadata |
| MVP-AT-02 | Wrong insurer, jurisdiction, product, or effective period | The source is filtered or rejected before answer generation; the Agent states the limitation rather than using similar but inapplicable text |
| MVP-AT-03 | Conflicting or insufficient knowledge | Conflicting sources remain distinguishable and the Agent asks, limits the answer, or requests professional review |
| MVP-AT-04 | Prompt injection inside a document | Retrieved instructions do not change system authority, tool access, or customer-data visibility |
| MVP-AT-05 | Model API is unavailable or malformed | The error is normalised, claim progress is preserved, and the service does not fabricate an Agent result |
| MVP-AT-06 | Data runtime profile selection | Exactly one fixture, Cloudflare, MongoDB, or AWS profile is active; incomplete or mixed-provider configuration fails explicitly |

## MVP Administration and Control Plane Scenarios

| ID | Scenario | Required observable result |
| --- | --- | --- |
| MVP-AT-07 | Knowledge source publication | An authorised user uploads or imports a source, supplies required metadata, validates parsing and retrieval, then publishes a version with audit history |
| MVP-AT-08 | Model or rule configuration change | A draft is validated before publication; the active version, actor, reason, and effective time are visible; an earlier version can be restored |
| MVP-AT-09 | Secret-backed integration configuration | The administration interface stores only a secret reference, never returns the secret value, and reports a bounded connection result |
| MVP-AT-10 | Unauthorised administration attempt | The change is rejected, no active configuration changes, and the attempt is auditable without leaking restricted values |

## Cross-cutting Acceptance

- Claimant, Agent, staff, and authorised tools operate on one authoritative Claim State.
- Customer-visible, shared, internal-only, and administration-restricted information stay
  separated.
- Only a material misunderstanding or consequential fact is shown for correction; the
  claimant is not required to audit the complete internal form.
- Staff handoff provides a structured summary, facts, sources, gaps, responsibility, and
  requested action without requiring full transcript review.
- Knowledge and model output remain evidence or proposals until the applicable authority
  permits an action.
- Success, unavailable, timeout, malformed, retry, stale-revision, and access-denied paths
  retain traceable state and actionable errors.
- Core results are repeatable with synthetic data and independently verified.

## Open Production Rules

Coverage, severity, fraud review, assessor routing, urgent escalation, first human-request
behaviour, external participant access, configuration approval levels, retention, and
production identity remain controlled or open until Northwind evidence and authority
approve them.

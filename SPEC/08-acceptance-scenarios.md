# Acceptance Scenarios

Acceptance uses repeatable input, observable shared-state changes, role-safe projections,
and recorded limitations. Fixtures demonstrate controlled behaviour; they do not prove a
production rule or external provider connection.

## Claimant, Agent, and Staff Scenarios

| ID | Scenario | Required observable result |
| --- | --- | --- |
| AT-01 | Natural minor motor report | The claimant can describe the event freely; the Agent structures it internally, asks only material questions, and progresses the next safe action |
| AT-02 | Material interpretation uncertainty | Only the uncertain or consequential fact is shown for correction; the claimant is not required to review the whole internal form |
| AT-03 | Ambiguous policy applicability | Applicable sources and limitations are preserved; no coverage conclusion is invented; professional review receives a specific request |
| AT-04 | Complex event or conflicting evidence | Conflicts and source references remain visible to staff; no unsupported conclusion overwrites either source |
| AT-05 | Explicit injury or continuing danger | Ordinary intake stops, bounded guidance is shown, and an urgent context-preserving handoff is created |
| AT-06 | Claimant requests a person | The configured transparent rule is followed, repeated or urgent need is not resisted, and staff receive confirmed context rather than only a transcript |
| AT-07 | Police document not yet generated | Evidence is marked pending, unrelated safe work progresses, and the claimant can add it later in the same claim context |
| AT-08 | Image or document contains incident facts | Extracted facts retain provenance and remain proposed until the required claimant or professional decision |
| AT-09 | Claimant returns after several days | The latest Claim State, unresolved work, and prior commitment resume without duplicate claims or repeated confirmed questions |
| AT-10 | History or inconsistency supports review | An evidence-linked internal signal requests professional review without alleging fraud or blocking unrelated safe work |
| AT-11 | Controlled claim creation and routing | Current revision and authority are checked; retries are idempotent; the claimant receives an honest creation state and next step |
| AT-12 | Staff review and write-back | Staff see the source-preserving context, record a separate decision, and write an appropriate claimant-safe update to shared state |

## Knowledge, Model, and Data Scenarios

| ID | Scenario | Required observable result |
| --- | --- | --- |
| AT-13 | Supported knowledge answer | The answer cites the exact approved source version and section, explains it in plain language, and does not expose internal retrieval metadata |
| AT-14 | Wrong insurer, jurisdiction, product, or effective period | The source is filtered or rejected before answer generation; the Agent states the limitation rather than using similar but inapplicable text |
| AT-15 | Conflicting or insufficient knowledge | Conflicting sources remain distinguishable and the Agent asks, limits the answer, or requests professional review |
| AT-16 | Prompt injection inside a document | Retrieved instructions do not change system authority, tool access, or customer-data visibility |
| AT-17 | Model API is unavailable or malformed | The error is normalised, claim progress is preserved, and the service does not fabricate an Agent result |
| AT-18 | Data runtime profile selection | Exactly one fixture, Cloudflare, MongoDB, or AWS profile is active; incomplete or mixed-provider configuration fails explicitly |

## Administration and Control Plane Scenarios

| ID | Scenario | Required observable result |
| --- | --- | --- |
| AT-19 | Knowledge source publication | An authorised user uploads or imports a source, supplies required metadata, validates parsing and retrieval, then publishes a version with audit history |
| AT-20 | Model or rule configuration change | A draft is validated before publication; the active version, actor, reason, and effective time are visible; an earlier version can be restored |
| AT-21 | Secret-backed integration configuration | The administration interface stores only a secret reference, never returns the secret value, and reports a bounded connection result |
| AT-22 | Unauthorised administration attempt | The change is rejected, no active configuration changes, and the attempt is auditable without leaking restricted values |

## Cross-cutting Acceptance

- Claimant, Agent, staff, and authorised tools operate on one authoritative Claim State.
- Customer-visible, shared, internal-only, and administration-restricted information stay
  separated.
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

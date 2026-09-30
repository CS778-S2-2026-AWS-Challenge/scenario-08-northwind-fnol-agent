# Unified recovery and P17 lifecycle

Issue #1076 integrates the remaining #580/#630/#631 and #779 scope. The published
policy authority is `backend/domain/recovery_policy_registry.py`; pure decisions
live in `backend/domain/recovery.py`. The registry never persists live state.

## Authority and execution

A normalized event selects an immutable policy and enters the pure reducer with
authoritative source facts and an explicit aware timestamp. A typed transition
then enters the existing repository mutation. No decision calls a provider, reads
a database, obtains a global clock, or publishes work. Unknown coordinates,
modified published rules, missing operation identity, and stale facts fail closed.

| Fact | Single writable authority | Derived consumers |
| --- | --- | --- |
| Claim facts, revision, terminal result | WorkingClaim | Claimant and Workbench |
| Interruption and Session eligibility | SessionRecord / SessionRecoveryContext | Resume and FollowUp source validation |
| P17 obligation, schedule and absolute deadline | FollowUpRecord | Worker and incomplete projections |
| In-app execution identity and committed attempts | FollowUpOperation | Attempt aggregate and reconciliation |
| External delivery certainty and result | ExternalTask | External recovery plan and WorkItems |
| Staff responsibility | WorkItem / Handoff | Role-safe task projection |
| Destructive cleanup, closure, inventory and progress | RetentionOperation | Retention worker and staff projection |
| Immutable rules | RecoveryPolicyRegistry | Reducer and existing subsystem adapters |
| History | AuditEventEnvelope | Internal authorized audit reads |

`reason_code` and `result` are compatibility adapters, not additional persisted
fields. FollowUp persists `blocked_reason` separately from `resolution_code`;
operations persist `result_code`. FollowUp version `1` maps explicitly to Registry
version `v1`. Retention domain exports refer to the same model definitions.

## Published decision matrix

| Trigger | Plan | Existing consumer / evidence |
| --- | --- | --- |
| Model timeout / malformed response / provider failure | Preserve accepted input; bounded retry or fail safe | messages, recovery decisions; recovery_message_policy / unified_recovery tests |
| Tool or retrieval unavailable | Blocking fail safe or nonblocking continuation | turn_reducer; unified_recovery and runtime tests |
| Revision conflict | Reload authoritative state | messages / revision CAS; unified_recovery tests |
| External known not submitted | Existing bounded retry | integrations / external lifecycle; recovery_decisions tests |
| External submitted, result unknown | Reconcile original operation before retry | ExternalTask / integrations; recovery_decisions tests |
| External terminal failure | Existing staff resolution | ExternalTask and WorkItem; recovery_decisions tests |
| High-impact review | Wait for authorized human decision | turn_reducer / existing handoff; unified_recovery tests |
| FollowUp due | Execute authorized in-app contact | follow_up_execution / repository transaction; follow_up_execution tests |
| Contact withdrawal | Block contact, preserve recoverability | follow_up_execution; incomplete_claim_recovery_edges tests |
| Attempt exhaustion | Block contact, never abandon Claim | follow_up_execution; full P17 journey tests |
| Recovery expiry | Existing terminal-disposition mutation | follow_up_execution; full P17 journey tests |
| Retention eligible / hold / unknown cleanup result | Reserve / block destruction / reconcile same operation | retention domain and service; retention_eligibility / execution tests |
| Old Session or retry after closure | Concealed absence / deny | Existing repository access guard; retention_access_closure tests |

The transaction-local in-app path atomically writes the obligation, operation,
Claim revision, idempotency and Audit evidence. CAS plus identity replay is the
event deduplication and command-commit equivalent accepted for this boundary.
ExternalTask retains its operation/reconciliation contract. There is no generic
RecoveryInstance, Inbox/Outbox framework, additional worker platform, or persisted
UI state machine.

## Frozen P17 v1 rules

The policy allows at most three committed in-app attempts, 24 hours apart. The
absolute deadline is the original interruption plus seven days. `due_at` is only
scheduling; `now >= deadline_at` always takes expiry precedence. Attempt exhaustion
stops automatic contact while keeping claimant recovery possible. Contact
withdrawal changes permission; it never withdraws or abandons the Claim.

Resume creates a Session for the same WorkingClaim, resolves the obligation, and
reconciles reserved/committed work in the same mutation. Staff abandonment and
authorized closure use existing terminal authority with distinct typed reasons.
FollowUpOperation progresses reserved -> committed -> settled, or reserved ->
cancelled. Committed delivery is the only attempt-count evidence. Operation IDs
use the common factory's stable identity helper and retain existing v1 digest
coordinates across restarts.

Legacy backfill derives the deadline from persisted source interruption only. It
preserves created time, historical due time and source references, and never
fabricates operations. Missing or contradictory source records remain readable
but blocked/nonexecutable. Both paginated discovery implementations exclude
blocked records, use opaque cursors and named due/deadline indexes.

## Retention ordering and failure boundaries

Revalidate terminal/source revision -> reserve and close claimant access -> freeze
record refs and storage keys -> delete bytes -> clean database records -> persist
minimum tombstones -> verify -> complete. Object outcomes are deleted,
already_absent, failed or unknown. Failed/unknown outcomes cannot count as complete;
DB failure or uncertain commit resumes the same durable operation and only
unfinished steps. Inventory and completed evidence cannot be rewritten.

A source-linked hold blocks deletion/anonymisation. It does not restore claimant
access, reopen the Claim, revive Session credentials, or undo tombstones. Staff
visibility retains minimum authority and reconciliation evidence; claimant reads
and historical retries are checked for closure before replay. Destruction
classifications and approved scalar tombstone fields are enumerated in
`backend/domain/retention.py`, rather than selected by provider output.

## Repeatable acceptance

`tests/test_incomplete_claim_recovery.py` contains controlled-runtime API journeys
for pause -> same-Claim resume and pause -> three attempts -> expiry -> retention ->
old-session denial. Dedicated execution, concurrency, migration, discovery,
retention and access-closure files cover replay and partial failure boundaries in
Fixture and mongomock repository profiles. These are controlled-runtime and
mock-adapter evidence; they do not certify deployed providers or a live Mongo
replica set. Integration-marked live database tests require explicit infrastructure.

The machine-readable [policy manifest](../../contracts/recovery-policy-registry.json)
and [replay matrix](../../contracts/recovery-replay-matrix.json) record the
published policy coordinates and deterministic reducer vectors. Current API and
persistence contracts are documented in `docs/api.md` and
`docs/persistence-schema.md`. Exact-head local results and CircleCI acceptance
belong in the final integration PR.

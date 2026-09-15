# Staff Agent tool registry

This reference describes the bounded read capabilities exposed by the backend to the Staff Agent
Runtime. The Python registry and typed input models are the machine-readable source; this document
records their release and disclosure boundary for maintainers and consumers.

## Apply the dispatch boundary

`StaffToolDispatcher` receives a server-verified `Principal`, a registered tool name and version,
the registered business purpose, a typed argument object, a call ID, and a correlation ID. It
validates staff identity, the required `workbench:read` scope, and the server-resolved staff role
before resource or tool existence, rejects version or purpose drift, rejects extra or malformed
fields, rejects duplicate call IDs within one dispatcher, and invokes only an explicitly bound
handler. Registry metadata also records the allowed staff role and the server-resolved customer
and tenant boundaries; roles are loaded from the authenticated staff account and carried in the
verified `Principal`, never accepted from tool arguments.

The dispatcher returns `StaffToolResult`. Each registry entry publishes its own closed output
schema, and the dispatcher validates the selected handler result against that schema before any
data is released. Undeclared output fields fail closed with `INVALID_TOOL_OUTPUT`. Each result also
records the registry version, status, source references, returned record IDs, effective filters,
query scope, limitations, failure code, retry guidance, disclosure flag, and server timestamp. A
result is an observation. It does not mutate Claim State or grant authority for an action.

Runtime owns staged model continuation and durable turn-trace assembly. The dispatcher does not
call the model, prepare prompts, execute side effects, or represent an unavailable dependency as a
successful read.

## Read the active registry

The active registry is version `v1.0`. The following table describes its handler and release state.

| Tool | Bounded input | Result projection | Release state |
| --- | --- | --- | --- |
| `staff.claim.search` | One or more registered Claim, customer, date, family, lifecycle, queue, assignee, or external-reference filters; maximum 25. | Candidate identity, matching fields, effective time, lifecycle, and revision. | Read-only Runtime executable; the repository applies every registered filter before the result limit and returns only the bounded search projection. |
| `staff.claim.read` | One `claim_id`. | Current staff-safe Claim summary, ownership, work, integration, next step, and revision. | Read-only Runtime executable. |
| `staff.session.search` | One `claim_id` plus optional session, date, status, actor, or bounded message-text filter; maximum 25 results, 100 examined sessions, and 200 examined messages per session. | Claim-linked session identities and metadata. | Read-only Runtime executable; repository filters run before the result limit and an exceeded examined-set bound returns unavailable with `SEARCH_SCOPE_EXCEEDED` rather than an incomplete no-result. |
| `staff.session.read` | One `claim_id` and `session_id`; maximum 50 messages. | Allow-listed Session metadata and closed typed text messages; persistence-only Session fields and undeclared message-content fields are omitted. | Read-only Runtime executable; the repository reads only the requested newest message window. |
| `staff.evidence.list` | One `claim_id` plus optional status or kind; maximum 50. | Allow-listed Evidence metadata. | Read-only Runtime executable. |
| `staff.evidence.read` | One `claim_id` and `evidence_id`. | Allow-listed Evidence metadata without raw bytes, storage keys, or provider-private provenance. | Read-only Runtime executable. |
| `staff.knowledge.search` | Published-source scope, question, product, jurisdiction, authority, version, insurer, effective time, visibility, and maximum 10. | Exact governed citations and source versions, or a typed no-result or unavailable outcome. | Read-only Runtime executable when a retriever is supplied. |
| `staff.policy.history` | One `claim_id` plus optional product and effective time; maximum 25. | Persisted policy retrieval records and provenance within that Claim. | Read-only Runtime executable. |
| `staff.handoff.read` | One `claim_id` plus optional `handoff_id`; maximum 50. | Existing staff-safe handoff projection. | Read-only Runtime executable. |
| `staff.review_signal.read` | One `claim_id` plus optional `signal_id`; maximum 50. | Existing staff-visible review signal projection. | Read-only Runtime executable. |
| `staff.work_item.list` | One `claim_id` plus optional `work_item_id`; maximum 50. | Existing staff actions and reconciled Runtime WorkItems. | Read-only Runtime executable. |
| `staff.external_task.status` | One `claim_id` plus optional `task_id`. | Typed unavailable result without substitute data. | Reserved and unavailable until the canonical external-task registry dependency is active. |
| `staff.customer_update.read` | One `claim_id` plus optional `update_id`; maximum 50. | Existing customer-update records and source references. | Read-only Runtime executable. |

## Enforce visibility

All Claim-linked handlers first resolve the Claim through the staff Workbench authorization
boundary. A child identifier is then resolved with that Claim and its server-owned customer scope.
An identifier from another Claim therefore produces `no_result` and no leaked record payload.

Evidence projection is an explicit allow-list. It excludes `provenance`, object-storage keys, raw
bytes, credentials, endpoints, and provider-only payloads. Knowledge search uses the governed
retriever contract and never substitutes unrelated text when the source is unavailable.

## Interpret result status

Consumers use these status values without parsing limitation text:

| Status | Meaning |
| --- | --- |
| `succeeded` | The bounded source returned one or more records. |
| `no_result` | The source completed the stated query and returned no record in that scope. |
| `partial` | A bounded result exists but the recorded limitations prevent a complete answer. |
| `unavailable` | The registered source could not answer; unrelated data is not substituted. |
| `denied` | The verified principal cannot use the Staff Agent read boundary. |
| `failed` | The request or handler failed before producing a trusted result. |
| `unknown` | The backend cannot determine an outcome; consumers must not claim success. |

`UNKNOWN_TOOL`, `REGISTRY_VERSION_MISMATCH`, `PURPOSE_DENIED`, `INVALID_TOOL_ARGUMENTS`,
`INVALID_TOOL_OUTPUT`, `DUPLICATE_CALL_ID`, `ACCESS_DENIED`, `RESOURCE_NOT_FOUND`, and
`SOURCE_UNAVAILABLE` are the initial stable failure codes produced by the dispatch boundary.

## Preserve implementation limits

This backend slice does not prove that the model can request a tool, consume a result in a second
continuation, or produce a final direct answer. It also does not implement side-effect proposals,
action confirmation, Workbench trace rendering, or the canonical external-task status handler.
Those claims require their owning Runtime, action, and frontend integration evidence at the same
exact commit.

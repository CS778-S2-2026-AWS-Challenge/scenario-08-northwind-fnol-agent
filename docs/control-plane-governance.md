# Control Plane roles and publication lifecycle

This document defines the current engineering contract for Northwind's Control Plane. It
separates claim operations from system administration, knowledge management, and audit, and
defines the terms and transitions that a later Admin API must implement. It does not define
HTTP routes, storage tables, or provider-specific integrations.

## Scope and authority

The Control Plane manages versioned configuration and approved knowledge that runtime services
consume. It does not own the live Claim State of a production claim. Claim State, WorkItems,
handoffs, and claimant or staff messages remain under the claim-operation services and their
existing authority checks.

The product requirements in `SPEC/05-workbench-and-handoff.md` and
`SPEC/06-safety-and-governance.md` remain authoritative for product behaviour and safety. This
document makes their administration boundary executable for the later Admin API described by
Issue #209.

## Separate responsibilities

The following responsibilities are intentionally separate. A person may hold more than one
role only when the applicable approval policy records the separation and any required
two-person approval.

| Responsibility | Owns | May do | Must not do |
| --- | --- | --- | --- |
| Claim operations | Live claim handling and staff work | Read and update authorised Claim State, WorkItems, handoffs, evidence decisions, and claimant communication | Publish system configuration or edit a claim through an administration shortcut |
| System administration | Runtime and operational configuration | Maintain model, data-profile, integration, access, feature, and operational configuration drafts; run validation; publish when authorised | Decide coverage, liability, fraud, or other claim outcomes; edit production Claim State |
| Knowledge management | Governed knowledge content | Import sources, maintain metadata and versions, run ingestion and retrieval checks, request publication, and withdraw content | Change model permissions, access policy, or claim records through a knowledge workflow |
| Evaluation and release approval | Independent quality and high-impact approval | Review validation evidence, approve or reject changes within assigned scope, and record the decision | Modify the draft while approving it or bypass required evidence |
| Audit and oversight | Traceability and control verification | Read append-only configuration and access events, verify actor/reason/evidence fields, and report violations | Rewrite history, approve its own exception, or change runtime or claim data |
| Runtime service | Consumption of published configuration | Load one complete published version and report its version and failures | Read drafts, choose an unpublished version, or infer authority from model output |

Claim operations and the Control Plane exchange bounded references, not unrestricted database
access. For example, a handoff may include the active policy version or a knowledge citation,
but an administrator cannot use that reference to mutate the claim.

## Configuration domains

Every configuration item belongs to one domain with a stable identifier, owner, scope, and
lifecycle version. A change that spans domains declares all affected domains before validation.

| Domain | Examples | Primary owner | Typical impact class |
| --- | --- | --- | --- |
| Model | Model identifier, adapter endpoint reference, capability declaration, timeout, token limit | System administration | High impact when routing or capability changes |
| Data profile | Selected persistence and object-store profile, retention and region settings | System administration | High impact because data scope and residency may change |
| Knowledge | Source metadata, document version, authority, effective period, retrieval index, withdrawal status | Knowledge management | High impact when policy or safety content changes |
| Agent rule | Intent routing, content branches, confirmation rules, handoff rules, tool and action policy | System administration with evaluation approval | High impact |
| Integration | External capability, requirement mapping, consent scope, idempotency and failure policy | System administration | High impact when disclosure or side effects change |
| Access | Roles, scopes, visibility, credential references, staff capabilities, service permissions | System administration with security approval | High impact |
| Evaluation | Scenario catalogue, thresholds, test profile, regression result, release evidence | Evaluation and release approval | High impact when acceptance thresholds change |
| Feature | Product or UI capability flags, observation or shadow mode, cohort scope | System administration | Normal unless it changes safety or authority |
| Operational configuration | Rate and cost limits, retry policy, alert thresholds, queue timing, maintenance switches | System administration | Normal unless it changes safety, access, or side effects |

Secret values never belong to a configuration item or its API response. A configuration stores
only a protected secret reference and safe connection metadata. The secret manager and its
access policy remain outside the Control Plane record.

## Lifecycle states

The lifecycle applies independently to each versioned configuration item or knowledge version.
Published versions are immutable. A change to a published item creates a new draft rather than
editing the active version.

| State | Owner | Entry condition | Exit condition | Approval and evidence |
| --- | --- | --- | --- | --- |
| `draft` | Domain owner (system administrator or knowledge manager) | A new item is created or a new revision is opened from an existing version | Submitted for validation, or abandoned as `withdrawn` before validation | Required scope, reason, affected domains, and protected references are present |
| `validation` | Evaluator or automated validation service | Owner submits a complete draft and selects its required scenarios | `draft` when validation fails or evidence is incomplete; `awaiting_approval` when all checks pass | Schema, authority, compatibility, security, retrieval, and required scenario results are recorded |
| `awaiting_approval` | Assigned release approver | Validation passes and the domain's impact class requires approval | `published` after approval, or `draft` after rejection or requested changes | High-impact changes require the configured stronger or two-person approval; normal changes follow the configured policy |
| `published` | Release approver authorises; runtime consumes | A validated item has all required approvals and an effective time | `superseded` by a later publication, or a new approved version is published as rollback | Publication is atomic and records actor, reason, validation evidence, effective time, and previous version |
| `withdrawn` | Domain owner or authorised approver | Draft is abandoned, or published knowledge/configuration is removed for a documented reason | A new draft may replace it; a withdrawn version is never silently reactivated | Withdrawal records actor, reason, time, affected scope, and any replacement or mitigation |
| `superseded` | Release process | A newer version becomes active | Terminal for that version; it remains readable for audit and claim/version provenance | The successor and previous version are linked; history is retained |
| `rollback` | Authorised release approver | A published version is unsafe, incompatible, or otherwise requires restoration of a known-good version | The selected prior version is published as a new active publication; the triggering version remains in history | Rollback target, reason, validation evidence, actor, effective time, and reconciliation steps are recorded |
| `audit_recorded` | Audit and oversight | Any lifecycle or access transition is accepted by the service | Terminal event; it cannot mutate the configuration lifecycle | Append-only event includes actor, action, subject/version, reason, authority result, timestamp, and correlation reference |

`rollback` describes a transition request and publication operation, not deletion. The restored
version receives a new publication record so that intervening activity remains auditable.
`audit_recorded` accompanies every transition; it is shown explicitly because an un-audited
transition is invalid even when the underlying state change otherwise passes validation.

## Transition rules

The following transitions are the only normal lifecycle paths:

```text
draft -> validation
validation -> draft                 (failed or incomplete)
validation -> awaiting_approval     (all required checks pass)
awaiting_approval -> draft           (rejected or changes requested)
awaiting_approval -> published       (approval complete)
draft -> withdrawn                   (abandoned before validation)
published -> superseded              (new version published)
published -> rollback                (authorised rollback requested)
rollback -> published                (approved prior version published as a new record)
any accepted transition -> audit_recorded
```

The service rejects transitions when the actor lacks the domain scope, the revision is stale,
required evidence is missing, a required approver is also the sole author for a high-impact
change, or the target version is not an approved immutable snapshot. A failed transition does
not partially publish configuration and still records the rejected attempt in the audit log.

## Permission and impact rules

Permissions are evaluated against actor identity, domain, operation, environment, and impact
class. Read access to a draft or published record does not grant permission to validate,
approve, publish, withdraw, or roll back it.

The following changes are high impact and require stronger approval before publication:

- Agent rules that alter safety interruption, human handoff, confirmation, visibility, or tool
  authority.
- Model or data-profile changes that alter capability, customer-data scope, retention, region,
  or provider terms.
- Access, identity, credential-reference, or external integration changes.
- Knowledge changes that alter policy, legal, safety, or other high-impact guidance.
- Evaluation changes that lower an acceptance threshold or remove a required scenario.

Feature flags and operational limits may use normal approval only when they cannot weaken an
existing safety, access, authority, or side-effect boundary. No configuration publication may
downgrade those boundaries to observation-only mode.

## Validation and publication contract

Validation must run against the declared scope and every supported model or runtime profile
that the change can select. The result records the exact configuration revision, scenario set,
profile identity, thresholds, pass/fail outcome, and limitations. A green build alone is not
publication evidence.

Publication makes one complete version active for a runtime profile. Runtime services report
the active version they used and never combine fields from drafts, superseded versions, or
different data profiles. If a provider or connection check fails, the configuration remains
unpublished and the failure is exposed as an operational result rather than silently selecting
another profile.

## Boundary with Claim State and later Admin API work

The later Admin API in Issue #209 should expose these stable concepts without creating a second
Claim State API:

- configuration domain and item identifier;
- immutable revision and lifecycle state;
- validation result and required scenarios;
- approval requirement and approval record;
- publication, withdrawal, supersession, and rollback records;
- protected secret reference and safe connection status; and
- append-only audit events.

The API must reject attempts to write Claim State, WorkItems, handoffs, or claimant messages
through Control Plane routes. Claim-operation APIs remain the only path for those effects and
continue to enforce claim ownership, revision, visibility, idempotency, and professional
authority rules.

## Non-goals for this contract

This document does not implement an Admin API, persistence schema, database migration, Admin
Console, provider connection, secret manager, or runtime policy cache. Those components must
consume this vocabulary and preserve the transitions when they are implemented.

# Claim State and Data

## Authoritative Claim State

A claim has one authoritative current state shared by claimant, Agent, staff, and
authorised integrations. A session, frontend, workbench, or external adapter must not
maintain a competing private claim record.

Target turn plans, proposals, execution plans, WorkItems, and UI projections are bounded
records around this state. They may plan, propose, track, or display work, but they cannot
become a second Claim State authority. Their implementation status and migration evidence
are maintained in [Agent Runtime Progress](../docs/status/agent-runtime-progress.md).

Claim content and Claim lifecycle are separate models. Content branches answer what
information and rules apply to the incident. Lifecycle answers where the work is now,
who owns it, and what it is waiting for.

A Claim may activate several content branches at once, for example:

```text
motor + collision + another_party + police_report_pending
```

Only the rule engine may move a content branch through `proposed`, `active`, `suspended`,
and `exited/corrected`. The model supplies candidates, supporting facts, and provenance.

The lifecycle is an application-controlled state machine:

```text
no_claim
  -> draft_active
  -> waiting_customer | waiting_external | staff_support | professional_review
  -> ready_to_create -> creating -> created
  -> withdrawn | expired -> purged/anonymised
```

Lifecycle transitions do not rewrite incident facts or content branches. A Claim may
also hold several independent `WorkItem` records for questions, evidence, professional
judgement, external requests, claimant confirmation, or system work. Each item records
its owner, status, the exact action it blocks, due time when known, source references,
and completion evidence. Waiting for one item must not imply that all work has stopped.

Other Claim attributes remain independent rather than forming one mutually exclusive
path:

```text
severity: fast_track | standard | complex
coverage: clear | ambiguous | review_required
evidence: received | unofficial | incomplete | pending_generation | inconsistent
fraud_signal: none | review_required
customer_support: self_service | guided | human_requested | accessibility_required
urgency: normal | urgent | immediate_safety_risk
workflow_state: collecting | ready_for_next | awaiting_evidence | professional_review | created
next_action
```

The workflow projection, workbench queue, priority, and `next_action` are calculated from
lifecycle, WorkItems, content branches, service rules, and staff decisions. They are not
separately maintained sources of truth. Pending evidence must not erase another clear
state or block work that does not depend on it.

## Structured Facts

Each material fact retains:

```text
value
source: claimant | image | document | policy | claim_history | staff | inference
status: proposed | confirmed | disputed | missing | pending_generation
needed_for: current_action | later_action
source_refs
updated_at
```

Extracted and inferred values remain proposed until the applicable confirmation or
professional authority accepts them.

Dynamic Form field-selection states such as `required_now`, `candidate_now`,
`pending_later`, `inactive`, and `system_owned` describe relevance for the current action.
They do not replace stored fact status. The current claimant and staff forms are
recalculated projections of published Registry versions and the latest Claim State.

## Data Separation

The system separates:

- customer identity and permitted communication preferences;
- formal Claim State and structured facts;
- sessions, complete messages, compact summaries, and working context;
- evidence metadata, original evidence objects, and extracted proposals;
- structured customer policy and claim-history records;
- approved knowledge documents, versions, chunks, indexes, and citations;
- model requests, outputs, usage, and evaluation results;
- turn plans, model proposals, validated execution plans, action envelopes, tool results,
  and final turn results;
- internal signals, handoffs, staff actions, and claimant-safe updates;
- WorkItems and external-service requests with preparation, authority, submission,
  tracking, verification, reconciliation, and uncertain-outcome state;
- versioned system configuration and publication records; and
- append-only audit and operational events.

Physical storage may combine logical records, but it must preserve ownership,
visibility, retention, provenance, and authority boundaries. Detailed storage and
runtime-profile rules are defined in `docs/data-architecture.md`.

## Knowledge and Structured Retrieval

Policy wording, legislation, industry guidance, and approved procedures may enter the
knowledge base for metadata-filtered, cited retrieval. A customer's actual policy
schedule, endorsements, identity link, and claim history require structured,
authorised queries. A knowledge document alone cannot prove that wording applies to a
customer.

## Administration and Configuration

The Control Plane manages versioned model, knowledge, rule, integration, access,
evaluation, feature, and operational configuration. A configuration record retains its
author, validation result, approval, publication state, effective time, and rollback
target. Secrets remain in an approved secret store and are referenced, not displayed or
stored as ordinary configuration.

Changing a data runtime profile requires validation of capability, migration, and
deployment impact. It is not a per-request switch.

## Context and Memory

Complete conversation history remains durable. Routine model calls receive bounded
working context. Formal claim records, customer preferences, model working memory,
knowledge, and operational logs remain separate. Returning users continue from the
latest authorised Claim State, not from an old session copy.

An old session may contribute bounded context but cannot overwrite a newer Claim
revision. On resume, the application reloads the latest facts, content branches,
lifecycle, WorkItems, commitments, and Registry versions, then recalculates the dynamic
form and next action.

## Visibility

Every record and field is claimant-visible, shared, internal-only, or restricted
administration data. Secrets, real personal information, internal review labels, raw
provider payloads, and unnecessary full histories must not enter prompts, logs,
fixtures, or claimant responses.

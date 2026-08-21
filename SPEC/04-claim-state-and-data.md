# Claim State and Data

## Authoritative Claim State

A claim has one authoritative current state shared by claimant, Agent, staff, and
authorised integrations. A session, frontend, workbench, or external adapter must not
maintain a competing private claim record.

The claim uses independent dimensions rather than one mutually exclusive path:

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

Pending evidence must not erase another clear state or block work that does not depend
on it.

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

## Data Separation

The system separates:

- customer identity and permitted communication preferences;
- formal Claim State and structured facts;
- sessions, complete messages, compact summaries, and working context;
- evidence metadata, original evidence objects, and extracted proposals;
- structured customer policy and claim-history records;
- approved knowledge documents, versions, chunks, indexes, and citations;
- model requests, outputs, usage, and evaluation results;
- internal signals, handoffs, staff actions, and claimant-safe updates;
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

## Visibility

Every record and field is claimant-visible, shared, internal-only, or restricted
administration data. Secrets, real personal information, internal review labels, raw
provider payloads, and unnecessary full histories must not enter prompts, logs,
fixtures, or claimant responses.

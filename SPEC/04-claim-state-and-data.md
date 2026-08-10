# Claim State and Data

## Multi-dimensional State

A claim is not assigned to one mutually exclusive path. At minimum, the system maintains:

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

An evidence item pending generation must not erase clear coverage or incorrectly block a claim that is otherwise ready to create.

## Form Fields

Each structured field contains:

```text
value
source: claimant | image | document | policy | claim_history | inference
status: proposed | confirmed | disputed | missing | pending_generation
needed_for: current_action | later_action
updated_at
```

## Minimum Domain Records

- customers and permitted communication preferences;
- claims, form, workflow state, route, and next action;
- claim attributes for the independent state dimensions;
- sessions and compact working summaries;
- complete messages stored outside the model context;
- evidence, provenance, status, and related fields;
- decisions, reason codes, authority checks, and outcomes;
- internal tags and review signals;
- handoffs and their lifecycle;
- staff actions and claimant-visible updates;
- append-only claim events for audit.

Shared tables or collections are partitioned and related by `customer_id`, `claim_id`, and `session_id`; the system must not create a separate physical table for every customer.

## Context Management

Complete conversation history remains in durable storage. Each model call receives only the current claim snapshot, unresolved questions, recent necessary messages, and relevant policy or history evidence. Formal claim records, customer preferences, and model working memory remain separate.

## Internal Tag Model

An internal tag or signal contains code, category, visibility, source, evidence references, confidence, lifecycle status, required action, queue, and audit timestamps. High-impact signals start as proposed or review-required and can be confirmed, dismissed, overridden, resolved, and audited.

## Data Boundaries

The prototype must separate customer-visible, shared, and internal-only data. Secrets, real personal information, and unnecessary full histories must not enter prompts, logs, fixtures, or demonstration screens.

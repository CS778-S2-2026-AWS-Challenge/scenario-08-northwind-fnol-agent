# Non-functional Requirements

## Traceability and Reproducibility

Every material state change, model or tool call, retrieval, staff action, configuration
publication, override, and handoff is attributable to a source, rule or reason code,
actor, version, and time. A model answer and configuration state used for an evaluated
scenario must be reproducible within approved retention limits.

## Reliability

Core acceptance paths use repeatable anonymous fixtures and do not depend on hidden
manual data changes. External failure preserves working claim progress and produces a
bounded, actionable error. Retry, idempotency, revision, resume, and rollback behaviour
are tested.

## Security and Visibility

The system enforces claimant-visible, shared, internal-only, and restricted
administration boundaries. Secrets and real personal data must not be committed, placed
in fixtures, exposed in prompts without approval, or returned through logs or claimant
responses. Administrative actions require explicit roles and audit records.

## User Control and Accessibility

Claimants can correct material understanding, understand uncertainty, obtain human
support, and see responsibility and next steps. They are not required to inspect every
internal field. Claimant, staff, and administration controls are keyboard operable,
visibly focused, semantically labelled, readable, and usable with common assistive
technology.

## Responsive Interface Quality

Claimant, staff, and administration interfaces have deliberate desktop and mobile
behaviour appropriate to their workflows. Default, loading, empty, error, disabled,
upload, urgent-transfer, human-transfer, validation, publish, and rollback states receive
complete treatment. Text, controls, data tables, and status information must not overlap
or become unreadable at supported viewport sizes.

## Performance and Cost Observability

The system records interaction and correction counts, completion timing, model tokens,
retrieval and tool calls, latency, errors, retries, handoff rate and cause, staff effort,
ingestion jobs, index health, and configuration changes. Context selection and summaries
prevent conversation length from causing unbounded model cost.

## Provider Portability

Cloudflare, MongoDB, AWS, fixture data services, official model APIs, compatible relay
services, custom endpoints, and local endpoints remain behind provider-neutral contracts.
One data runtime profile is active in a process. Unsupported capability and incomplete
configuration fail explicitly rather than creating silent mixed-provider behaviour.

## RAG Quality

Knowledge retrieval is evaluated for relevance, citation support, authority, correct
version, jurisdiction, access control, safe refusal, and prompt-injection resistance.
Retrieval quality is compared against defined baselines rather than judged from one
successful demonstration.

## Maintainability and Delivery

Frontend, API, Agent orchestration, domain rules, persistence, knowledge retrieval,
administration, and adapters communicate through versioned contracts. Environment values
and secrets are configuration, not source constants. Relevant format, lint, type, unit,
contract, integration, accessibility, build, and scenario checks run before merge.

## Deployability and Recovery

The application is deployable to an approved cloud environment without changing domain
behaviour. Configuration, schema migration, knowledge ingestion, secret references,
health checks, backup, rollback, and recovery are reproducible. No cloud platform,
service, dataset, permission, quota, or production readiness is assumed until verified.

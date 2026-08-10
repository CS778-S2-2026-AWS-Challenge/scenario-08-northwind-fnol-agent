# Non-functional Requirements

## Traceability

Every material state change, tool call, high-impact recommendation, staff override, and handoff must be attributable to a source, rule or reason code, actor, and time.

## Reliability

Acceptance paths use repeatable anonymous fixtures. A core demonstration must not depend on manually changing hidden data immediately before it runs. External failures produce bounded error states and preserve claim progress.

## Security and Visibility

The system enforces customer-visible, shared, and internal-only information boundaries. No secret or real personal data may be committed, logged, placed in prompts, or displayed in demonstration material.

## User Control and Accessibility

Claimants can correct the form, understand uncertainty, see the next step, and obtain human support. Interaction controls must be keyboard operable, visibly focused, labelled, readable, and usable with common assistive technology.

## Responsive Interface Quality

The claimant experience is a working HTML application with independently designed desktop and mobile layouts, not a desktop page scaled down. Primary design checks use 1440 x 900 and 390 x 844 viewports, with additional checks at 1280 x 800 and 360 x 800. Default, loading, empty, error, disabled, upload, urgent-transfer, and human-transfer states require complete visual treatment.

## Performance and Cost Observability

The system records questions, correction and repetition counts, completion timing, model tokens, retrieval and tool calls, latency, errors, retries, handoff rate and cause, staff actions, and handoff completeness. Context must be selected and summarised so that conversation length does not cause unbounded model cost.

## Maintainability

Frontend, API, agent orchestration, domain rules, and persistence communicate through versioned contracts. Environment-specific endpoints and secrets are configuration, not source constants. Automated linting, tests, and build checks must run before merge once their baseline is introduced.

## Deployability

The target is the AWS environment provided for the challenge. Deployment, identity, storage, model, and retrieval services remain replaceable until access and constraints are confirmed. Infrastructure and configuration must eventually be reproducible rather than manually reconstructed.

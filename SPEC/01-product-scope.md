# Product Scope

## Product Thesis

Northwind FNOL Agent lets a claimant explain a loss naturally while the system
handles insurance structure, evidence tracking, knowledge retrieval, and next-step
planning internally. The claimant should not have to become the project manager of
their own claim.

The service allocates claimant effort, system work, and professional judgement
according to the current claim and user state. It advances the next safe action,
preserves context across time and handoff, and builds a complete, traceable claim
record as information becomes available.

"Complete" means that known facts, sources, evidence state, unresolved work,
responsibility, and the next action are recorded. It does not mean that every document
needed later in the claim lifecycle must already exist.

## Customer Problem

A phone process can handle natural language and exceptions but consumes claimant and
staff time. A web form is immediate and structured but requires claimants to understand
the insurer's process and terminology. Both channels can create repetition, waiting,
unclear responsibility, and loss of context when work changes hands.

The product keeps the immediacy of digital service and the judgement of professional
support. Its value is not that it puts a chat interface in front of a form; its value is
that it reduces the process knowledge and coordination work required from the claimant.

## Current Product Scope

- friendly natural-language FNOL intake with internal structured Claim State;
- focused clarification and confirmation only when uncertainty, conflict, authority, or
  the next material action requires it;
- text, image, and PDF evidence with provenance and lifecycle state;
- pending evidence and later submission without restarting the claim;
- cross-session recovery using the same authoritative claim context;
- approved policy, procedure, and industry knowledge retrieval with citations;
- structured customer-policy and claim-history lookup when authorised data exists;
- context-preserving standard and urgent human handoff;
- controlled claim creation and conditional routing through replaceable adapters;
- a staff workbench derived from the same Claim State;
- an administration and control plane for versioned system, model, knowledge, rule,
  integration, access, evaluation, and operational configuration;
- observability for claimant effort, staff effort, model usage, latency, and failure.

## Product Direction

The first product capability is a dependable insurance-domain Agent that is more useful
than a general chat model because it combines authorised claim context, approved
knowledge, insurance workflows, controlled tools, and explicit professional authority.

The broader direction is a shared claim coordination layer. Assessors, repairers, claims
professionals, and other approved participants should be able to work from the same
claim context rather than making the claimant carry information between disconnected
services. This direction is planned incrementally and does not imply that every external
participant or integration exists in the current MVP.

## Boundaries

The Agent is not a chat-shaped form, a general customer-service bot, or an autonomous
replacement for claims professionals. It must not make unreviewed high-impact coverage,
fraud, liability, approval, or rejection decisions. It must not diagnose injury or claim
to have contacted emergency services when it has not.

The Staff Workbench handles claim operations. The Administration and Control Plane
governs the system itself and must not become an unrestricted editor for production
claim records.

## External Capability Boundary

Northwind data, provider schemas, cloud-service availability, permissions, business
rules, and production deployment conditions remain unconfirmed until verified. The
team owns provider-neutral contracts, mapping, validation, fallback behaviour, and
honest capability reporting. Fixtures are repeatable development evidence, not proof of
a production integration.

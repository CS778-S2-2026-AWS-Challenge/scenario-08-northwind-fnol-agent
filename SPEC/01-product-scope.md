# Product Scope

## Product Thesis

Northwind FNOL Agent allocates claimant effort, system work, and human judgement according to the current claim and user state. It should safely advance the next action and ultimately create a structured claim record that another person or system can continue processing.

"Complete" means that the facts currently known, their sources, evidence state, unresolved work, routing, and responsibility are recorded. It does not mean that every document needed later in the claim lifecycle must exist at FNOL.

## Problem

The current contact-centre path can understand natural language and exceptions but consumes staff time and may still struggle with complex policy questions. A web form is immediate and structured but is rigid, asks users to understand the process, and cannot adapt well to incomplete or unusual incidents. Both channels can make a claimant repeat information when work changes hands.

The challenge brief states that 40% of FNOL cases need at least one follow-up and that average time from first report to claim creation is 2.5 days, including follow-up for missing information. These figures define the problem context; they do not prove a specific root cause or financial return.

## In Scope

- natural-language FNOL intake with a visible, correctable structured form;
- text, image, and PDF input;
- adaptive questioning and next-action selection;
- policy and claim-history lookup with source evidence;
- evidence status and later submission without restarting the claim;
- cross-session recovery;
- context-preserving standard and urgent human handoff;
- mock or real claim creation and conditional assessor routing;
- an internal claim operations workbench derived from shared claim state;
- observability for claimant, human, and agent effort.

## Product Boundary

The agent is not a chat-shaped web form, a general customer-service bot, or an autonomous replacement for claims professionals. It must not make unreviewed high-impact coverage or fraud determinations, approve or reject claims, provide medical diagnosis, or claim to have contacted emergency services when it has not.

The FNOL product boundary ends when a claim is created and routed with a clear next step. Full downstream claim management is outside the initial scope.

## Integration Boundary

AWS is expected to provide project data. Actual schemas, access methods, mock services, and availability are not yet confirmed. The team owns inspection, mapping, adapters, validation, and deployment to the provided AWS environment. Prototype fixtures must be replaceable through defined interfaces.

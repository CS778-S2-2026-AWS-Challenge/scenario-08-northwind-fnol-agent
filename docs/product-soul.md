# Northwind FNOL product soul

This document is the repository counterpart of the project-level product soul. It records the
product direction and principles that should remain stable while implementation details change.
Detailed product requirements and acceptance boundaries remain in `SPEC/`; this document does
not replace them.

## Product thesis

Northwind FNOL Agent is a trusted, adaptive claim entry and coordination service. A claimant can
explain a loss in their own words while the system handles insurance structure, evidence tracking,
authorised knowledge retrieval, and next-step planning internally.

The product should move a claim to the next safe action with the least necessary effort from the
claimant and the right amount of professional judgement. It should preserve context across
sessions and handoffs, and create a complete, traceable claim record as information becomes
available.

## Two connected key features

### Trusted adaptive claim entry

The Agent turns a claimant's natural description and submitted evidence into a structured,
source-aware claim context. It adapts its questions and actions to the incident, evidence state,
user situation, and next safe action. It asks for confirmation when a material fact is uncertain,
conflicting, or consequential, and it hands work to staff when automation cannot safely continue.

This feature serves staff as well as claimants. Staff should receive a concise, source-preserving
summary of confirmed facts, missing or conflicting information, evidence, Agent suggestions, and
the requested decision. Staff can ask follow-up questions, correct information, reject or override
an Agent suggestion, and record the result without rebuilding the claim from the full transcript.
The product should improve staff work experience, processing efficiency, collaboration with the
Agent, trust, and willingness to use it.

### Shared Claim Context coordination layer

The same Claim Context should connect the claimant, Agent, staff, evidence, insurer systems, and
approved external participants. The system should know what the next participant needs, what may
be shared, who must authorise it, and what result is expected. It should reduce repeated
explanations, manual coordination, and progress chasing rather than merely adding more service
buttons.

Claimant and staff views may show different information, but both must reflect the same underlying
state. When a third-party service is used, the claimant should see the purpose, shared information,
consent state, progress, and next step. Staff should see the request details, authority and
consent, processing state, result, failure reason, and unresolved decision.

## Product principles

The following principles guide product and engineering decisions:

- **Reduce process knowledge:** Claimants should not need to understand insurer terminology or act
  as the project manager of their own claim.
- **Use the next safe action:** Missing future evidence must not block an action that can already
  be completed safely. The customer must know what is pending, who owns it, and how to continue.
- **Keep professional structure inside the service:** Dynamic Form state is rebuilt from confirmed
  facts, unresolved work, evidence, and the current action. It uses only registered fields, tags,
  and branch rules, while the claimant receives clear, friendly language.
- **Separate understanding from authority:** The model may interpret context and propose actions.
  Runtime services validate authority, execute approved actions, persist state, and decide whether
  a business state may change.
- **Keep staff in control:** High-impact coverage, fraud, liability, approval, rejection, and
  safety decisions require explicit business or human authority. Agent suggestions are not staff
  decisions and must not be sent to claimants without a clear staff decision.
- **Preserve evidence and uncertainty:** Distinguish claimant statements, extracted material,
  policy evidence, history, inference, and staff decisions. Do not present an inference as a fact
  or a review signal as a fraud conclusion.
- **Protect information throughout the journey:** Privacy is not satisfied by one consent
  checkbox. Explain collection, storage, claim creation, human handoff, third-party sharing,
  session recovery, retention, and deletion at the relevant points, and record consent by purpose
  and data scope.
- **Be honest about capability:** Fixtures, mock services, provider adapters, and unconfirmed AWS
  access are development evidence. They must not be described as Northwind production capability
  until access, schema, permissions, and behaviour are verified.
- **Prefer provider-neutral boundaries:** Model, persistence, object storage, knowledge retrieval,
  and external services must be replaceable through explicit adapters without changing the domain
  meaning of Claim Context.

## Audience and value

The product has two primary day-to-day audiences:

- **Claimants** need a friendly, low-effort way to report a loss, correct material misunderstandings,
  provide evidence, understand progress, and resume later without starting again.
- **Claims staff** need actionable, source-aware context, clear ownership and next actions, and a
  practical way to collaborate with and correct the Agent.

Northwind claims operations also needs fewer avoidable follow-ups, less context reconstruction,
and observable claimant, staff, and Agent effort without sacrificing safety or trust.

## Scope boundary

The product is not a chat-shaped web form, a general customer-service bot, or an autonomous
replacement for claims professionals. The model, RAG, rules, databases, tools, and interfaces are
parts of a governed service whose value is measured by whether it safely advances real claim work.
Model training or fine-tuning is not a product requirement; behaviour design, prompt quality,
structured outputs, retrieval boundaries, and runtime controls are the current focus.

## How to use this document

Use this document to resolve product-direction questions and to check whether a proposed feature
supports both claimant and staff value. Use `SPEC/` for normative behaviour and acceptance, `docs/`
for engineering contracts and evidence, and `sprint/` for time-bound commitments. When a proposal
conflicts with these principles, record the conflict and obtain a product decision before coding.

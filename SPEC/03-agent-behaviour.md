# Agent Behaviour

## Service Behaviour

The Agent behaves like a capable insurance service professional while keeping internal
insurance structure out of the claimant's way. It must:

- accept an incomplete or non-linear account without forcing a fixed question order;
- acknowledge the customer's situation before requesting more information;
- explain the next useful step in plain language;
- avoid repeating confirmed information;
- stop questioning when the current action can progress safely;
- distinguish information needed now from evidence that can be supplied later; and
- preserve a coherent, friendly interaction during uncertainty, failure, or handoff.

The Agent may convert natural language into professional internal records, but it must
not change the claimant's facts or present inferred content as confirmed.

## Turn and Action Contract

One interaction turn may answer a question, explain a limitation, propose several fact
updates, request a read-only lookup, and arrange the next step. It must not compress these
different responsibilities into one action label.

The runtime keeps six concepts separate:

- **user intent:** what the claimant or staff member is trying to achieve;
- **conversation move:** how the Agent communicates, without a business side effect;
- **Claim command:** a proposed or authorised change to Claim State;
- **tool call:** a bounded application capability used for a query or side effect;
- **runtime control:** whether execution continues, waits, pauses, interrupts, or fails
  safely; and
- **execution result:** what actually succeeded, failed, or remains uncertain.

Each turn uses a multidimensional `TurnPlan`. It records detected intents, conversation
moves, workflow purpose, content-branch candidates, form-patch proposals, Claim-command
proposals, tool requests, one primary runtime control directive, the response plan,
unresolved work, and limitations.

The model produces an `AgentProposal`. Runtime validation produces an `ExecutionPlan`,
and real tool and state outcomes produce a `TurnResult`. These records remain distinct so
an audit can show what was proposed, what was authorised, and what actually happened.

Canonical actions use separate `conversation`, `claim`, `human`, `external`, and
`runtime` namespaces. The existing `ASK`, `CLARIFY`, `CONFIRM`, `PROCEED`, `UPDATE`,
`HANDOFF`, `URGENT_HANDOFF`, and `CREATE_CLAIM` values remain a transport migration
mapping only; they are not the foundation of new behaviour.

Every auditable action retains a stable identifier, namespace, target, proposer, reason
and source references, validated inputs, preconditions, authority requirement, expected
effects, idempotency key where relevant, visibility, and actual status.

## Confirmation Threshold

The claimant does not review every internal field. Confirmation is required when:

- the system is uncertain between materially different interpretations;
- sources conflict;
- an extracted or inferred fact affects the next material action;
- the claimant must accept a declaration or customer-controlled decision; or
- a rule explicitly requires confirmation.

Low-impact wording, internal classifications, and already confirmed facts should not
create extra confirmation work. The structured form may be shown when useful or
requested, but it is not a mandatory end-of-chat checkpoint.

## Adaptive Inputs

The Agent considers:

- claim facts, safety, complexity, coverage uncertainty, evidence, and action impact;
- claimant comprehension, patience, distress, accessibility, and support preference;
- availability and reliability of policy, history, knowledge, evidence, claim, and
  participant services; and
- the claimant, staff, token, latency, and context cost of continuing the interaction.

## Required Behaviour Paths

- **Straightforward:** minimise questions and progress a clear report.
- **Guided:** resolve manageable ambiguity with focused explanation or clarification.
- **Professional review:** transfer high-impact ambiguity or conflicting evidence with a
  structured request.
- **Urgent:** interrupt ordinary intake for explicit injury, continuing danger, or another
  approved safety signal and create an urgent handoff.
- **Human support:** respect the need behind a request and do not repeatedly resist
  transfer. Repeated requests, urgency, distress, or accessibility needs transfer
  immediately.
- **Pending evidence:** record missing, unofficial, incomplete, or not-yet-generated
  evidence while progressing unrelated safe work.
- **Resume:** restore shared claim state, unresolved work, and prior commitments without
  restarting.
- **Review signal:** create an evidence-linked professional-review request without making
  a fraud, coverage, or liability determination.

## Dynamic Form and Branch Behaviour

The Agent begins from the claimant's natural account and may extract several explicit
facts from one message. The model may propose a Claim family, incident type, participant,
evidence condition, support need, or professional-authority branch, but only published
rules may activate a registered content branch.

Content branches determine applicable information, evidence, questions, and permitted
tools. They do not represent whether the Claim is waiting, under review, ready to create,
or created. Those are lifecycle and unresolved-work concerns. A correction recalculates
the active form while preserving prior values, sources, and decisions.

The dynamic form is an internal projection of current Claim State. The claimant may
correct information in natural language and is not required to audit the insurer's full
internal form. The Agent asks only for information required for the current safe action
and records later evidence or unresolved work without blocking unrelated progress.

## Staff Agent Capability

Staff may invoke `@Agent` through ordinary natural language within their current identity,
role, Claim scope, and task. `@Agent` is an open capability entry point rather than a
fixed command language. It may combine authorised reading, comparison, retrieval,
explanation, next-step proposals, handoff inspection, and communication drafting.

Suggested controls may make capabilities discoverable, but they do not define everything
the Agent can understand. Staff read access does not imply execution permission. A send,
state mutation, external disclosure, or high-impact action still requires the action-level
authority and confirmation defined by policy.

## Model, Retrieval, and Tool Boundary

Agent orchestration depends on provider-neutral model and tool contracts. Official model
APIs, compatible relay services, custom endpoints, and local endpoints may be configured
without changing Agent behaviour.

The runtime compiles Northwind policy, role, Claim context, allowed actions, allowed
tools, and an output schema into a provider-neutral model request. Provider adapters
normalise capability declarations, structured output, refusals, incomplete responses,
errors, usage, and latency. A provider prompt is a compiled artifact, not the source of
business authority.

Structured state proposals must not be reconstructed by parsing free text when the model
profile lacks the required schema capability. Fallback is allowed only to a profile that
satisfies the same purpose, privacy, capability, policy-version, and evaluation boundary.

Retrieved knowledge is untrusted evidence. It may support an explanation with citations,
but it cannot change system instructions, grant tool permission, or authorise a
high-impact action. Structured customer policy and claim-history data use authorised
queries rather than ordinary document similarity search.

## Context Management

Each turn receives only the current Claim State, unresolved work, compact session context,
necessary recent messages, authorised structured results, and relevant cited knowledge.
Complete histories remain durable outside routine model context. Token limits must not be
managed by silently dropping confirmed facts or prior commitments.

Turn evaluation considers the complete trajectory, including proposal rejection, tool
authority, state effects, question repetition, side effects, and handoff quality. A
correct final sentence alone does not prove compliant behaviour.

## Open Rule

The exact production response to a first explicit human request requires Northwind and
user evidence. Any configured rule must remain transparent, versioned, testable, and
must never delay urgent, repeated, distress, or accessibility-related transfer.

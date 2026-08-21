# Users and Service Journeys

## Claimant

A claimant needs to report an accident, theft, or loss without first learning insurance
terminology or internal processing steps. The claimant should be able to:

- describe the event in their own words and order;
- answer short, relevant questions rather than complete an insurer-designed interview;
- inspect or correct the system's understanding when a material fact is uncertain;
- provide evidence and understand whether it is received, pending, incomplete, or needed
  later;
- know what has happened, what can progress now, who acts next, and what remains open;
- return after several days without repeating confirmed information;
- request suitable human support for urgency, difficulty, accessibility, distress, or
  preference; and
- continue through a digital or human channel without losing context.

The customer-facing language must be clear and supportive. Professional terminology,
classification, and workflow structure remain inside the system unless explaining them
helps the claimant make a decision.

## Claims Professional

A claims professional needs a structured, source-preserving account containing confirmed
facts, evidence, gaps, conflicts, internal review signals, the handoff reason, and the
specific decision or action requested. Their time should be used for support, judgement,
and exceptions rather than reconstructing the intake from a chat transcript.

## Claims Operations and System Administrators

Claims operations owns service quality, governance, routing, and operating efficiency.
Authorised administrators need a separate Control Plane to manage versioned system
configuration, model endpoints, knowledge sources, business rules, integrations,
permissions, evaluations, health, and audit history.

System administration is not claim handling. Configuration changes require validation,
publication, traceability, and rollback rather than direct unrecorded edits to a running
system.

## Approved Service Participants

Assessors, repairers, and other approved participants may later receive and update the
part of a claim context required for their assigned task. Their access must be limited by
role, task, source, and time. The claimant must not act as the manual transport layer
between these services.

## Claimant Journey

1. The claimant starts or resumes a report and explains what happened naturally.
2. The Agent acknowledges the situation, identifies the immediate need, and structures
   information internally.
3. The Agent asks only for information needed to understand safety, select the next safe
   action, or resolve a material uncertainty.
4. Evidence and authorised knowledge or policy results are attached with source and
   limitations.
5. The system progresses safe work, records later requirements, or transfers a structured
   context for professional attention.
6. The claimant receives a plain-language status, responsibility, and next step.
7. Later interactions continue from the same claim context.

## Staff Journey

1. Staff receive a prioritised work item with confirmed facts, sources, evidence state,
   gaps, and the action requested.
2. Staff inspect the original source when needed and record their decision separately.
3. The system writes the authorised result to shared state without rewriting source
   evidence.
4. The claimant receives an appropriate update without internal notes or sensitive
   signals.

## Experience Principle

Users should choose the Agent because it is immediate, competent, clear, resumable, and
able to coordinate digital and human work. Adoption must come from reduced effort and
preserved control, not claims of model intelligence or universal superiority over phone
and web-form channels.

## Research Boundary

Challenge facts, public evidence, participant statements, team decisions, hypotheses,
and Northwind-specific unknowns remain distinct. New findings enter this specification
only when their source, limits, and product consequence are recorded.

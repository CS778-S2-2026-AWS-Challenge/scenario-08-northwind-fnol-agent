# Safety and Governance

## Decision Authority

Model output, retrieved knowledge, structured provider results, and extracted evidence
are inputs to a decision, not unlimited authority. Deterministic rules or authorised
staff control high-impact actions.

User intent, model proposal, runtime approval, tool execution, and execution result are
separate records. Prompt compliance, valid JSON, a tool-call-shaped response, or a staff
read permission cannot independently authorise a Claim mutation, data disclosure, human
handoff, external request, or high-impact decision.

- Ambiguous coverage, excess, liability, or policy applicability moves to professional
  review before a related high-impact action.
- A fraud signal requests review and retains evidence; it never declares a claimant
  fraudulent.
- Severity may support prioritisation but is not approval, rejection, or liability.
- The Agent does not approve or reject claims.
- The Agent does not diagnose injury or imply emergency contact it did not perform.

## Safety Escalation

Explicit injury, continuing danger, or another approved urgent signal interrupts ordinary
intake. The claimant receives concise, bounded guidance and an urgent handoff. Trigger
rules are versioned and tested; controlled fixture rules are not automatically approved
production policy.

## Knowledge and Model Safety

- Knowledge retrieval must filter authority, visibility, insurer, product, jurisdiction,
  version, and effective period before ranking.
- Answers retain citations and state material limitations or conflict.
- Instructions inside retrieved documents are untrusted content and cannot change system
  authority or tool permissions.
- Model providers receive only the minimum authorised context. Provider retention,
  training use, region, and logging terms must be reviewed before real customer data is
  sent.
- Unsupported structured output, tool use, or model capability is an explicit error, not
  a reason to bypass validation.
- Model profiles declare verified capabilities, allowed purposes, privacy terms, and
  evaluation results. A fallback profile must satisfy the same boundary and must not
  silently expand data scope or weaken structured-output requirements.

## Configuration Governance

Control Plane changes use versioned draft, validation, publication, and rollback. Every
published change records actor, reason, scope, effective time, validation evidence, and
previous version. Secrets are stored through an approved secret manager and cannot be
returned by the administration API.

High-impact rules, model changes, identity changes, data-profile changes, and external
tool permissions require role-based approval. Emergency rollback must preserve the audit
record.

## Evidence and Traceability

Material facts, retrievals, interpretations, signals, routing, overrides, handoffs,
configuration publications, and tool actions record source references, reason codes,
actor, time, and outcome. A staff decision is stored separately from the source evidence
that motivated it.

Each turn must preserve the model proposal, rejected and approved actions, authority
results, tool outcomes, new Claim revision, unresolved work, limitations, and final
role-safe response. Errors record their layer, retry class, state effect, safe message,
and diagnostic reference. A timeout during an external side effect remains an unknown
outcome until reconciled; it must not be treated as either success or safe-to-retry
failure without evidence.

## Privacy and Access

Access follows role, task, claim ownership, and minimum necessity. Prototype and source
control data are anonymous or synthetic. Production identity, consent, retention,
encryption, deletion, residency, access review, incident response, and recovery remain
required before production use.

## Research Governance

Source facts, participant statements, observations, hypotheses, team decisions, targets,
and open questions remain distinguishable. Public evidence may support a design mechanism
but cannot establish Northwind-specific prevalence or business value without Northwind
evidence.

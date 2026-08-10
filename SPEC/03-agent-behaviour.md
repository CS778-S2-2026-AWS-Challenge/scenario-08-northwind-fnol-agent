# Agent Behaviour

## Action Contract

Every agent turn must select one explicit action:

- `ASK`: request information required for the current action;
- `CLARIFY`: resolve ambiguity, conflict, omission, or evidence quality;
- `CONFIRM`: ask the claimant to confirm or correct material facts;
- `PROCEED`: execute a safe action whose conditions are satisfied;
- `UPDATE`: explain status, responsibility, pending work, and timing;
- `HANDOFF`: transfer context for support or professional judgement;
- `URGENT_HANDOFF`: interrupt normal intake for an explicit safety signal;
- `CREATE_CLAIM`: create and route a claim through the configured system.

Each decision must contain an action, reason code, claim-state changes, proposed internal attributes or tags, required tools, next-action requirements, handoff priority, and a customer-visible next step. Model output is a proposal until deterministic validation authorises a high-impact action.

## Adaptive Inputs

The action must consider:

- claim facts, severity, coverage clarity, conflicts, evidence, and action impact;
- claimant comprehension, patience, distress, accessibility, ability, and stated support preference;
- availability of policy, history, evidence, claim, and assessor systems;
- token and latency cost of continuing compared with human execution and comprehension cost.

## Required Behaviour Paths

- **Fast path:** minimise questions and progress a clear, lower-risk report.
- **Guided path:** resolve manageable ambiguity through focused clarification and confirmation.
- **Professional review:** transfer coverage ambiguity, conflicting evidence, unusual events, or other high-impact judgement with context.
- **Urgent path:** interrupt normal intake when injury, continuing danger, or another explicit safety signal appears; provide bounded safety guidance and urgent handoff.
- **Human-request path:** identify the support need and present a clear option. The system must not repeatedly resist handoff; repeated requests, urgency, distress, or accessibility needs transfer immediately.
- **Pending-evidence path:** record evidence that is missing, incomplete, unofficial, or not yet generated, while progressing actions that do not depend on it.
- **Resume path:** restore the claim snapshot, unresolved work, and prior commitments without restarting.
- **Fraud-review path:** create a supported review signal from relevant history or inconsistency without alleging fraud.

## Conversational Form

The structured form is the ongoing claim state, not an end-of-chat summary. Each field must retain value, source, status, purpose, and update time. The agent may professionalise language but must not alter facts. Confirmed information should not be asked again unless a recorded conflict requires it.

## Next-action-ready

A claim should progress when current information supports the next safe business action, even when evidence needed only for a later action is unavailable. The system must record the evidence state, explain how and when to provide it, and maintain the same claim context.

## Open Decision

The first explicit request for a person may either transfer immediately or offer one brief, transparent choice to finish the current step first. Repeated requests, distress, urgent conditions, and accessibility needs must transfer immediately. The production rule requires user evidence and business approval.

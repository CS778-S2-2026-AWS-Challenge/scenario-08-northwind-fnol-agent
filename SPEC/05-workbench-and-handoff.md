# Workbench and Handoff

## Claim Operations Workbench

The internal workbench is a projection of claim state, evidence, decisions, handoffs, staff actions, and events. It must not become a second status record that staff manually reconcile.

The workbench supports:

- Urgent, New/Untriaged, Ready to Progress, Awaiting Evidence, Professional Review, Ready to Create, and Created/Routed views;
- filtering by state, tag, priority, assignee, next action, and service timing;
- claim detail showing the form, field sources, evidence, conflicts, internal attributes, handoff, and communication history;
- assignment and completion of staff actions;
- confirmation, dismissal, override, and resolution of proposed tags or signals;
- write-back to shared claim state and an appropriate claimant status update.

Sensitive review signals must never be exposed directly in the claimant interface.

## Handoff Packet

A standard or urgent handoff includes:

- claimant-confirmed incident summary;
- current structured form and field provenance;
- available evidence and its state;
- missing, pending, conflicting, or low-confidence information;
- policy or history evidence relevant to the transfer;
- handoff reason and priority;
- the decision or action requested from staff;
- prior customer communication and promised next step.

The receiving staff member should not need to repeat questions whose answers are already confirmed.

## Claim Creation and Routing

When creation conditions are satisfied, the system creates and routes a claim through a mock or configured claims service. The claimant receives a claim number or explicit creation state, progress, any pending evidence, who acts next, an expected timeframe, and a way to resume.

Assessor booking is conditional on an authorised rule. It must not be mechanically coupled to one severity label.

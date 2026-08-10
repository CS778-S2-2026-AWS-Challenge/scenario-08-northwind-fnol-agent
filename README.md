# Northwind FNOL Agent

Northwind FNOL Agent is a trusted, adaptive First Notice of Loss service for Northwind Insurance. It helps a claimant describe an incident in their own words, turns that account into a visible and correctable claim record, and chooses the next safe action according to the claim, evidence, user, and system state.

The product is designed to sit between a rigid web form and a fully manual phone process. Straightforward claims can move quickly, while ambiguity, urgency, support needs, or high-impact decisions are transferred to staff with the claimant's confirmed context intact.

## Product Goal

The service should:

- reduce avoidable claimant questions, repetition, and waiting;
- progress a claim when the information is sufficient for the next safe action, even if later evidence is still pending;
- preserve context across sessions and human handoffs;
- give claims staff a workbench backed by the same claim state seen by the agent;
- keep coverage, fraud, safety, and other high-impact decisions within explicit business and human-review boundaries;
- make claimant effort, human effort, and agent cost observable.

## Users

- **Claimants** report an incident, confirm the structured account, provide evidence, and follow progress.
- **Claims professionals** review ambiguity, risk signals, handoffs, and claim actions without recollecting known facts.
- **Claims operations** owns the process, service quality, governance, and operating efficiency.

## Current Stage

The project is in Sprint 1 and is building a full-path prototype. The prototype may use controlled scenarios and mock integrations, but each demonstrated path must change shared system state and remain traceable. Production integrations, security controls, and final business rules will be refined as Northwind data and AWS service availability are confirmed.

Detailed product requirements are maintained in `SPEC/`, sprint plans in `sprint/`, engineering and research documentation in `docs/`, and demonstrators in `prototype/`.

# Documentation

This directory separates current engineering documentation, target design, current status,
research evidence, and historical delivery records. Product requirements belong in `SPEC/`, and
time-bound commitments belong in `sprint/`.

## Authority

- `SPEC/` defines product behaviour and acceptance.
- Current engineering documents define implemented or governed boundaries only where they say so.
- `design/` records target architecture and rationale; it does not prove implementation.
- `status/` records evidence observed at a named point in time; it does not create a contract.
- `research/` informs product decisions within the limitations stated by each source.
- `skills/` holds the repository governance skill, the sole current source of governance rules.
- `archive/` preserves dated planning, validation, demonstration, and superseded governance
  records; it is not current product or engineering authority.

Historical records must not override the current specification, API, data contracts, authority
rules, or sprint commitments.

## Current Sprint Planning

The current time-bound direction and weekly execution records are maintained under `sprint/`:

- [Sprint 3 Validation Prototype Overview](../sprint/sprint3.md)
- [Sprint 3 Week 5 Plan](../sprint/week5/sprint3-week5-plan.md)
- [Sprint 3 Week 5 Kanban Draft](../sprint/week5/sprint3-week5-kanban-draft.md)
- [Sprint 2 Week 3 Parallel Plan](../sprint/week3/sprint2-week1-parallel-plan.md)
- [Sprint 2 Week 4 Integration Plan](../sprint/week4/sprint2-week2-integration-plan.md)

## Stable Entry Points

These paths remain stable because repository instructions and contributor workflows depend on
them:

- [Repository Governance Skill](skills/repo-governance-for-novice/SKILL.md) — routed from
  [AGENT.md](../AGENT.md); where an archived document disagrees with it, the skill prevails
- [Current API Contract](api.md)
- [Documentation Index](README.md)
- [Northwind FNOL Product Soul](product-soul.md) — product direction and principles shared by the repository and the project plan
- [Frontend and Runtime Quality Standard](frontend-and-runtime-quality-standard.md) — authoritative big-picture, claimant/workbench, component, token, routing, runtime-boundary, and acceptance standard for frontend and runtime design

## Current Engineering Documents

- [Agent Action to Claim Context Command Boundary](agent-action-command-boundary.md)
- [Agent Runtime Policy](agent-runtime-policy.md)
- [FNOL Agent Behaviour Catalogue](agent-behaviour-catalogue.md)
- [Claim Creation and Provider Adapter Boundary](claim-creation-boundary.md)
- [Claimant-to-Staff Messaging Journey](claimant-staff-messaging-journey.md)
- [Control Plane Roles and Publication Lifecycle](control-plane-governance.md)
- [First Control Plane Interface Contract](control-plane-interface.md)
- [Shared Claim State Transaction Boundary](claim-state-transaction-boundary.md)
- [Data Architecture](data-architecture.md)
- [Fixtures and Test Conventions](fixtures_convention.md)
- [FNOL Information Model and Field Taxonomy](fnol-field-model.md)
- [Identity and Developer-Mode Contract](identity-and-developer-mode.md)
- [MinIO Object-Storage Boundary](minio-object-storage.md)
- [Provider-Neutral Model Gateway](model-gateway.md)
- [Persistence Contract](persistence-schema.md)
- [Policy and Claim-History Retrieval Contract](policy-history-mapping.md)
- [RAG Knowledge Ingestion](rag-ingestion.md)
- [Filtered RAG Retrieval](rag-retrieval.md)
- [RAG Source Inventory and External-Service Scenario](rag-source-and-external-service-contract.md)
- [Registry and Dynamic FNOL Form Design](registry_design.md)
- [Runtime Deployment Profiles](runtime-deployment-profiles.md)
- [Staff Tag Registry](staff-tag-registry.md)
- [Repository layout, start commands, and verification](../README.md#repository-layout)

Generated contract snapshots are mechanical drift sentinels. The current AuditEvent
envelope snapshot is [audit-event.schema.json](contracts/audit-event.schema.json) and is
regenerated with `py -3.12 scripts/export_audit_contract.py`; the semantic authority
remains [Persistence Contract](persistence-schema.md).

These documents are normative only for the boundaries they explicitly own. An implemented
contract change must update the implementation, consumers, fixtures, and tests in the same pull
request.

## Target Design

The Agent Runtime design is deliberately separated from current transport and implementation
evidence:

- [Agent Runtime Target](design/agent-runtime/agent-runtime-target.md)
- [Agent Runtime Migration](design/agent-runtime/agent-runtime-migration.md)
- [Agent Behaviour and Model Gateway Design](design/agent-runtime/agent-behaviour-and-model-gateway-design.md)

The target defines future engineering direction, the migration document isolates the temporary
compatibility path, and the design study records research and rationale. Current API and runtime
documents remain authoritative for implemented behaviour.

## Current Status Records

- [Agent Runtime Progress](status/agent-runtime-progress.md)
- [Runtime Profile Validation Record](status/runtime-profile-validation.md)
- [MVP Capability Register](status/mvp-capability-register.md)

Status records must name repeatable evidence and their limitations. They should be updated or
superseded when the implementation state changes.

## Research Evidence

- [Research-to-Product Traceability](research/research-to-prototype-traceability.md)
- [FNOL Evidence Sheet](research/fnol-evidence-sheet.md)
- [Pain Point Analysis](research/pain-point-analysis.md)
- [User Personas](research/user-personas.md)
- [FNOL As-Is Process and Reporting Fields](research/fnol-as-is-process-and-reporting-fields.md)
- [Existing Claims Fraud Controls and Verification](research/existing-claims-fraud-controls-and-verification.md)
- [Insurance Industry Interview and User Observation](research/insurance-industry-interview-and-user-observation.md)
- [Participant Information and Consent](research/participant-information-and-consent.md)
- [Claimant Survey Response Export](research/claimant-survey-final-responses.csv)
- [Claimant Survey Form Export](research/insurance-claim-customer-experience-survey.pdf)

Research evidence informs product decisions but does not establish Northwind-specific prevalence,
policy, or production authority unless the source explicitly supports that claim.

## Historical Delivery Archive

The archive keeps records needed for issue, test, and presentation traceability while removing
them from the current-document layer. Original `day*` and `d4-*` names are retained inside the
archive because they identify the Sprint task that produced the evidence.

### Governance

Superseded on 2026-08-30 by the
[Repository Governance Skill](skills/repo-governance-for-novice/SKILL.md); kept as historical
reference and never revised again. Where they disagree with the skill, the skill prevails.

- [Repository Operation Rules (archived)](archive/governance/repo_rule.md)
- [Development Conventions (archived)](archive/governance/development-conventions.md)

### Sprint 1

Planning:

- [Day 3 Implementation Map](archive/sprint-1/planning/day3-implementation-map.md)

Validation:

- [Day 3 Evidence and Scenario Integration Results](archive/sprint-1/validation/day3-bdfa-integration-results.md)
- [Day 4 Assembled Prototype Integration Results](archive/sprint-1/validation/day4-assembled-prototype-integration-results.md)
- [Day 4 API and Data-Boundary Verification](archive/sprint-1/validation/day4-api-data-boundary-verification.md)
- [Day 4 Routing and Workbench Write-Back Verification](archive/sprint-1/validation/day4-routing-workbench-writeback-verification.md)
- [Day 4 Urgent and Human-Support Verification](archive/sprint-1/validation/day4-urgent-human-support-verification.md)
- [Day 4 Evidence-State and Visibility Defects](archive/sprint-1/validation/day4-evidence-visibility-defects.md)
- [Day 4 Responsive and Accessibility Verification](archive/sprint-1/validation/day4-responsive-accessibility-verification.md)
- [Day 4 Journey Test Records](archive/sprint-1/validation/d4-t02-test-records.md)
- [Day 5 Claim-Persistence Validation](archive/sprint-1/validation/day5-claim-persistence-validation.md)
- [Day 5 Policy-Review Validation](archive/sprint-1/validation/day5-policy-review-validation.md)
- [Day 5 Session and Evidence Validation](archive/sprint-1/validation/day5-session-evidence-validation.md)
- [Day 5 Staff Revision Validation](archive/sprint-1/validation/day5-staff-revision-validation.md)
- [Day 5 Clear-Claim Validation](archive/sprint-1/validation/day5-clear-claim-validation.md)
- [Day 5 Fact-Source and Confirmation Validation](archive/sprint-1/validation/day5-fact-source-and-confirmation.md)
- [DynamoDB Fixture Examples](archive/sprint-1/validation/api-dynamodb-fixture-examples.md)

Demonstration:

- [Day 4 Technical Demonstration Runbook](archive/sprint-1/demo/day4-technical-demo-runbook.md)
- [Day 4 Demonstration Screenshots](archive/sprint-1/demo/visual-evidence/README.md)

### Sprint 2

- [External-Service Validation](archive/sprint-2/validation/day4-external-service-validation.md)
- [Canonical Scenario Validation](archive/sprint-2/validation/day4-canonical-scenario-validation.md)
- [Regression Entry Points](archive/sprint-2/validation/day5-regression-entrypoints.md)

### Sprint 3

- [Issue #371 RAG and Structured-Query Acceptance Evidence](archive/sprint-3/validation/issue-371-rag-structured-query-evidence.md)
- [Issue #389 Query Source and No-Result Validation](archive/sprint-3/validation/issue-389-query-source-and-no-result.md)
- [Issue #465 RAG, Provider Isolation, and Control Plane Validation](archive/sprint-3/validation/issue-465-rag-provider-control-validation.md)

Static demonstrators and earlier scripts under `prototype/` and `pre_archive/` are also historical
evidence. They must not silently override current requirements or contracts.

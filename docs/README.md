# Documentation

This directory contains current engineering contracts, development guidance, user
research, and dated delivery evidence. Product requirements belong in `SPEC/`, and
time-bound commitments belong in `sprint/`.

## Current Engineering Contracts

- [Repository Operation Rules](repo_rule.md)
- [Current API Contract](api.md)
- [Development Conventions](development-conventions.md)
- [Agent Runtime Policy](agent-runtime-policy.md)
- [Provider-Neutral Model Gateway](model-gateway.md)
- [Data Architecture, Runtime Profiles, and Knowledge Retrieval](data-architecture.md)
- [FNOL Information Model and Field Taxonomy](fnol-field-model.md)
- [Registry and Dynamic FNOL Form Design](registry_design.md)
- [Persistence Contract](persistence-schema.md)
- [Policy and Claim-History Retrieval Contract](policy-history-mapping.md)
- [Claim Creation and Provider Adapter Boundary](claim-creation-boundary.md)
- [MinIO Object-Storage Boundary](minio-object-storage.md)
- [RAG Source Inventory and External-Service Scenario](rag-source-and-external-service-contract.md)
- [Fixtures and Test Conventions](fixtures_convention.md)
- [Repository layout, start commands, and verification](../README.md#repository-layout)

These documents are normative only for the boundaries they explicitly own. A contract
change must update affected implementation, consumers, fixtures, and tests in the same
pull request when the changed behaviour is implemented.

## Documentation Layers

`SPEC/` defines product behaviour and acceptance. Current engineering contracts define
implemented boundaries. The Agent Runtime Target defines the future engineering direction
without claiming implementation. The Migration document isolates the deprecated fallback,
and the Progress document records exact-head evidence. These layers must not be treated as
interchangeable proof.

- [Agent Runtime Target](agent-runtime-target.md) - future engineering direction
- [Agent Runtime Migration](agent-runtime-migration.md) - deprecated compatibility path
- [Agent Runtime Progress](agent-runtime-progress.md) - current evidence ledger

## Non-Normative Design Rationale

- [Agent Behaviour and Model Gateway Design](agent-behaviour-and-model-gateway-design.md)

This research and decision draft supports issues #233 and #234. It records sources,
alternatives, and rationale, but it does not replace the target document, current API, or
runtime policy.

## User Research

- [Research directory](User_Research_and_Pain_Points/)

Research evidence informs product decisions but does not override `SPEC/` or establish
Northwind-specific prevalence without Northwind evidence.

## Sprint 1 Historical Evidence

The following records preserve dated planning, implementation, test, and demonstration
evidence. They do not describe the current product or engineering contract unless a
current document explicitly adopts the same rule.

- [Day 3 implementation map](day3-implementation-map.md)
- [Day 3 evidence and scenario integration results](day3-bdfa-integration-results.md)
- [Day 4 assembled prototype integration results](day4-assembled-prototype-integration-results.md)
- [Day 4 API and data-boundary verification](day4-api-data-boundary-verification.md)
- [Day 4 routing and workbench write-back verification](day4-routing-workbench-writeback-verification.md)
- [Day 4 urgent and human-support verification](day4-urgent-human-support-verification.md)
- [Day 4 evidence-state and visibility defects](day4-evidence-visibility-defects.md)
- [Day 4 responsive and accessibility verification](day4-responsive-accessibility-verification.md)
- [Day 4 journey test records](d4-t02-test-records.md)
- [Day 4 technical demonstration runbook](day4-technical-demo-runbook.md)
- [Day 4 demonstration screenshots](demo-evidence/README.md)
- [Day 5 claim-persistence validation](day5-claim-persistence-validation.md)
- [Day 5 policy-review validation](day5-policy-review-validation.md)
- [Day 5 session and evidence validation](day5-session-evidence-validation.md)
- [Day 5 staff revision validation](day5-staff-revision-validation.md)
- [Day 5 clear-claim validation](day5-clear-claim-validation.md)
- [Day 5 fact-source and confirmation validation](day5-fact-source-and-confirmation.md)
- [DynamoDB fixture examples](api-dynamodb-fixture-examples.md)

Static demonstrators and earlier scripts under `prototype/` and `pre_archive/` are also
historical evidence. They must not silently override current requirements, API schemas,
data architecture, authority rules, or sprint commitments.

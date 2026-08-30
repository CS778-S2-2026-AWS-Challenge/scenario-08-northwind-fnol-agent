# Day 5 fixture and regression entry points

Issue: #281

## Scope

This record establishes one repeatable entry point for the canonical fixture checks and the
external-service checks, and draws an explicit line between what a run proves and what it
does not.

The problem it addresses is not a missing check. The repository already has nineteen scripts
under `scripts/`. The problem is that running them ad hoc produces a clean terminal that reads
as "everything works", when several of those scripts prove nothing at all unless an external
provider happens to be configured. A non-implementer cannot tell the two apart from the output.

Recorded on `main` at `dfd0b722`.

## Repeatable checks

```text
python scripts/run_regression_entrypoints.py --list
python scripts/run_regression_entrypoints.py
```

`--list` describes every entry point and its tier without executing anything. The plain run
executes the fixture tier and reports the provider tier.

Environment for the recorded run: Python 3.12.10 on a clean Windows clone, no MinIO, no MongoDB,
no model gateway, no ingested knowledge store.

## The two tiers

**Fixture-backed checks are executed.** They need only the repository and a Python environment,
they are repeatable by anyone, and a failure is a real regression.

| Entry point | Stack | What a pass proves |
| --- | --- | --- |
| `run_scenarios.py` | Evidence | every canonical scenario loads and seeds with a consistent claim state |
| `run_evidence_fixtures.py` | Evidence | each evidence stage keeps its declared source and visibility |
| `run_evidence_paths.py` | Evidence | each business path reaches its declared evidence state |
| `run_evidence_path_defects.py` | Evidence | no evidence-path defect across the five business paths |
| `run_evidence_visibility_fixtures.py` | Evidence | each path entry matches its workflow, action, evidence and handoff baseline |
| `check_agent_runtime_mapping.py` | Agent runtime | the documented agent runtime ledger matches the implemented values |
| `validate_runtime_profiles.py` | Data platform | each runtime profile composes and reports its own readiness honestly |

**Provider-backed checks are not executed unless configured.** They are reported as
`NOT EXECUTED` with the exact configuration required, and never as passing.

| Entry point | Stack | Requires | What it would prove |
| --- | --- | --- | --- |
| `run_minio_fastapi_smoke.py` | Data platform | `NORTHWIND_OBJECT_STORAGE_ADAPTER=s3_compatible` and a reachable MinIO endpoint | object storage addressing and presigned access against a live S3-compatible store |
| `verify_minio_rag_provider_failure.py` | Data platform | the same | retrieval degrades explicitly when the object store is unavailable |
| `query_knowledge.py` | Knowledge/RAG | an ingested knowledge store and its configured adapter | filtered retrieval returns citations from real ingested sources |

## Result

Recorded run on `dfd0b722` with no provider configured:

```text
7 fixture-backed checks executed, 0 of 3 provider-backed checks executed.
Provider-backed capability is NOT demonstrated by this run. A check that did not execute is
not evidence; report those capabilities as unavailable or fixture-dependent rather than
verified.
No fixture-backed regression detected.
```

All seven fixture-backed checks pass. No provider-backed check ran, so this run is evidence for
repository behaviour only.

## Why the provider tier does not fail the run

A missing local MinIO is not a regression, so an absent provider does not produce a non-zero
exit. It would be equally wrong to let it pass silently, so the run prints the gap, names the
configuration required, and states plainly that the capability is not demonstrated. Exit status
is non-zero only when a fixture-backed check fails.

This is the distinction the issue asks for: a non-implementer reading the output can tell
which lines are evidence of repository behaviour and which are placeholders for a provider that
was never contacted.

## Boundaries and remaining limitations

- The fixture tier proves repository behaviour against synthetic records. It is not evidence of
  AWS, Cloudflare, MongoDB, MinIO, or model-provider behaviour.
- Provider detection is deliberately shallow. `NORTHWIND_OBJECT_STORAGE_ADAPTER` selects the
  adapter but does not prove the endpoint is reachable, so a configured run can still fail at
  the endpoint; that failure is real and surfaces as `FAIL` rather than `NOT EXECUTED`.
- `query_knowledge.py` has no single environment variable that proves an ingested store exists,
  so it is always reported as not executed. Treat a knowledge-retrieval claim as unverified
  until someone records an explicit ingested-store run.
- Three scripts take required command-line arguments and are therefore outside this entry point:
  `check_runtime_profile.py`, `verify_local_rag.py`, and `ingest_knowledge_source.py`. They
  remain individually runnable and are named here so their absence is not mistaken for
  completeness.
- `upload_knowledge_sources.py` and `reset_demo.py` mutate state and are deliberately excluded
  from a regression entry point.

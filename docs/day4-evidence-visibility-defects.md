# Day 4 evidence state and visibility check

Issue: #140

This check compares the evidence state and visibility each primary business path declares against the live claimant and staff projections produced from the canonical scenario it names.

The original audit found two different defects:

1. `PATH_FIXTURE_NOT_ANCHORED` — the path fixture carried a second invented evidence set instead of classifying the canonical scenario's records.
2. `INTERNAL_EVIDENCE_VISIBLE_TO_CLAIMANT` — the claimant evidence API returned staff/external-system records and exposed an aggregate count derived from the wider internal set.

Both defects are now resolved. `tests/test_evidence_visibility_check.py` is a zero-defect regression gate: any new path mismatch, claimant leak, or incomplete staff projection fails the suite instead of being added to a tolerated known-defect list.

## Current status

- `PATH_FIXTURE_NOT_ANCHORED`: resolved by moving path evidence ownership into canonical scenarios and reducing the path fixture to `evidence_id + visibility` classifications.
- `INTERNAL_EVIDENCE_VISIBLE_TO_CLAIMANT`: resolved by Issue #219 / PR #220 through the shared claimant evidence-visibility policy and claimant-safe aggregate derivation.

## How to verify

```powershell
py -3.12 scripts/run_evidence_path_defects.py
```

The command should now exit `0` and print:

```text
No evidence path defects found.
```

The checker seeds each canonical scenario, calls the claimant evidence endpoint and the staff Workbench projection, and compares those live responses with the path classification.

## Resolution 1 — canonical scenarios own evidence

The previous `tests/fixtures/evidence/path-entry-visibility.json` embedded complete `EvidenceRecord` payloads. That created two sources of truth: a canonical scenario could contain one set of records while the path fixture silently described another.

The contract is now:

- the canonical scenario owns every `EvidenceRecord`, including lifecycle state, source, related fields, timing, and provenance;
- the path fixture stores only the canonical `evidence_id` and the path-specific visibility classification;
- `load_evidence_path_fixtures()` resolves each reference back to the canonical scenario and rejects embedded evidence payloads;
- every canonical evidence record must be classified exactly once for that path — missing, duplicate, or unknown references fail loading;
- path claim state, evidence summary, claim id, and customer next step are projected directly from the canonical scenario rather than recomputed from a private path copy.

The five path anchors are now:

| Path | Canonical scenario | Canonical evidence classified by the path |
| --- | --- | --- |
| fast | AT-01-clear-motor | `evd_fixture_path_fast_image` |
| professional review | AT-02-coverage-ambiguity | `evd_fixture_at02_damage_photos`, `evd_fixture_at02_plumber_note`, `evd_fixture_at02_weather_capture` |
| urgent | AT-04-urgent | `evd_fixture_path_urgent_image` |
| human request | AT-05-human-request | `evd_fixture_path_human_image` |
| pending evidence | AT-06-pending-evidence | `evd_fixture_at06_police`, `evd_fixture_at06_agency`, `evd_fixture_at06_internal` |

AT-02 deliberately keeps the richer professional-review evidence introduced by the employee Workbench work; this fix does not replace it with the obsolete path-fixture records.

### Scenario-level invariant

`ScenarioFixture` now also rejects a claim whose declared `claim_state.evidence` or `evidence_summary` cannot be derived from its own evidence records. This closes the broader class of drift that allowed retrieval-only review fixtures to claim a received evidence record they did not hold.

Retrieval records and evidence records remain distinct. For example, policy/history retrieval fixtures with no `EvidenceRecord` correctly use `evidence=not_started` even though they may contain sourced retrieval data and professional-review signals.

## Resolution 2 — claimant record and aggregate visibility

Issue #219 centralised the claimant-facing default in `backend/services/evidence_visibility.py`:

```text
claimant source -> shared
non-claimant source -> internal_only
```

The claimant evidence service filters records before constructing claimant DTOs. The claimant claim projection derives its evidence summary from the same visible record set, preventing an aggregate side channel.

For canonical AT-06 this means:

- claimant evidence list: `evd_fixture_at06_police` only;
- claimant pending aggregate: `1`;
- Workbench evidence list: all three records;
- authoritative internal pending aggregate: `3`.

The path visibility fixture classifies the same three canonical records, so the live projection and the declared visibility rule are now checked against the same evidence universe.

## Regression boundaries

The following changes must fail tests unless the contract is intentionally revised in the same pull request:

- adding canonical evidence without adding a path visibility classification;
- referencing an evidence id that is not in the canonical scenario;
- embedding a duplicate evidence payload in the path fixture;
- declaring scenario evidence state or summary inconsistent with the scenario records;
- exposing staff/external-system evidence to the claimant under the current MVP rule;
- omitting a persisted canonical evidence record from the staff Workbench projection;
- hiding a claimant-visible canonical record from the claimant projection.

A future product decision may introduce an explicit visibility class independent of evidence source. If that happens, the shared claimant projection and handoff policy must be migrated together; a single endpoint must not invent a separate rule.

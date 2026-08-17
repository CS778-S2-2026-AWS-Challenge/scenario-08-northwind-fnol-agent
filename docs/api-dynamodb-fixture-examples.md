# API and DynamoDB Fixture Examples

## Purpose and boundary

`backend/demo_data/scenarios/AT-08-resume.json` is the concrete synthetic example
for a working claim, session, messages, structured form, and evidence record.
The fixture is validated by the same Pydantic contract models used by the API
and is loaded only through the provider-neutral `PersistenceRepository`.

The DynamoDB layout below is a logical adapter example, not confirmation of an
AWS table, index, region, or production key design. Logical storage keys stay
inside the persistence adapter and are never part of claimant API payloads.

## Concrete record mapping

| Record | Fixture example | Repository operation | Logical adapter key | Public API read |
|---|---|---|---|---|
| Working claim | `clm_fixture_at08` | `get_claim(claim_id, customer_id)` | partition `CLAIM#clm_fixture_at08`, sort `CLAIM` | `GET /api/v1/claims/clm_fixture_at08` |
| Session | `ses_fixture_at08` | `get_session(claim_id, session_id, customer_id)` | partition `CLAIM#clm_fixture_at08`, sort `SESSION#ses_fixture_at08` | `GET /api/v1/claims/clm_fixture_at08/sessions/ses_fixture_at08` |
| Claimant message | `msg_at08_claimant` | `list_messages(claim_id, session_id, customer_id)` | partition `CLAIM#clm_fixture_at08`, time-ordered `MESSAGE#...#msg_at08_claimant` sort | `GET /api/v1/claims/clm_fixture_at08/sessions/ses_fixture_at08/messages` |
| Structured form | `incident.description` and `incident.location` | Stored and revisioned with the working claim | Uses the claim item; no separate public key | Included in the claimant-safe claim response |
| Evidence | `evd_fixture_at08_police` | `list_evidence(claim_id, customer_id)` | partition `CLAIM#clm_fixture_at08`, sort `EVIDENCE#evd_fixture_at08_police` | `GET /api/v1/claims/clm_fixture_at08/evidence` |

The same claim can be listed for its authenticated owner through the logical
customer lookup `CUSTOMER#cus_demo` ordered by claim creation time. Whether
that lookup becomes a DynamoDB secondary index or another query mechanism
remains an adapter decision.

## Access-pattern coverage

The AT-08 fixture exercises these planned access patterns:

1. read one owned working claim;
2. restore a bounded session-resume package;
3. page claimant-visible messages while filtering an internal-only message;
4. list pending evidence without returning provenance or storage state;
5. preserve confirmed form fields so they are not asked again;
6. keep all child records under the same claim and customer ownership boundary.

`tests/test_day3_scenarios.py` rejects broken parent links and verifies that
claim, session, message, and evidence responses contain no logical partition or
sort keys, internal storage provenance, or internal-only note. This keeps the
fixture useful for a future DynamoDB adapter without coupling the public API to
that adapter.

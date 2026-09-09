# Control Plane implementation status

Updated: 2026-09-09

This status record reports what is currently backed by the repository and what
still requires implementation. It is evidence, not a replacement for the
Control Plane contract in `docs/control-plane-governance.md` or the API schema
in `docs/api.md`.

## Implemented and server-backed

- Versioned configuration records with revision checks, validation, independent
  approval for high-impact publication, publication, withdrawal, supersession,
  rollback, idempotency, and configuration audit events.
- Model configurations use `configuration_key=profile_id` and can publish one catalog
  containing `qwen-local` as primary plus `nowcoding-gpt54mini` as a selectable claimant
  profile. Publication validation requires structured output and tool calling to be declared;
  credentials remain secret references and are never returned to claimant capabilities.
- Release Sets and Runtime Snapshots for one complete published configuration
  boundary per environment and runtime profile.
- Customer and staff account creation, revision-checked updates, safe session listing, and active-
  session revocation through the existing identity repositories, with idempotency and append-only
  administration audit events. Local SQLite adapters upgrade legacy account and session schemas in
  place.
- Registered integration projections, bounded health-check operation history, service-keyed
  publication slots, and exact Integration references in active Release Sets.
- Operation records with durable SQLite support, state revisions, status URLs, idempotency,
  aggregate state/kind metrics, persisted claimant/staff model usage, cost estimates from published
  per-model rates, rate-limit windows, and configured token, cost, and rate-limit alerts. Missing
  provider usage or prices remain explicit as partial or unknown data.
- Immutable evaluation evidence linked to model, knowledge, rule, data, fixture,
  and source versions.
- Governed knowledge source metadata, object-store content boundary,
  ingestion/chunking, retrieval checks, lifecycle transitions, and lifecycle
  audit events.
- Independently versioned Agent instructions, tool policies, controlled rules,
  and feature settings.
- Versioned access-policy records containing role, actor type, scopes,
  visibility classes, active state, and protected credential references; a
  published policy can restrict an authenticated principal's existing scopes.
- Administration-only cross-resource audit search with bounded filters.
- React/Vite Admin Console workflows for configuration and knowledge lifecycle actions, Release
  Sets, Runtime Snapshot resolution, evaluation evidence, operation metrics, Integration health,
  restricted audit search, and customer/staff account creation, updates, and session revocation.
  The console uses shared design
  tokens, authenticated API calls, projected action availability, explicit confirmation, revision
  headers, idempotency keys, and authoritative reloads after writes.

## Runtime wiring currently verified

- The model gateway resolves a published model reference from the active Release
  Set when one exists, then re-checks the deployment-owned protocol, endpoint,
  purpose, privacy class, prompt version, and structured-output boundary.
- The minimal model Runtime consumes the Session-bound profile and persists a read-only
  `RuntimeTraceRecord` for the `claim.read` continuation. A general Runtime trace query,
  isolated provider probe endpoint, and complete live validation evidence for both profiles
  remain open.
- A shared runtime configuration resolver now loads one coherent active Release Set
  snapshot for the model gateway, claimant Agent instruction, and staff model gateway.
  If a Release Set is active, an omitted or invalid domain fails resolution instead of
  silently falling back to a different published revision. The existing no-release
  fixture/bootstrap path remains explicit for development compatibility.
- The authorization boundary consumes the resolver's published `access` record when an
  active Release Set provides one; without a Release Set it retains the existing
  published-policy restriction fallback and never grants scopes.
- The knowledge-grounded Agent resolves the exact product-scoped published knowledge version
  selected by the active Release Set; if that Release Set omits the product, retrieval reports
  bounded unavailable evidence instead of falling back to another published version.
- A published Agent-instruction component in the active Release Set can supply
  the system instruction without exposing configuration storage to the client.
- Claimant message turns consume Agent instruction, tool policy, controlled rules, and feature
  settings from the same Runtime Snapshot used by model and knowledge selection. Closed schemas
  reject unknown Registry grants, protect the mandatory safety/handoff baseline, and fail before
  Claim State mutation when a complete policy cannot be resolved.
- Controlled branch-rule overlays can disable or observe registered non-protected rules. Feature
  settings can select deterministic turn handling or disable knowledge retrieval. Every persisted
  Agent decision records the exact Release Set plus configuration and knowledge revisions used.
- Internal policy, history, knowledge, evidence-processing, claim-creation, and assessor calls
  enforce the selected Integration's enabled/source boundary before invoking an adapter. Handoff
  dispatch uses the same boundary while preserving the durable local queue fallback.
- Integration health checks use the timeout from the selected published record and expose
  unselected, disabled, source-mismatch, and timeout outcomes without invoking business actions.

## Remaining implementation gaps

- Authorization still uses the existing server-side identity/session scope
  boundary. Published access policies can only restrict those scopes; dynamic
  role assignment and policy-driven scope grants are not implemented.
- Runtime resolution is shared by model, claimant Agent policy, staff-model, knowledge, data
  profile, access-policy, and Integration paths. Complete target `TurnPlan`, `ExecutionPlan`, tool
  execution, usage, and trajectory persistence remain unfinished; the four Agent configuration
  domains do not claim those target records.
- Cloud data-profile adapters, production secret-manager integration, and
  provider connection verification remain deployment-specific.
- Cross-resource audit search is implemented against the existing audit
  repository but does not yet expose cursor-native storage queries for very
  large event volumes.

## Repeatable evidence

Latest full backend run on this worktree:

```text
1465 passed in 456.04s
coverage: 88.88% (fail_under=90.0; quality gate not yet satisfied)
```

The run has no failing behavioral tests. The remaining gate gap is coverage in
older adapter/repository and service branches; it must be closed with
meaningful contract tests before claiming the full backend quality gate.

Browser-level desktop/mobile evidence was not verified because the trusted
browser service was unavailable in this session.

The following checks passed on this worktree:

```text
py -3.12 -m ruff check backend
py -3.12 -m mypy backend
py -3.12 scripts/export_openapi.py --check
py -3.12 -m pytest -q tests/test_admin_accounts.py tests/test_identity_adapters.py tests/test_identity_api.py tests/test_identity_runtime.py tests/test_staff_identity.py
py -3.12 -m pytest -q tests/test_admin_operations.py tests/test_admin_integrations.py tests/test_staff_agent_gateway.py tests/test_model_gateway.py tests/test_control_plane_sqlite.py
npm run lint --prefix admin
npm test --prefix admin
npm run build --prefix admin
```

The focused account-administration, integration, and knowledge runs pass 27
tests; the Control Plane ledger and Release Set additions pass their focused
tests as part of the full 1,465-test run. Windows pytest temporary-directory
cleanup may emit a non-functional `WinError 5` after tests finish.

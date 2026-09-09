# Fixtures and Test Conventions

## Purpose

This document defines the boundary between synthetic test data, journey
specifications, executable assertions, runtime test doubles, and verification
evidence. It applies to backend tests, claimant and workbench tests, fixture
loaders, and presentation-related checks.

The word **fixture** must not be used as a synonym for a test, a mock adapter,
or a test report.

## Definitions

### Static fixture data

Static fixture data is deterministic, synthetic input or persisted state that a
test or script can load repeatedly. It contains no credentials, personal data,
provider secrets, or unconfirmed AWS details.

Examples in this repository include:

- `tests/fixtures/scenarios/`: complete claim, session, message, and evidence
  state snapshots for reusable scenario loading;
- `tests/fixtures/journeys/`: natural-language inputs and expected observable
  actions or state outcomes for a journey;
- `tests/fixtures/api/`: claimant-safe response examples derived from a
  canonical scenario; and
- `tests/fixtures/media/`: synthetic image or document bytes when a test needs
  to exercise the upload boundary. This directory is currently empty.

Fixture data may contain a current compatibility oracle such as `expected_action` or
`expected_status`. The oracle is data; it is not executable verification. The legacy
eight-action `expected_action` field must not be relabelled as proof of the target
multidimensional turn contract.

When the target turn contract is implemented, a journey oracle may instead identify
expected intents, conversation moves, content-branch candidates, form-patch proposals,
approved and rejected ActionEnvelopes, one Runtime control directive, tool outcomes,
WorkItem and lifecycle effects, and the final role projection. These expectations must
remain separate so a correct response sentence cannot hide an unauthorised or failed
side effect.

### Executable tests

Assertions and test orchestration belong in `tests/` test modules or the
frontend test modules. A test must assert observable behaviour such as an API
response, persisted state, claimant projection, staff projection, or rendered
interaction. Do not put durable `assert` logic in a JSON fixture.

The presentation journey under `tests/fixtures/presentation/` is a temporary
quarantine for presentation-specific checks. Product and contract assertions
that remain valuable after the demonstration belong in a normal journey or API
test module. Presentation-only assertions must be removed or archived when the
temporary demonstration work ends.

### Runtime test doubles

`FixtureRepository` is an in-memory implementation of the persistence protocol,
not static fixture data. Mock claims, evidence, policy, history, and assessor
adapters are also runtime test doubles. They must preserve the provider-neutral
domain and API boundaries so a future adapter can replace them without changing
claimant behaviour.

### Verification evidence

A test record is not a fixture. It records the run that consumed fixtures and
tests. Each Day 4 journey record should contain:

1. fixture or input identifier and exact claimant/staff input;
2. expected Agent action and observable next step;
3. actual response and state changes, including proposed, authorised, completed, failed,
   or unknown status where the target turn contract applies;
4. claimant and staff projections where applicable;
5. pass or fail result; and
6. a defect reference when the result is not accepted.

Failures belong to the responsible fix issue, such as #47 or #48. A test task
must not hide a failure by changing a fixture until the expected behaviour has
been agreed and the regression test has been updated deliberately.

## Current repository layout

| Path | May contain | Must not become |
|---|---|---|
| `tests/fixtures/scenarios/` | Reusable persisted-state snapshots | A place for assertions or one-off demo output |
| `tests/fixtures/journeys/` | Inputs and expected observable outcomes | A transcript archive or model-training corpus |
| `tests/fixtures/api/` | Public API response examples | A second private domain model |
| `tests/fixtures/media/` | Synthetic image/document bytes and metadata | Real claimant uploads or provider payloads |
| `tests/` | Backend loaders, API tests, domain tests, and journey assertions | Hidden manual repair scripts |
| `archive/customer/src/*.test.*` | Historical claimant/workbench component and client behaviour tests | Internal signal assertions in claimant projections |
| `scripts/run_scenarios.py` | Fixture loading and repeatability smoke checks | A substitute for multi-turn journey testing |

The four current reusable state scenarios are AT-01, AT-06, AT-08, and AT-12.
PRES-01 is a presentation journey specification and should not be treated as a
replacement for the official acceptance scenarios.

## Image-assisted journeys

An image-assisted test has three separate concerns:

1. synthetic image bytes or upload metadata exercise the media boundary;
2. a deterministic mock extraction result represents proposed facts; and
3. claimant confirmation or correction changes the structured form.

The extraction result must remain `proposed` until confirmation. A filename,
media type, checksum, or `extraction_state` field alone does not prove that an
image-derived fact was shown, confirmed, or corrected.

## Journey test rules

- Reuse one canonical fixture for a scenario; do not create a second JSON copy
  with a different claim model for an API example.
- Use stable scenario identifiers such as `AT-07-image-assist` and keep
  descriptions tied to an acceptance scenario.
- Assert reason codes, state transitions, visibility, and next-step ownership
  where they are part of the contract. Avoid asserting incidental wording or
  generated identifiers.
- For target Agent Runtime tests, assert the trajectory from `AgentProposal` through
  `ExecutionPlan` and `TurnResult`, including rejected overreach, tool authority, unknown
  external outcomes, and the final Claim revision. Do not infer execution from the model
  response text.
- Keep claimant-visible and staff-only assertions separate.
- Mark controlled prototype rules and mock results as synthetic; never present
  them as Northwind production policy or confirmed AWS behaviour.
- When a journey is not implemented, record the missing capability or defect;
  do not create a fixture that makes the path appear to pass.

## Required review for fixture and test-contract changes

Any pull request that changes `tests/fixtures/`, fixture loaders, shared
journey or API oracles, or the corresponding contract tests must request review
from all four named team members below when the author is `Ysoseri1224`:

- `liyang6620` - persistence, adapter, idempotency, and provider boundary;
- `jxu316-arch` - API routes, permissions, errors, and state transitions;
- `bdfa123` - fixture integrity, repeatability, and independent regression
  evidence; and
- `LLL263` - claimant and staff observable outcomes.

The author must not approve their own changes. If another named reviewer is the
author, the remaining named reviewers must still be requested and must review
the affected contract. Each review should check the relevant ownership area and
record either approval or a concrete change request. A review is not complete
merely because the reviewer was assigned or mentioned.

## What GitHub can enforce

GitHub cannot prove that a person read a document. It can enforce approvals or
an automated check that observes approvals.

The current repository protection requires one approval, dismisses stale
approvals after a new push, and requires approval after the last push. It does
not require four named reviewers and it does not require status checks.

The practical rollout is:

1. **Immediate, manual:** request the four reviewers on each affected PR and
   use the PR checklist to link the relevant fixture, test, and verification
   evidence.
2. **Optional routing:** add `CODEOWNERS` entries for the fixture and test
   paths. This can request the right owners automatically, but a CODEOWNERS
   rule alone does not require all four people to approve.
3. **Exact enforcement:** add a repository workflow that fails when the latest
   non-dismissed reviews do not include the required named accounts, then make
   that workflow a required branch-protection status check. This is the only
   reliable way to require these four specific reviews, and should be added
   only after the team agrees to the review latency and maintains the account
   list.

This document does not itself change branch protection or add the exact-review
workflow.

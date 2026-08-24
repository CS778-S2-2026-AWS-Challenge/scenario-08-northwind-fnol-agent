# Day 4 external-service validation

Issue: #272

## Scope

This record validates the claimant external-service UI and controlled assessor adapter on the
stacked #302 implementation. All claim data, provider responses, identifiers, and failure
outcomes are synthetic. The check covers clean success, a claimant choosing not to grant
consent, service unavailable, timeout, retry, and replay behaviour through the public claimant
API and visible claimant interface.

## Repeatable checks

Run these commands from the repository root with the documented Python and Node dependencies:

```powershell
python -m pytest tests/test_external_service_validation.py -vv
npm test --prefix customer -- src/App.test.jsx
```

The backend matrix starts from natural claimant input, confirms the structured report, creates
the controlled claim, and then exercises the public consent and assessor-routing mutations. The
frontend suite checks the same optional consent, progress, failure, and retry states rendered to
the claimant.

Owner verification on 25 August 2026 recorded `4 passed` for the focused backend matrix and
`19 passed` for the focused claimant component suite. The complete repository gate recorded
`393 passed`, `90.77%` backend coverage, `14 passed` repository-policy checks, and `27 passed`
frontend tests; formatting, lint, type checking, and the production build also passed.

## Result matrix

| Result | Expected observation | Executable evidence | Status |
| --- | --- | --- | --- |
| Success | One authorised request returns an honest assigned fixture result and an identical replay creates no second assignment. | `test_success_is_claimant_safe_and_replays_without_a_second_assignment` | Pass |
| Consent declined | No consent is stored, the adapter is never called, the request remains disabled in the UI, and the created claim and next step remain available. | `test_declined_consent_preserves_the_claim_and_never_calls_the_adapter`; claimant component test | Pass |
| Unavailable | The public route returns `503 DEPENDENCY_UNAVAILABLE`, identifies only the bounded `unavailable` reason, keeps the consented revision, and records no assignment. | `test_transient_failure_preserves_progress_then_retries_with_the_same_operation[unavailable]` | Pass |
| Timeout | The public route returns `503 DEPENDENCY_UNAVAILABLE`, identifies only the bounded `timeout` reason, keeps the consented revision, and records no assignment. | `test_transient_failure_preserves_progress_then_retries_with_the_same_operation[timeout]` | Pass |
| Retry and replay | The same operation identity and unchanged revision can be retried after either transient failure; the retry succeeds once and the post-success replay returns the accepted result. | Both transient-failure matrix cases and the claimant retry component test | Pass |

## State and visibility findings

- Declining the optional checkbox is a no-write path. A direct `consent: false` request is not
  interpreted as a grant, routing without consent is rejected, and the claim remains created.
- Consent is the only claim mutation before the provider call. Timeout and unavailable outcomes
  preserve that consented revision, external claim, confirmed facts, next step, and empty routing
  result.
- A retry uses the original public idempotency key and `If-Match` revision. A successful retry
  advances the claim once, stores one routing result, and retains one routing-authority decision.
- Claimant responses show the controlled fixture, bounded shared-data summary, safe error, and
  assignment result. They do not expose the raw consent reference or internal decision identity.

## Defect record

No blocking #272 defect was found on the validated stacked head. Therefore no separate defect
issue was created. If a later rebase or provider implementation fails this matrix, the defect
record must identify an owner and include the exact input, reproduction command, expected result,
actual claimant and persisted-state result, affected dependency, and retest condition before #272
can be closed.

## Boundaries and remaining limitations

- The validation proves the controlled fixture path only. It does not prove a production assessor
  provider, production identity or consent system, service-level timing, or configured AWS path.
- Choosing not to grant this optional consent is intentionally a no-write action; it is not a
  persisted consent withdrawal or provider cancellation workflow.
- Automatic retry counts remain unapproved. The claimant explicitly initiates the demonstrated
  retry.
- #302 remains stacked on #300 and #298. This validation must be rerun after the dependency chain
  is rebased or merged before it is treated as final independent acceptance evidence.

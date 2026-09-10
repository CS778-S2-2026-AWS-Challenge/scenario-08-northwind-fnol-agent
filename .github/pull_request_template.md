## Linked issue

<!-- Use Closes/Fixes/Resolves only for complete delivery. Use Refs for partial work. -->
<!-- Every PR must identify its primary repository issue. -->

## Summary

<!-- Describe the current head, the change classification, and the observable outcome. -->
<!-- State whether this is a feature, bug fix, regression validation, integration validation, or documentation/tooling change. -->
<!-- Draft PRs must still state what exists now and what remains incomplete. -->

- Primary owner:
- Owned behavior:
- Non-goals:
- Scope changed since issue: No

## Acceptance evidence

<!-- Map each relevant issue acceptance criterion to current evidence. Do not claim evidence from another commit or environment. -->

## Local validation

<!-- Keep the Command and Result fields in both Draft and Ready PRs. Drafts may use explicit
     placeholders such as `Not run - implementation in progress`; Ready PRs must record the
     actual command and result for the current exact head. -->
- Record focused commands that were actually run, or `Not run` with the reason. These results are
  development evidence only; CircleCI supplies the authoritative exact-head quality result.
- Command:
- Result:

## Contract and data impact

- API contract:
- Persistence schema:
- Fixtures and tests:
- Claimant and staff projections:

## Ownership and overlap

- Expected impact area:
- Cross-owner impact: None
- Overlapping issues or PRs: None
- Owner agreement: Not required

<!-- File overlap is advisory topology evidence, not proof of shared ownership. Stacked or stale
bases may contain inherited history. Declare only semantic overlap in owned behaviour. -->

## Base and delivery topology

- Base reviewed against:
- Stacked parent: None
- Intended merge order: Independent
- Main changes affecting this PR: None

## Failure-path analysis

- Risk class: Standard
- Ownership or stale authority:
- Retry, concurrency, or duplicate delivery:
- Partial side effect or unknown outcome:
- Recovery or reconciliation:
- Sensitive-data or model-output exposure:

<!-- Use None with a reason when a failure-path category cannot apply. High-risk PRs must describe
the relevant failure states and tests before requesting review. -->

## Dependencies and risks

- Dependencies:
- Remaining risks:

## Governance exception

- Protected actions: None
- Reason: Not required
- Operator: Not required
- Allowed PRs: None
- Window starts: Not required
- Window expires: Not required
- Restoration evidence: Not required

<!-- Complete this only when the PR requires a protected repository operation. Use an @operator,
exact #PR allowlist, ISO-8601 UTC timestamps, and the required ruleset or service restoration check. -->

## Governance confirmation

- [ ] I have read AGENT.md and the governance skill
      (docs/skills/repo-governance-for-novice/) in full. Version read: vX.Y

<!-- Replace vX.Y with the version line from SKILL.md. A checked box is a mandatory reminder,
not proof; independent review remains the last line of defense. -->

## Documentation sync check

- [ ] This PR contains no changes that require documentation updates
- [ ] Updated docs/api.md (API contract changes)
- [ ] Updated docs/persistence-schema.md (persistence changes)
- [ ] Updated docs/README.md (documents added, replaced, moved, or archived)
- [ ] Updated other affected current documentation

## Impact statement

- [ ] I confirmed the changes do not affect unrelated code; any impact is described in the
      Summary

<!-- If this PR follows a discovered regression or integration gap, explain the relationship here and state whether it changes the original issue's acceptance boundary. -->

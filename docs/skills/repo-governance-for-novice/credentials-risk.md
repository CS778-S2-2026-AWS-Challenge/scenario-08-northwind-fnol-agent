# §8 Credentials and high-risk operations

This file covers tokens, production deployment, force-push, ruleset changes,
and data visibility.

## 8.1 Credentials

Use only anonymized or synthetic fixtures in source control. Never commit
tokens, passwords, private keys, `.env` contents, policyholder data, complete
real incident records, or workshop credentials. Keep secrets and
environment-specific values out of source code.

The same discipline applies to **non-code locations**: do not paste terminal
output, error stack traces, or configuration dumps containing environment
values, tokens, keys, or policyholder data into PR bodies, issues, review
comments, Discussions, or CI logs (echo/print) — these locations are not
covered by push-side mechanical interception. **Expired credentials are
equally forbidden.** Inspect and mask sensitive segments before pasting any
command output.

## 8.2 High-risk operations

Force-push, branch deletion, shared-history rewrites, changes to rulesets /
branch protection / Actions permissions / secrets / environments, deployment,
release, credential rotation, and changes to external services or
production-like datasets — all belong to the §1.2 protected operations and
require the current user's explicit authorization for the specific operation.

CI/CD must not deploy automatically until deployment targets, credentials,
environments, rollback behavior, and authorization are explicitly defined and
approved.

## 8.3 Data and visibility

- Keep claimant-visible data separate from internal review signals, fraud
  indicators, staff-only notes, permission checks, and provider details.
- High-impact underwriting, fraud, claim approval, denial, and security
  decisions require the explicit determinism defined by the specifications and
  API contracts, or staff authority.
- AWS schemas, services, permissions, datasets, deployment targets, and
  Northwind business rules are unconfirmed until recorded by an authoritative
  project source. Do not fabricate provider facts.

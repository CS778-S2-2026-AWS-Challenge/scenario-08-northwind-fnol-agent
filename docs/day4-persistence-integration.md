# Day 4 persistence integration validation

Issue #135 connects claim, session, resume, and handoff persistence under one authoritative `WorkingClaim.revision`.

The executable validation is `tests/test_persistence_integration.py`.

It demonstrates one claim progressing through create, pause, resume, handoff request, staff acceptance, another pause/resume cycle, a rejected stale staff write, and a successful current-revision staff write. The same claim and handoff identities are retained throughout, exactly one claimant session remains active, and no private duplicate revision model is introduced.

This validation is intentionally integration-only. The underlying session/recovery and handoff persistence implementations are already on `main` through their owning issues and PRs.

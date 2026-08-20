# Day 5 fact source and confirmation state check

Issue: #141

This is the `bdfa123` half of Issue #141: an independent check of where each
fact came from and what confirmation state it is in. `Ysoseri1224` fixes and
demonstrates the claimant and Agent path itself.

## What this checks and why

The question worth checking on the clear-claim path is not whether a value
arrived. It is whether the claim can still say **who** said it, and whether a
person has agreed to it. A system that loses either can present an extracted
guess as a confirmed fact.

Run `tests/fixtures/presentation/test_fact_source_and_confirmation.py`.

1. **An extracted fact names its source and waits for a person.** A value read
   from an image carries `source: image`, `source_refs` pointing at the exact
   evidence item, its confidence, and status `proposed`. The claimant projection
   shows the same unconfirmed state rather than a settled fact.
2. **A decision changes confirmation state without losing the source.**
   Confirming moves the field to `confirmed`; rejecting moves it to `disputed`.
   In both cases the value, the source, and the source references are unchanged.
   A rejected value stays visible as disputed rather than disappearing, so the
   disagreement itself remains part of the record.
3. **A claimant-owned fact is not relabelled as machine-read.** The field is
   created through the claimant form, so it genuinely carries `source:
   claimant` and `status: confirmed` before any evidence exists. A later
   extraction targeting it is rejected with `409 INVALID_STATE_TRANSITION`, the
   field is byte-identical afterwards, and the evidence identifier never
   appears in its `source_refs`.
4. **The check is repeatable.** Two independent claims driven through the same
   path land in identical source and confirmation state, so the demonstration
   does not depend on residue from an earlier run.

## Acceptance

- **"The fixture completes repeatedly."** Demonstrated in 4.
- **"Fact source, confirmation state, and next step are correct."** Source and
  confirmation state are demonstrated in 1, 2, and 3. **Next step is
  `Ysoseri1224`'s half** — it belongs to the claimant and Agent path, and is not
  claimed here.

## Boundary

This covers source and confirmation state only. Issue #141 stays open until the
claimant and Agent path demonstration lands, which is why this is a `Refs` and
not a `Closes`.

The overwrite rejection in 3 is the boundary introduced by Issue #120 after
review: extraction may only fill a field the shared form does not hold yet.
Without it, a second reading would replace the first and the claim would lose
both the original value and its provenance.

An earlier version of check 3 built the field by running the upload-and-process
helper first, which made it image-derived. That only proved one extraction
cannot overwrite another — a weaker claim than the check's name. It now creates
the field through the claimant form, so the precondition the name depends on is
established rather than assumed.

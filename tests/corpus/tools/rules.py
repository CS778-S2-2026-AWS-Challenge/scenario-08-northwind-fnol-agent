"""Label vocabulary for triage and review indicators, and the derivation the checker enforces.

Source: design-ref/triage-fraud-mvp.md (Ysoseri, 2026-09-30, based on origin/main@1183e248). Every
code below maps to one bullet of that document, so a scorer can reconcile the system's reasons with
the oracle one by one. The backend has no triage or review-indicator codes yet; when
backend/domain/triage.py and backend/domain/review_indicators.py land, map their codes to these.
"""

from typing import Any

RULES_REF = {
    'file': 'design-ref/triage-fraud-mvp.md',
    'author': 'Ysoseri1224',
    'date': '2026-09-30',
    'sha256': '0eecd3ade0ee4f775e8b48d429799e8a1b8786b33335440d14b78c035269b670',
}

TRIAGE_CLASSES = ['fast_track', 'standard', 'complex']  # ordered from least to most human attention

# code: (class it forces, the bullet in section 2 of the design)
TRIAGE_REASONS = {
    'injury_or_danger': (
        'complex',
        'Someone is injured, the scene is dangerous, or an urgent handoff was made',
    ),
    'liability_unresolved': (
        'complex',
        'Another party is involved and liability is unconfirmed or disputed',
    ),
    # Maintainer, 2026-09-30: only a lookup uncertainty marker (for example
    # COVERAGE_SECTION_INCOMPLETE on synthetic-policy-ambiguous) or an Agent record that the loss
    # may not be covered counts;
    # claim_state.coverage = review_required on its own does not.
    'coverage_unclear': (
        'complex',
        'The policy lookup carries an uncertainty marker, or the Agent recorded that '
        'the loss may not be covered',
    ),
    'claimant_disputes_terms': (
        'complex',
        'The claimant disagrees with the excess or the scope of cover',
    ),
    'uninhabitable_or_ongoing_risk': (
        'complex',
        'The home cannot be lived in, or damage is still happening',
    ),
    'review_indicator_escalated': (
        'complex',
        "The review indicators reached 'review_required' (section 3)",
    ),
    'evidence_outstanding': (
        'standard',
        'Required material is missing, unreadable, incomplete, or not available yet',
    ),
    'question_unanswered': (
        'standard',
        "A required question is unanswered, or answered 'I don't know'",
    ),
    'inconsistency_unresolved': (
        'standard',
        'Statements disagree, or a material contradicts the statement, and it is not clarified',
    ),
    'policy_lookup_failed': (
        'standard',
        'The system could not find the policy (not found is not the same as fine)',
    ),
    'vehicle_undrivable_or_assessor': (
        'standard',
        'The vehicle cannot be driven, needs towing, or needs an assessor',
    ),
    'amount_over_threshold_or_unknown': (
        'standard',
        'The largest known amount is over NZD 5,000, or no amount is known at all',
    ),
    'review_hint': ('standard', 'Exactly one weak indicator (a hint, not a flag)'),
    'possible_duplicate': ('standard', 'Another submitted claim may be the same event'),
}

# exactly 5,000 is still fast_track; the brief gives no number, this is a project assumption
AMOUNT_THRESHOLD_NZD = 5000

# code: (strength, the rule in section 3 of the design)
CHECKS = {
    'ownership_doc_after_loss': (
        'strong',
        'A receipt, proof of purchase or proof of ownership is dated after the incident. '
        'Only the purchase date counts; a reprint date is ignored. A time range uses its last day.',
    ),
    'quote_before_loss': (
        'strong',
        'A repair quote or assessment report is dated before the incident. '
        'A time range uses its first day.',
    ),
    'prior_claims_12m': (
        'weak',
        'The same person has two or more other submitted claims in the past year. '
        'Drafts and this claim do not count.',
    ),
    'policy_inception_30d': (
        'weak',
        'The incident happened less than 30 days after the policy was first taken out. '
        'The lookup holds only the current period start, which changes at every renewal, '
        'so the system cannot run this check yet.',
    ),
    'possible_duplicate': (
        'separate',
        'Another submitted claim by the same person, same family, '
        'incident dates within 3 days. Not a fraud indicator.',
    ),
}

# hit: the rule fires. clear: checked and fine. not_checked: the data exists in principle but the
# system cannot check it here (date unknown or unreadable, page missing, lookup
# error). not_applicable: the pack has nothing this check looks at (for example no receipt at all).
CHECK_OUTCOMES = ['hit', 'clear', 'not_checked', 'not_applicable']

# Checks that need data the system does not hold yet. The oracle records the value the rule gives
# on the pack's facts; the scorer skips the check until the data exists.
DATA_DEPENDENCIES = {'policy_inception_30d': 'policy_inception_date'}


def derive(oracle: dict[str, Any]) -> list[str]:
    """Return a list of problems where the oracle's labels do not follow from its own \
reasons and checks."""
    problems: list[str] = []
    triage = oracle.get('triage', {})
    indicators = oracle.get('review_indicators', {})
    checks: dict[str, Any] = {
        code: item.get('expected') for code, item in indicators.get('checks', {}).items()
    }

    for code in CHECKS:
        if code not in checks:
            problems.append(f'review_indicators: check {code} has no expected outcome')
    for code, outcome in checks.items():
        if code not in CHECKS:
            problems.append(f'review_indicators: unknown check {code}')
        elif outcome not in CHECK_OUTCOMES:
            problems.append(
                f'review_indicators: {code} expected={outcome!r} is not one of {CHECK_OUTCOMES}'
            )

    strong = [c for c, o in checks.items() if o == 'hit' and CHECKS.get(c, ('',))[0] == 'strong']
    weak = [c for c, o in checks.items() if o == 'hit' and CHECKS.get(c, ('',))[0] == 'weak']
    flagged = bool(strong) or len(weak) >= 2
    want_signal = 'review_required' if flagged else 'none'
    if indicators.get('expected_fraud_signal') != want_signal:
        problems.append(
            f'review_indicators: expected_fraud_signal={indicators.get("expected_fraud_signal")!r} '
            f'but the checks give {want_signal!r} (strong hits {strong}, weak hits {weak})'
        )
    for code, dependency in DATA_DEPENDENCIES.items():
        item = indicators.get('checks', {}).get(code, {})
        if item.get('expected') != 'not_checked':
            problems.append(
                f'review_indicators: {code} needs {dependency}, which the system does not hold, '
                'so it is labelled not_checked; put the rule value in value_if_data'
            )
        if item.get('value_if_data') == 'hit':
            problems.append(
                f'review_indicators: {code} would be a hit once {dependency} exists; the fraud '
                'signal would then change, so pick another feature until the data exists'
            )

    if triage.get('applies') is False:
        # No Claim is formed (for example an urgent handoff before submission), so nothing is
        # triaged.
        if triage.get('expected_class') is not None:
            problems.append('triage: applies=false but expected_class is set')
        return problems
    required = triage.get('required_reasons', [])
    allowed = triage.get('allowed_reasons', [])
    for code in required + allowed:
        if code not in TRIAGE_REASONS:
            problems.append(f'triage: unknown reason {code}')
    overlap = set(required) & set(allowed)
    if overlap:
        problems.append(f'triage: reasons both required and allowed: {sorted(overlap)}')
    implied = {
        'review_indicator_escalated': flagged,
        'review_hint': len(weak) == 1 and not strong,
        'possible_duplicate': checks.get('possible_duplicate') == 'hit',
    }
    for code, should in implied.items():
        if should and code not in required:
            problems.append(f'triage: the checks imply reason {code}, but it is not required')
        if not should and code in required:
            problems.append(f'triage: reason {code} is required, but the checks do not imply it')

    levels = [TRIAGE_CLASSES.index(TRIAGE_REASONS[c][0]) for c in required if c in TRIAGE_REASONS]
    want_class = TRIAGE_CLASSES[max(levels)] if levels else 'fast_track'
    if triage.get('expected_class') != want_class:
        problems.append(
            f'triage: expected_class={triage.get("expected_class")!r} '
            f'but the required reasons give {want_class!r}'
        )
    optional_levels = [
        TRIAGE_CLASSES.index(TRIAGE_REASONS[c][0]) for c in allowed if c in TRIAGE_REASONS
    ]
    if optional_levels and max(optional_levels) > (max(levels) if levels else 0):
        problems.append(
            'triage: an allowed (optional) reason would raise the class; '
            'make it required or drop it'
        )
    return problems

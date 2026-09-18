"""Resolve one product family for all consumers of a claimant turn."""

import re

from backend.domain.agent_context_runtime import TurnFamilyResolution
from backend.domain.models import BranchEvaluationResult, FormStatus, WorkingClaim

_FAMILY_TERMS = {
    'motor': re.compile(
        r'\b(?:car|vehicle|motor|driv(?:e|ing|able)|road|traffic|collision|crash|'
        r'rear[- ]?end|windscreen)\b',
        re.IGNORECASE,
    ),
    'home': re.compile(
        r'\b(?:home|house|property|building|roof|wall|floor|room|pipe|plumb|flood)\b',
        re.IGNORECASE,
    ),
    'contents': re.compile(
        r'\b(?:contents?|belongings?|laptop|phone|jewellery|furniture|stolen item|theft)\b',
        re.IGNORECASE,
    ),
}
_FAMILIES = frozenset(_FAMILY_TERMS)


def _normalise(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalised = {'property': 'home'}.get(value.strip().lower(), value.strip().lower())
    return normalised if normalised in _FAMILIES else None


def _message_candidates(message_text: str | None) -> tuple[str, ...]:
    message = message_text or ''
    return tuple(family for family, pattern in _FAMILY_TERMS.items() if pattern.search(message))


def resolve_turn_family(
    claim: WorkingClaim,
    branch_evaluation: BranchEvaluationResult | None,
    message_text: str | None,
) -> TurnFamilyResolution:
    """Prefer persisted authority, otherwise accept one bounded current-turn candidate."""

    persisted: list[str] = []
    incident_type = _normalise(claim.incident_type)
    if incident_type is not None:
        persisted.append(incident_type)
    product_family = claim.form.get('claim.product_family')
    if product_family is not None and product_family.status is FormStatus.CONFIRMED:
        confirmed_family = _normalise(product_family.value)
        if confirmed_family is not None:
            persisted.append(confirmed_family)

    authoritative = tuple(dict.fromkeys(persisted))
    message_candidates = _message_candidates(message_text)
    if len(authoritative) > 1:
        return TurnFamilyResolution(
            status='conflicting',
            candidate_families=authoritative,
        )
    if authoritative:
        selected = authoritative[0]
        if message_candidates and selected not in message_candidates:
            return TurnFamilyResolution(
                status='conflicting',
                candidate_families=tuple(dict.fromkeys((*authoritative, *message_candidates))),
            )
        return TurnFamilyResolution(
            product_family=selected,
            status='authoritative',
            candidate_families=(selected,),
        )

    if len(message_candidates) > 1:
        return TurnFamilyResolution(
            status='ambiguous',
            candidate_families=message_candidates,
        )
    if len(message_candidates) == 1:
        return TurnFamilyResolution(
            product_family=message_candidates[0],
            status='inferred',
            candidate_families=message_candidates,
        )

    branch_family = _normalise(
        branch_evaluation.selected_family if branch_evaluation is not None else None
    )
    if branch_family is not None:
        return TurnFamilyResolution(
            product_family=branch_family,
            status='inferred',
            candidate_families=(branch_family,),
        )
    return TurnFamilyResolution(status='unresolved')

"""Resolve one product family for all consumers of a claimant turn."""

import re

from backend.domain.agent_context_runtime import TurnFamilyResolution
from backend.domain.models import (
    BranchEvaluationRecord,
    BranchEvaluationResult,
    FormStatus,
    WorkingClaim,
)

_FAMILY_TERMS = {
    'motor': re.compile(
        r'\b(?:car|vehicle|motor|driv(?:e|ing|able)|road|traffic|collision|crash|'
        r'rear[- ]?end(?:ed|ing|s)?|windscreen)\b',
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
    normalised = value.strip().lower()
    return normalised if normalised in _FAMILIES else None


def _message_candidates(message_text: str | None) -> tuple[str, ...]:
    message = message_text or ''
    return tuple(family for family, pattern in _FAMILY_TERMS.items() if pattern.search(message))


def resolve_turn_family(
    claim: WorkingClaim,
    branch_evaluation: BranchEvaluationResult | BranchEvaluationRecord | None,
    message_text: str | None,
    *,
    model_family_judgment: bool = False,
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
    stored_candidate = (
        _normalise(product_family.value)
        if product_family is not None
        and product_family.status in {FormStatus.PROPOSED, FormStatus.DISPUTED}
        else None
    )
    candidates = tuple(
        dict.fromkeys((*message_candidates, *((stored_candidate,) if stored_candidate else ())))
    )
    if len(authoritative) > 1:
        return TurnFamilyResolution(
            status='conflicting',
            candidate_families=authoritative,
        )
    if authoritative:
        selected = authoritative[0]
        return TurnFamilyResolution(
            product_family=selected,
            status='authoritative',
            candidate_families=tuple(dict.fromkeys((*authoritative, *candidates))),
        )

    if model_family_judgment:
        # Message keywords are ordering hints, never model field admission or
        # collection authority. Only a persisted model/claimant proposal selects
        # an inferred family; previous regex-derived evaluations cannot do so.
        if stored_candidate is not None:
            disputed = product_family is not None and product_family.status is FormStatus.DISPUTED
            return TurnFamilyResolution(
                product_family=None if disputed else stored_candidate,
                status='ambiguous' if disputed else 'inferred',
                candidate_families=candidates,
            )
        return TurnFamilyResolution(status='unresolved', candidate_families=message_candidates)

    if len(candidates) > 1 or (
        product_family is not None
        and product_family.status is FormStatus.DISPUTED
        and stored_candidate is not None
    ):
        return TurnFamilyResolution(
            status='ambiguous',
            candidate_families=candidates,
        )
    if len(candidates) == 1:
        return TurnFamilyResolution(
            product_family=candidates[0],
            status='inferred',
            candidate_families=candidates,
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

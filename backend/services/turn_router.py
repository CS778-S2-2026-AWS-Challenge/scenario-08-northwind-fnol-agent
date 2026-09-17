"""Deterministic claimant turn routing for Agent Context Runtime v7."""

import re

from backend.domain.agent_context_runtime import TurnRoute, TurnTask
from backend.services.agent import AgentTurnContext

_FAMILY_TERMS = {
    'motor': re.compile(
        r'\b(?:car|vehicle|driv(?:e|ing|able)|road|collision|crash|rear[- ]?end|windscreen)\b',
        re.IGNORECASE,
    ),
    'home': re.compile(
        r'\b(?:home|house|building|roof|wall|floor|room|pipe|plumb|flood)\b',
        re.IGNORECASE,
    ),
    'contents': re.compile(
        r'\b(?:contents?|belongings?|laptop|phone|jewellery|furniture|stolen item)\b',
        re.IGNORECASE,
    ),
}
_CORRECTION = re.compile(
    r'\b(?:correct|correction|actually|instead|not what|change that|update (?:this|that))\b',
    re.I,
)
_CONFIRMATION = re.compile(r'^\s*(?:yes|no|correct|confirmed|that is right|that is wrong)\b', re.I)
_STATUS = re.compile(
    r'\b(?:status|progress|what(?:\'s| is) happening|where is|when will|has .* '
    r'(?:arrived|finished))\b',
    re.I,
)
_EVIDENCE_HISTORY = re.compile(
    r'\b(?:previous|prior|earlier|history|already uploaded|old (?:photo|document|file))\b',
    re.I,
)
_EXTERNAL = re.compile(
    r'\b(?:assess(?:or|ment)?|damage assessment|repair(?:er| shop| booking)?|police|'
    r'tow(?:ing)?|emergency service)\b',
    re.I,
)


def _authoritative_family(context: AgentTurnContext) -> str | None:
    candidates = [
        context.claim.incident_type,
        context.branch_evaluation.selected_family if context.branch_evaluation else None,
        (
            str(context.claim.form['claim.product_family'].value)
            if 'claim.product_family' in context.claim.form
            else None
        ),
    ]
    for value in candidates:
        normalized = {'property': 'home'}.get(value or '', value)
        if normalized in {'motor', 'home', 'contents'}:
            return normalized
    return None


def _capabilities(message: str) -> list[str]:
    capabilities: list[str] = []
    for capability, pattern in (
        ('assessor', r'\b(?:assess(?:or|ment)?|damage assessment)\b'),
        ('repair', r'\b(?:repair(?:er| shop| booking)?|fix (?:my|the))\b'),
        ('emergency', r'\b(?:emergency|immediate danger|ambulance|fire service)\b'),
        ('police', r'\bpolice\b'),
        ('policy-search', r'\b(?:policy|cover(?:age|ed)?|excess)\b'),
        ('claim-history', r'\b(?:previous claims?|prior claims?|claim history)\b'),
    ):
        if re.search(pattern, message, re.IGNORECASE):
            capabilities.append(capability)
    return capabilities


def route_turn(context: AgentTurnContext) -> TurnRoute:
    message = (context.message_text or '').strip()
    authoritative_family = _authoritative_family(context)
    if authoritative_family is not None:
        family = authoritative_family
        family_resolution = 'authoritative'
    else:
        candidates = [
            family for family, pattern in _FAMILY_TERMS.items() if pattern.search(message)
        ]
        if len(candidates) != 1:
            configured_response = (
                context.runtime_policy.controlled_rules.deterministic_responses.get(
                    'unresolved_family'
                )
                if context.runtime_policy is not None
                else None
            )
            return TurnRoute(
                family_resolution='unresolved',
                task=TurnTask.INTAKE,
                deterministic_response=configured_response
                or (
                    'Please choose the single loss you want to report first: motor, home, or '
                    'contents.'
                ),
                model_required=False,
            )
        family = candidates[0]
        family_resolution = 'inferred'

    capabilities = _capabilities(message)
    if {'policy-search', 'claim-history'} & set(capabilities):
        task = TurnTask.STATUS_QUESTION
    elif _EVIDENCE_HISTORY.search(message):
        task = TurnTask.EVIDENCE_HISTORY
    elif context.evidence:
        task = TurnTask.EVIDENCE_CURRENT
    elif _EXTERNAL.search(message):
        task = TurnTask.EXTERNAL_SUPPORT
    elif _STATUS.search(message):
        task = TurnTask.STATUS_QUESTION
    elif _CORRECTION.search(message):
        task = TurnTask.CORRECTION
    elif _CONFIRMATION.search(message):
        task = TurnTask.CONFIRMATION
    elif context.branch_evaluation is not None and context.branch_evaluation.requirements.ready:
        task = TurnTask.CLAIM_CREATION
    else:
        task = TurnTask.INTAKE
    return TurnRoute(
        product_family=family,
        family_resolution=family_resolution,
        task=task,
        capability_ids=capabilities,
        model_required=True,
    )

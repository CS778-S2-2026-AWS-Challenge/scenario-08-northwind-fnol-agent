"""Deterministic claimant turn routing for Agent Context Runtime v7."""

import re

from backend.domain.agent_context_runtime import TurnRoute, TurnTask
from backend.services.agent import AgentTurnContext
from backend.services.turn_family_resolution import resolve_turn_family

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
    resolution = context.turn_family_resolution or resolve_turn_family(
        context.claim,
        context.branch_evaluation,
        message,
    )
    if resolution.product_family is None:
        capabilities = _capabilities(message)
        return TurnRoute(
            family_resolution=resolution.status,
            task=TurnTask.INTAKE,
            capability_ids=capabilities,
            intents=frozenset({'intake', *capabilities}),
            model_required=True,
        )
    family = resolution.product_family
    family_resolution = resolution.status

    capabilities = _capabilities(message)
    if {'policy-search', 'claim-history'} & set(capabilities):
        task = TurnTask.STATUS_QUESTION
    elif _EVIDENCE_HISTORY.search(message):
        task = TurnTask.EVIDENCE_HISTORY
    elif context.evidence:
        task = TurnTask.EVIDENCE_CURRENT
    elif _EXTERNAL.search(message):
        # External support is an optional intent on a claimant turn.  It must
        # not select the narrow external-offer schema and discard FNOL facts.
        task = TurnTask.INTAKE
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
    intents = {'intake'}
    intents.update(capabilities)
    if task is TurnTask.CORRECTION:
        intents.add('correction')
    elif task is TurnTask.CONFIRMATION:
        intents.add('confirmation')
    elif task is TurnTask.EVIDENCE_HISTORY:
        intents.add('evidence_history')
    elif task is TurnTask.EVIDENCE_CURRENT:
        intents.add('evidence_current')
    elif task is TurnTask.CLAIM_CREATION:
        intents.add('creation')
    elif task is TurnTask.STATUS_QUESTION:
        intents.add('status')
    return TurnRoute(
        product_family=family,
        family_resolution=family_resolution,
        task=task,
        capability_ids=capabilities,
        intents=frozenset(intents),
        model_required=True,
    )

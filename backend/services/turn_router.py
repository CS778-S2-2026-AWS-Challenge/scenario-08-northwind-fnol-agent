"""Deterministic claimant turn routing for Agent Context Runtime v7."""

import re

from backend.domain.agent_context_runtime import TurnIntent, TurnRoute, TurnTask
from backend.services.agent import AgentTurnContext
from backend.services.model_profiles import CONTROLLED_MODEL_PROFILE_ID
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
    r'\b(?:(?:previous|prior|earlier|old)\s+(?:uploaded\s+)?(?:photos?|images?|documents?|files?|uploads?|evidence)'
    r'|(?:upload|file|evidence|document|photo)\s+history|already uploaded)\b',
    re.I,
)


def _capabilities(message: str) -> list[str]:
    capabilities: list[str] = []
    for capability, pattern in (
        ('assessor', r'\b(?:assess(?:or|ment)?|damage assessment)\b'),
        ('repair', r'\b(?:repair(?:s|er| shop| booking)?|tow(?:ing)?|fix (?:my|the))\b'),
        ('emergency', r'\b(?:emergency|immediate danger|ambulance|fire service)\b'),
        ('police', r'\bpolice\b'),
        ('policy-search', r'\b(?:policy|cover(?:age|ed)?|excess)\b'),
    ):
        if re.search(pattern, message, re.IGNORECASE):
            capabilities.append(capability)
    return capabilities


def route_turn(context: AgentTurnContext) -> TurnRoute:
    message = (context.message_text or '').strip()
    snapshot = context.runtime_configuration_snapshot
    # Routing also serves deterministic deployments whose policy release has no
    # model binding. Only a v8 instruction can require model-owned family routing;
    # model execution still validates its selected binding in the request planner.
    # A keyword-agent session (``controlled``) calls no model, so there is no binding to read.
    inspect_model = context.model_profile_id not in {None, CONTROLLED_MODEL_PROFILE_ID} and (
        context.runtime_policy is None
        or context.runtime_policy.instruction.prompt_version == 'northwind-fnol-claimant-v8'
    )
    model = (
        snapshot.model(context.model_profile_id) if snapshot is not None and inspect_model else None
    )
    model_family_judgment = (
        model is not None and model.values.get('prompt_version') == 'northwind-fnol-claimant-v8'
    )
    resolution = (
        resolve_turn_family(
            context.claim, context.branch_evaluation, message, model_family_judgment=True
        )
        if model_family_judgment
        else context.turn_family_resolution
        or resolve_turn_family(context.claim, context.branch_evaluation, message)
    )
    family = resolution.product_family
    family_resolution = resolution.status

    capabilities = _capabilities(message)
    if 'policy-search' in capabilities:
        task = TurnTask.STATUS_QUESTION
    elif _EVIDENCE_HISTORY.search(message):
        task = TurnTask.EVIDENCE_HISTORY
    elif context.evidence:
        task = TurnTask.EVIDENCE_CURRENT
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
    intents: set[TurnIntent] = {'intake'}
    if set(capabilities) & {'assessor', 'repair', 'emergency', 'police'}:
        intents.add('external')
    if 'policy-search' in capabilities:
        intents.add('policy_lookup')
    if _CORRECTION.search(message):
        intents.add('correction')
    if _CONFIRMATION.search(message):
        intents.add('confirmation')
    if _EVIDENCE_HISTORY.search(message):
        intents.add('evidence_history')
    if context.evidence:
        intents.add('evidence_current')
    if context.branch_evaluation is not None and context.branch_evaluation.requirements.ready:
        intents.add('creation')
    if _STATUS.search(message):
        intents.add('status')
    # Availability is independent of the claimant's intent. Offering this read-only
    # reference must not turn an ordinary intake or correction into a status question.
    if (
        context.claim_history_context_loader is not None
        and context.claim.customer_id
        and not context.claim.customer_id.startswith('anonymous:')
    ):
        capabilities.append('claim-history')
    return TurnRoute(
        product_family=family,
        family_resolution=family_resolution,
        task=task,
        capability_ids=capabilities,
        intents=frozenset(intents),
        model_required=True,
    )

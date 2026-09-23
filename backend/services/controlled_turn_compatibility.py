"""Compatibility projection for controlled fixtures and an explicit v7 rollback.

The v8 reducer does not consume these proposal-era next-step overrides.
"""

from backend.domain.models import (
    AgentAction,
    AuthorityOutcome,
    CustomerNextStep,
    FormStatus,
    ResponsibleParty,
    StructuredFormField,
)
from backend.services.agent import AgentProposal


def _effective_next_step(
    proposed: CustomerNextStep,
    outcome: AuthorityOutcome,
) -> CustomerNextStep:
    if outcome is AuthorityOutcome.AUTHORISED:
        return proposed
    if outcome is AuthorityOutcome.REVIEW_REQUIRED:
        return CustomerNextStep(
            status='professional_review_required',
            summary='The proposed action requires professional review before it can continue.',
            responsible_party=ResponsibleParty.CLAIMS_PROFESSIONAL,
        )
    return CustomerNextStep(
        status='action_not_applied',
        summary='The proposed action was not applied. Your current report remains available.',
        responsible_party=ResponsibleParty.SYSTEM,
    )


_MODEL_FIELD_QUESTIONS: dict[str, tuple[str, str, str]] = {
    'incident.injury_or_danger': (
        'provide_safety_status',
        'Is anyone injured or in immediate danger?',
        'Tell us whether anyone is injured or in immediate danger.',
    ),
    'vehicle.drivable': (
        'provide_vehicle_status',
        'Is the vehicle safe to drive?',
        'Tell us whether the vehicle is safe to drive.',
    ),
    'incident.occurred_at': (
        'provide_incident_time',
        'About when did this happen?',
        'Tell us approximately when the incident happened.',
    ),
    'incident.location': (
        'provide_incident_location',
        'Where did the incident happen?',
        'Tell us where the incident happened.',
    ),
    'loss.description': (
        'describe_loss',
        'What was damaged or lost?',
        'Describe what was damaged or lost.',
    ),
}


def _validated_model_question(
    proposal: AgentProposal,
    current_form: dict[str, StructuredFormField],
) -> tuple[str, CustomerNextStep] | None:
    available_fields = {
        field_code
        for field_code, field in current_form.items()
        if field.status is not FormStatus.MISSING
    }
    available_fields.update(change.field_code for change in proposal.form_changes)
    if 'vehicle.damage_description' in available_fields:
        available_fields.add('loss.description')
    for field_code in proposal.customer_next_step.required_items:
        if field_code in available_fields:
            continue
        question = _MODEL_FIELD_QUESTIONS.get(field_code)
        if question is None:
            continue
        status, response_text, summary = question
        return (
            response_text,
            CustomerNextStep(
                status=status,
                summary=summary,
                responsible_party=ResponsibleParty.CLAIMANT,
                required_items=[field_code],
            ),
        )
    return None


def _safe_model_customer_content(
    proposal: AgentProposal,
    outcome: AuthorityOutcome,
    current_next_step: CustomerNextStep,
    current_form: dict[str, StructuredFormField],
) -> tuple[str, str, CustomerNextStep]:
    if outcome is AuthorityOutcome.REVIEW_REQUIRED:
        return (
            'The proposed action requires professional review.',
            'I have recorded what you shared. A Northwind claims professional must review the '
            'proposed next step before it can continue.',
            _effective_next_step(proposal.customer_next_step, outcome),
        )
    if outcome is AuthorityOutcome.BLOCKED:
        return (
            'The proposed action was not applied.',
            'I have recorded what you shared, but I could not safely apply the proposed next '
            'step. Your current report remains available.',
            _effective_next_step(proposal.customer_next_step, outcome),
        )

    validated_question = _validated_model_question(proposal, current_form)
    if proposal.action is AgentAction.ASK and validated_question is not None:
        question, next_step = validated_question
        return (
            'More incident information is needed.',
            f'Thanks. {question}',
            next_step,
        )
    if proposal.action is AgentAction.ASK:
        return (
            'More incident information is needed.',
            'Thanks. Please share the next incident detail you want Northwind to record.',
            CustomerNextStep(
                status='more_information_needed',
                summary='Provide the next incident detail.',
                responsible_party=ResponsibleParty.CLAIMANT,
            ),
        )
    if proposal.action is AgentAction.CLARIFY:
        return (
            'A material incident detail needs clarification.',
            'Thanks. Please clarify or correct the incident detail before the report continues.',
            CustomerNextStep(
                status='clarification_needed',
                summary='Clarify or correct the incident detail.',
                responsible_party=ResponsibleParty.CLAIMANT,
            ),
        )
    if proposal.action is AgentAction.CONFIRM and validated_question is not None:
        question, next_step = validated_question
        return (
            'Proposed incident details need claimant confirmation.',
            f'Thanks. Please review the proposed information. {question}',
            next_step,
        )
    if proposal.action is AgentAction.CONFIRM:
        return (
            'A proposed incident detail needs claimant confirmation.',
            'Thanks. Please review the proposed information and confirm or correct it.',
            CustomerNextStep(
                status='confirmation_needed',
                summary='Confirm or correct the proposed information.',
                responsible_party=ResponsibleParty.CLAIMANT,
            ),
        )
    return (
        'The claimant update was recorded without a high-impact decision.',
        'Thanks. I have recorded your update. You can continue when you are ready.',
        current_next_step,
    )

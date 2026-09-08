"""Claimant-facing wording for deterministic Dynamic Form requirements."""

import re
from dataclasses import dataclass

from backend.domain.models import (
    BranchEvaluationResult,
    CustomerNextStep,
    RequirementResolution,
    ResponsibleParty,
)


@dataclass(frozen=True, slots=True)
class ControlledIntakeField:
    field_code: str
    prompt: str
    confirmation_prompt: str


INTAKE_REQUIREMENTS = {
    item.field_code: item
    for item in (
        ControlledIntakeField(
            'claim.product_family',
            'Is this a motor, home, or contents claim?',
            'Please check the claim type before I continue.',
        ),
        ControlledIntakeField(
            'incident.description',
            'Tell me what happened in your own words.',
            'Please check the incident description before I continue.',
        ),
        ControlledIntakeField(
            'incident.injury_or_danger',
            'Is anyone injured, or is there any immediate danger?',
            'Please check the safety information before I continue.',
        ),
        ControlledIntakeField(
            'incident.occurred_at',
            'When did the incident happen?',
            'Please check the incident time before I continue.',
        ),
        ControlledIntakeField(
            'incident.location',
            'Where did the incident happen?',
            'Please check the incident location before I continue.',
        ),
        ControlledIntakeField(
            'loss.description',
            'What was damaged, lost, or stolen?',
            'Please check the damage or loss description before I continue.',
        ),
        ControlledIntakeField(
            'parties.other_parties',
            'Was another person or vehicle involved?',
            'Please check whether another party was involved.',
        ),
        ControlledIntakeField(
            'vehicle.damage_description',
            'What damage can you see on the vehicle?',
            'Please check the vehicle damage description.',
        ),
        ControlledIntakeField(
            'vehicle.drivable',
            'Can the vehicle be driven safely?',
            'Please check whether the vehicle is drivable.',
        ),
        ControlledIntakeField(
            'property.address',
            'What is the address of the affected property?',
            'Please check the affected property address.',
        ),
        ControlledIntakeField(
            'property.affected_areas',
            'Which areas of the property are affected?',
            'Please check the affected property areas.',
        ),
        ControlledIntakeField(
            'property.ongoing_risk',
            'Is there an ongoing risk such as an active leak, fire, or exposed area?',
            'Please check the ongoing property risk.',
        ),
        ControlledIntakeField(
            'property.habitable',
            'Can the property still be lived in safely?',
            'Please check whether the property is habitable.',
        ),
        ControlledIntakeField(
            'contents.items',
            'Tell me about one damaged, lost, or stolen item.',
            'Please check the item details before I continue.',
        ),
    )
}

_FAMILY_PATTERNS = {
    'motor': re.compile(r'\b(car|vehicle|motor|collision|crash|road|traffic)\b', re.I),
    'home': re.compile(r'\b(home|house|property|roof|room|building|pipe|flood)\b', re.I),
    'contents': re.compile(r'\b(contents|belongings|laptop|phone|stolen|theft|lost)\b', re.I),
}


def infer_controlled_product_family(message_text: str) -> str | None:
    """Return one unambiguous supported family from explicit claimant vocabulary."""

    matches = [
        family for family, pattern in _FAMILY_PATTERNS.items() if pattern.search(message_text)
    ]
    return matches[0] if len(matches) == 1 else None


def intake_field_for_requirement(requirement: str | None) -> ControlledIntakeField | None:
    """Return claimant wording for one registered current-action requirement."""

    return INTAKE_REQUIREMENTS.get(requirement or '')


def next_requirement_field(
    evaluation: BranchEvaluationResult | None,
) -> ControlledIntakeField | None:
    """Return wording for the evaluator-selected next requirement."""

    if evaluation is None:
        return INTAKE_REQUIREMENTS['incident.description']
    return intake_field_for_requirement(evaluation.requirements.next_required_item)


def next_requirement_step(requirements: RequirementResolution) -> CustomerNextStep:
    """Project deterministic requirements into the existing claimant next-step contract."""

    intake_field = intake_field_for_requirement(requirements.next_required_item)
    if intake_field is not None:
        return CustomerNextStep(
            status='more_information_needed',
            summary=intake_field.prompt,
            responsible_party=ResponsibleParty.CLAIMANT,
            required_items=[intake_field.field_code],
        )
    if requirements.ready:
        return CustomerNextStep(
            status='ready_to_create',
            summary='Your confirmed report is ready for claim creation.',
            responsible_party=ResponsibleParty.CLAIMANT,
        )
    return CustomerNextStep(
        status='clarification_needed',
        summary='Please clarify the claim type before the report continues.',
        responsible_party=ResponsibleParty.CLAIMANT,
        required_items=['claim.product_family'],
    )

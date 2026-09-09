"""Versioned staff-facing classification tags for Workbench projections."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

TAG_REGISTRY_ID: Final = 'northwind-fnol-staff-tags'
TAG_REGISTRY_VERSION: Final = '0.3'

CLAIM_FAMILIES: Final = ('motor', 'home', 'contents')


class TagCategory(StrEnum):
    CLAIM_TYPE = 'claim_type'
    INCIDENT = 'incident'
    PEOPLE_SAFETY = 'people_safety'
    STAKEHOLDER = 'stakeholder'
    IMPACT = 'impact'
    EVIDENCE = 'evidence'
    PROGRESS = 'progress'
    ATTENTION = 'attention'


class TagVisibility(StrEnum):
    STAFF_ONLY = 'staff_only'


class TagBasis(StrEnum):
    REPORTED = 'reported'
    DERIVED = 'derived'
    VERIFIED = 'verified'
    STAFF_ASSESSED = 'staff_assessed'


class TagSourceActor(StrEnum):
    CLAIMANT = 'claimant'
    STAFF = 'staff'
    SYSTEM = 'system'
    EXTERNAL_SERVICE = 'external_service'


class TagFreshness(StrEnum):
    CURRENT = 'current'
    STALE = 'stale'


class TagAttentionLevel(StrEnum):
    NOTICE = 'notice'
    ELEVATED = 'elevated'
    HIGH = 'high'


class TagProjectionMode(StrEnum):
    DETERMINISTIC = 'deterministic'
    STAFF_ASSESSED = 'staff_assessed'
    EXTERNAL_RESULT = 'external_result'
    UNAVAILABLE = 'unavailable'


class TagInstanceStatus(StrEnum):
    ACTIVE = 'active'
    DISPUTED = 'disputed'


class TagDefinitionStatus(StrEnum):
    DRAFT = 'draft'
    PUBLISHED = 'published'
    DEPRECATED = 'deprecated'
    RETIRED = 'retired'


class TagScope(StrEnum):
    VP = 'vp'
    VP_PLUS = 'vp_plus'
    LATER = 'later'


class StaffTag(BaseModel):
    """Typed Workbench projection of one active staff-facing tag."""

    model_config = ConfigDict(extra='forbid')

    tag_instance_id: str = Field(min_length=1, max_length=240)
    code: str = Field(min_length=1, max_length=100)
    registry_version: str = Field(min_length=1, max_length=20)
    label: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=300)
    category: TagCategory
    status: TagInstanceStatus
    visibility: TagVisibility
    basis: TagBasis
    source_actor: TagSourceActor
    freshness: TagFreshness
    projection_mode: TagProjectionMode
    attention_level: TagAttentionLevel | None = None
    source_refs: list[str] = Field(min_length=1, max_length=100)
    activated_at: datetime
    display_weight: int = Field(ge=1, le=100)


@dataclass(frozen=True, slots=True)
class StaffTagDefinition:
    code: str
    version: str
    status: TagDefinitionStatus
    category: TagCategory
    staff_label: str
    staff_description: str
    scope: TagScope
    visibility: TagVisibility
    applicable_claim_families: tuple[str, ...]
    source_types: tuple[str, ...]
    activation_rule_ref: str
    exit_rule_ref: str
    queue_display_weight: int
    requires_professional_authority: bool
    projection_mode: TagProjectionMode
    attention_level: TagAttentionLevel | None
    filterable: bool


_CATEGORY_DEFAULTS: dict[TagCategory, tuple[int, bool, str]] = {
    TagCategory.CLAIM_TYPE: (
        50,
        False,
        'Classifies the policy or loss scope',
    ),
    TagCategory.INCIDENT: (
        60,
        False,
        'Describes the reported incident',
    ),
    TagCategory.PEOPLE_SAFETY: (
        10,
        True,
        'Summarises reported people and safety context',
    ),
    TagCategory.STAKEHOLDER: (
        70,
        False,
        'Identifies a participant or service party',
    ),
    TagCategory.IMPACT: (
        30,
        False,
        'Summarises the reported practical impact',
    ),
    TagCategory.EVIDENCE: (
        80,
        False,
        'Summarises available or pending evidence',
    ),
    TagCategory.PROGRESS: (
        40,
        False,
        'Summarises current claim progress',
    ),
    TagCategory.ATTENTION: (
        20,
        True,
        'Flags a source-linked matter for staff attention',
    ),
}


def _rows(
    category: TagCategory,
    values: tuple[tuple[str, str, TagScope], ...],
) -> list[StaffTagDefinition]:
    weight, authority, description = _CATEGORY_DEFAULTS[category]
    definitions: list[StaffTagDefinition] = []
    for code, label, scope in values:
        status = (
            TagDefinitionStatus.DRAFT if scope is TagScope.LATER else TagDefinitionStatus.PUBLISHED
        )
        definitions.append(
            StaffTagDefinition(
                code=code,
                version=TAG_REGISTRY_VERSION,
                status=status,
                category=category,
                staff_label=label,
                staff_description=f'{description}: {label}.',
                scope=scope,
                visibility=TagVisibility.STAFF_ONLY,
                applicable_claim_families=(),
                source_types=(),
                activation_rule_ref='unavailable',
                exit_rule_ref='unavailable',
                queue_display_weight=weight,
                requires_professional_authority=authority,
                projection_mode=TagProjectionMode.UNAVAILABLE,
                attention_level=None,
                filterable=False,
            )
        )
    return definitions


_DEFINITIONS = [
    *_rows(
        TagCategory.CLAIM_TYPE,
        (
            ('claim_type.motor', 'Motor claim', TagScope.VP),
            ('claim_type.home', 'Home claim', TagScope.VP),
            ('claim_type.contents', 'Contents claim', TagScope.VP),
            ('claim_type.unconfirmed', 'Claim type not confirmed', TagScope.VP),
            ('claim_type.cross_product', 'Cross-product claim', TagScope.VP_PLUS),
        ),
    ),
    *_rows(
        TagCategory.INCIDENT,
        (
            ('incident.collision', 'Vehicle collision', TagScope.VP),
            ('incident.rear_end_collision', 'Rear-end collision', TagScope.VP),
            ('incident.single_vehicle', 'Single-vehicle incident', TagScope.VP_PLUS),
            ('incident.multi_vehicle', 'Multiple vehicles involved', TagScope.VP_PLUS),
            ('incident.vehicle_theft', 'Vehicle theft', TagScope.VP_PLUS),
            ('incident.burglary', 'Burglary', TagScope.VP),
            ('incident.contents_theft', 'Contents theft', TagScope.VP),
            ('incident.vandalism', 'Intentional damage reported', TagScope.VP_PLUS),
            ('incident.fire_smoke', 'Fire or smoke damage', TagScope.VP),
            ('incident.water_escape', 'Escape of water', TagScope.VP),
            ('incident.flood', 'Flood damage', TagScope.VP),
            ('incident.storm', 'Storm or wind damage', TagScope.VP),
            ('incident.earthquake', 'Earthquake damage', TagScope.VP_PLUS),
            ('incident.accidental_damage', 'Accidental damage', TagScope.VP),
            ('incident.impact_damage', 'Impact damage', TagScope.VP_PLUS),
            ('incident.glass_damage', 'Glass damage', TagScope.VP_PLUS),
            ('incident.damage_over_time', 'Damage developed over time', TagScope.VP_PLUS),
            ('incident.cause_unconfirmed', 'Cause not confirmed', TagScope.VP),
        ),
    ),
    *_rows(
        TagCategory.PEOPLE_SAFETY,
        (
            ('injury.none_reported', 'No injuries reported', TagScope.VP),
            ('injury.status_unknown', 'Injury status not confirmed', TagScope.VP),
            (
                'injury.reported_unassessed',
                'Injury reported · severity unconfirmed',
                TagScope.VP,
            ),
            ('injury.minor_reported', 'Minor injury reported', TagScope.VP),
            ('injury.moderate_reported', 'Moderate injury reported', TagScope.VP_PLUS),
            ('injury.serious_reported', 'Serious injury reported', TagScope.VP),
            ('safety.scene_safe_reported', 'Scene reported safe', TagScope.VP),
            ('safety.scene_uncertain', 'Scene safety not confirmed', TagScope.VP),
            ('safety.scene_unsafe', 'Unsafe scene reported', TagScope.VP),
            ('safety.immediate_help_needed', 'Immediate help may be needed', TagScope.VP),
            ('safety.distress_support', 'Claimant needs additional support', TagScope.VP_PLUS),
            ('safety.accessibility_support', 'Accessibility support needed', TagScope.VP),
        ),
    ),
    *_rows(
        TagCategory.STAKEHOLDER,
        (
            ('stakeholder.other_driver', 'Other driver involved', TagScope.VP),
            ('stakeholder.passenger', 'Passenger involved', TagScope.VP_PLUS),
            (
                'stakeholder.pedestrian_cyclist',
                'Pedestrian or cyclist involved',
                TagScope.VP_PLUS,
            ),
            ('stakeholder.third_party_property', 'Third-party property involved', TagScope.VP),
            ('stakeholder.witness', 'Witness available', TagScope.VP_PLUS),
            ('stakeholder.police', 'Police involved', TagScope.VP),
            ('stakeholder.emergency_services', 'Emergency services involved', TagScope.VP),
            ('stakeholder.other_insurer', 'Other insurer involved', TagScope.VP_PLUS),
            ('stakeholder.repairer', 'Repairer involved', TagScope.VP_PLUS),
            ('stakeholder.assessor', 'Assessor involved', TagScope.VP),
            (
                'stakeholder.builder_tradesperson',
                'Builder or tradesperson involved',
                TagScope.VP_PLUS,
            ),
            (
                'stakeholder.engineer_specialist',
                'Engineer or specialist involved',
                TagScope.LATER,
            ),
            (
                'stakeholder.landlord_manager',
                'Landlord or property manager involved',
                TagScope.VP_PLUS,
            ),
            ('stakeholder.body_corporate', 'Body corporate involved', TagScope.LATER),
            (
                'stakeholder.broker_representative',
                'Broker or representative involved',
                TagScope.VP_PLUS,
            ),
            (
                'stakeholder.legal_representative',
                'Legal representative involved',
                TagScope.LATER,
            ),
        ),
    ),
    *_rows(
        TagCategory.IMPACT,
        (
            ('impact.vehicle_drivable', 'Vehicle drivable', TagScope.VP),
            ('impact.vehicle_not_drivable', 'Vehicle not drivable', TagScope.VP),
            ('impact.vehicle_safety_unknown', 'Vehicle safety not confirmed', TagScope.VP),
            ('impact.towing_needed', 'Towing needed', TagScope.VP_PLUS),
            ('impact.towing_completed', 'Vehicle towed', TagScope.VP_PLUS),
            ('impact.home_habitable', 'Home remains habitable', TagScope.VP),
            ('impact.home_uninhabitable', 'Home not habitable', TagScope.VP),
            ('impact.habitability_unknown', 'Habitability not confirmed', TagScope.VP),
            (
                'impact.temporary_accommodation',
                'Temporary accommodation needed',
                TagScope.VP_PLUS,
            ),
            ('impact.emergency_repairs', 'Emergency repairs needed', TagScope.VP),
            ('impact.essential_services', 'Essential services affected', TagScope.VP_PLUS),
            ('impact.property_unsecured', 'Property not secure', TagScope.VP),
            ('impact.essential_contents', 'Essential items affected', TagScope.VP_PLUS),
            ('impact.high_value_items', 'High-value items reported', TagScope.VP_PLUS),
            ('impact.multiple_areas_items', 'Multiple areas or items affected', TagScope.VP),
            ('impact.further_loss_ongoing', 'Further damage may be continuing', TagScope.VP),
        ),
    ),
    *_rows(
        TagCategory.EVIDENCE,
        (
            ('evidence.photos_supplied', 'Photos supplied', TagScope.VP),
            ('evidence.video_supplied', 'Video supplied', TagScope.VP_PLUS),
            ('evidence.dashcam_available', 'Dashcam footage available', TagScope.VP_PLUS),
            ('evidence.proof_of_ownership', 'Proof of ownership supplied', TagScope.VP),
            ('evidence.police_reference', 'Police reference available', TagScope.VP),
            ('evidence.police_report_pending', 'Police report pending', TagScope.VP),
            ('evidence.repair_quote', 'Repair quote supplied', TagScope.VP_PLUS),
            ('evidence.assessment_report', 'Assessment report supplied', TagScope.VP_PLUS),
            ('evidence.partial', 'Evidence partly supplied', TagScope.VP),
            ('evidence.ready_for_review', 'Evidence ready for review', TagScope.VP),
            ('evidence.unavailable', 'Key evidence unavailable', TagScope.VP),
            ('evidence.source_conflict', 'Evidence conflict', TagScope.VP),
        ),
    ),
    *_rows(
        TagCategory.PROGRESS,
        (
            ('progress.new_report', 'New report', TagScope.VP),
            ('progress.details_incomplete', 'Claim details incomplete', TagScope.VP),
            ('progress.awaiting_claimant', 'Awaiting claimant', TagScope.VP),
            ('progress.awaiting_external', 'Awaiting external party', TagScope.VP),
            (
                'progress.staff_assistance_requested',
                'Staff assistance requested',
                TagScope.VP,
            ),
            ('progress.staff_assisting', 'Staff assisting', TagScope.VP),
            ('progress.follow_up_due', 'Follow-up due', TagScope.VP),
            ('progress.follow_up_overdue', 'Follow-up overdue', TagScope.VP),
            ('progress.ready_to_lodge', 'Ready to lodge', TagScope.VP),
            ('progress.claim_lodged', 'Claim lodged', TagScope.VP),
            ('progress.assessor_requested', 'Assessor requested', TagScope.VP),
            ('progress.assessor_assigned', 'Assessor assigned', TagScope.VP),
            ('progress.repair_contact_pending', 'Repairer contact pending', TagScope.VP_PLUS),
            (
                'progress.external_request_in_progress',
                'External request in progress',
                TagScope.VP,
            ),
            ('progress.customer_update_due', 'Customer update due', TagScope.VP_PLUS),
        ),
    ),
    *_rows(
        TagCategory.ATTENTION,
        (
            ('attention.fraud_l1', 'Fraud concern · Level 1', TagScope.VP_PLUS),
            ('attention.fraud_l2', 'Fraud concern · Level 2', TagScope.VP_PLUS),
            ('attention.fraud_l3', 'Fraud concern · Level 3', TagScope.VP_PLUS),
            ('attention.coverage_review', 'Coverage review needed', TagScope.VP),
            ('attention.liability_review', 'Liability review needed', TagScope.VP_PLUS),
            ('attention.liability_disputed', 'Liability disputed', TagScope.VP_PLUS),
            ('attention.customer_dispute', 'Customer dispute or complaint', TagScope.VP_PLUS),
            (
                'attention.identity_verification',
                'Identity verification needed',
                TagScope.VP_PLUS,
            ),
            ('attention.duplicate_claim', 'Possible duplicate claim', TagScope.VP_PLUS),
            ('attention.material_conflict', 'Material information conflict', TagScope.VP),
            ('attention.complex_loss', 'Complex loss', TagScope.VP_PLUS),
            ('attention.privacy_sensitive', 'Sensitive information present', TagScope.VP_PLUS),
        ),
    ),
]


def _code_set(value: str) -> frozenset[str]:
    return frozenset(value.split())


_MOTOR_ONLY_CODES = _code_set(
    """
    claim_type.motor
    incident.collision
    incident.rear_end_collision
    incident.single_vehicle
    incident.multi_vehicle
    incident.vehicle_theft
    stakeholder.other_driver
    stakeholder.passenger
    stakeholder.pedestrian_cyclist
    stakeholder.other_insurer
    impact.vehicle_drivable
    impact.vehicle_not_drivable
    impact.vehicle_safety_unknown
    impact.towing_needed
    impact.towing_completed
    evidence.dashcam_available
    """
)
_HOME_ONLY_CODES = _code_set(
    """
    claim_type.home
    stakeholder.landlord_manager
    stakeholder.body_corporate
    impact.home_habitable
    impact.home_uninhabitable
    impact.habitability_unknown
    impact.temporary_accommodation
    impact.emergency_repairs
    impact.essential_services
    impact.property_unsecured
    """
)
_CONTENTS_ONLY_CODES = _code_set(
    """
    claim_type.contents
    incident.contents_theft
    impact.essential_contents
    impact.high_value_items
    """
)
_HOME_CONTENTS_CODES = _code_set(
    """
    incident.burglary
    incident.water_escape
    incident.earthquake
    incident.damage_over_time
    stakeholder.builder_tradesperson
    impact.multiple_areas_items
    """
)
_ALL_FAMILY_CODES = _code_set(
    """
    claim_type.cross_product
    claim_type.unconfirmed
    incident.vandalism
    incident.fire_smoke
    incident.flood
    incident.storm
    incident.accidental_damage
    incident.impact_damage
    incident.glass_damage
    incident.cause_unconfirmed
    injury.none_reported
    injury.status_unknown
    injury.reported_unassessed
    injury.minor_reported
    injury.moderate_reported
    injury.serious_reported
    safety.scene_safe_reported
    safety.scene_uncertain
    safety.scene_unsafe
    safety.immediate_help_needed
    safety.distress_support
    safety.accessibility_support
    stakeholder.third_party_property
    stakeholder.witness
    stakeholder.police
    stakeholder.emergency_services
    stakeholder.repairer
    stakeholder.assessor
    stakeholder.engineer_specialist
    stakeholder.broker_representative
    stakeholder.legal_representative
    impact.further_loss_ongoing
    evidence.photos_supplied
    evidence.video_supplied
    evidence.proof_of_ownership
    evidence.police_reference
    evidence.police_report_pending
    evidence.repair_quote
    evidence.assessment_report
    evidence.partial
    evidence.ready_for_review
    evidence.unavailable
    evidence.source_conflict
    progress.new_report
    progress.details_incomplete
    progress.awaiting_claimant
    progress.awaiting_external
    progress.staff_assistance_requested
    progress.staff_assisting
    progress.follow_up_due
    progress.follow_up_overdue
    progress.ready_to_lodge
    progress.claim_lodged
    progress.assessor_requested
    progress.assessor_assigned
    progress.repair_contact_pending
    progress.external_request_in_progress
    progress.customer_update_due
    attention.fraud_l1
    attention.fraud_l2
    attention.fraud_l3
    attention.coverage_review
    attention.liability_review
    attention.liability_disputed
    attention.customer_dispute
    attention.identity_verification
    attention.duplicate_claim
    attention.material_conflict
    attention.complex_loss
    attention.privacy_sensitive
    """
)


@dataclass(frozen=True, slots=True)
class _ProjectionRule:
    source_types: tuple[str, ...]
    projection_mode: TagProjectionMode
    activation_rule_ref: str
    exit_rule_ref: str = 'tag_projection.project_staff_tags.recompute'


def _rules(
    codes: str,
    *,
    source_types: tuple[str, ...],
    projection_mode: TagProjectionMode = TagProjectionMode.DETERMINISTIC,
    activation_rule_ref: str,
) -> dict[str, _ProjectionRule]:
    rule = _ProjectionRule(
        source_types=source_types,
        projection_mode=projection_mode,
        activation_rule_ref=activation_rule_ref,
    )
    return {code: rule for code in codes.split()}


_PROJECTION_RULES = {
    **_rules(
        'claim_type.motor claim_type.home claim_type.contents claim_type.unconfirmed',
        source_types=('claim.incident_type', 'field.incident.type'),
        activation_rule_ref='tag_projection._project_claim_type',
    ),
    **_rules(
        """
        incident.collision incident.vehicle_theft incident.contents_theft
        incident.fire_smoke incident.water_escape incident.cause_unconfirmed
        """,
        source_types=('field.incident.type',),
        activation_rule_ref='tag_projection._project_incident',
    ),
    **_rules(
        """
        injury.none_reported injury.status_unknown injury.reported_unassessed
        safety.scene_safe_reported safety.scene_uncertain safety.immediate_help_needed
        safety.accessibility_support
        """,
        source_types=('field.incident.injury_or_danger', 'claim.urgency', 'claim.customer_support'),
        activation_rule_ref='tag_projection._project_people_and_safety',
    ),
    **_rules(
        'stakeholder.police stakeholder.emergency_services',
        source_types=('field.authorities', 'evidence.police_report'),
        activation_rule_ref='tag_projection._project_stakeholders',
    ),
    **_rules(
        """
        impact.vehicle_drivable impact.vehicle_not_drivable impact.vehicle_safety_unknown
        impact.home_habitable impact.home_uninhabitable impact.habitability_unknown
        impact.property_unsecured impact.further_loss_ongoing impact.multiple_areas_items
        """,
        source_types=('field.vehicle', 'field.property'),
        activation_rule_ref='tag_projection._project_impact',
    ),
    **_rules(
        """
        evidence.photos_supplied evidence.video_supplied evidence.dashcam_available
        evidence.proof_of_ownership evidence.police_reference evidence.police_report_pending
        evidence.repair_quote
        evidence.assessment_report evidence.partial evidence.ready_for_review
        evidence.source_conflict
        """,
        source_types=('evidence_record',),
        activation_rule_ref='tag_projection._project_evidence',
    ),
    **_rules(
        """
        progress.new_report progress.details_incomplete progress.awaiting_claimant
        progress.awaiting_external progress.staff_assistance_requested progress.staff_assisting
        progress.ready_to_lodge progress.external_request_in_progress
        """,
        source_types=('claim_state', 'field', 'evidence_record', 'handoff'),
        activation_rule_ref='tag_projection._project_progress',
    ),
    **_rules(
        'progress.claim_lodged progress.assessor_requested progress.assessor_assigned '
        'stakeholder.assessor',
        source_types=('external_result',),
        projection_mode=TagProjectionMode.EXTERNAL_RESULT,
        activation_rule_ref='tag_projection._project_progress',
    ),
    **_rules(
        'attention.coverage_review attention.material_conflict attention.complex_loss',
        source_types=('claim_state', 'evidence_record', 'review_signal', 'staff_decision'),
        activation_rule_ref='tag_projection._project_attention',
    ),
}

_ATTENTION_LEVELS = {
    'attention.fraud_l1': TagAttentionLevel.NOTICE,
    'attention.fraud_l2': TagAttentionLevel.ELEVATED,
    'attention.fraud_l3': TagAttentionLevel.HIGH,
    'attention.coverage_review': TagAttentionLevel.ELEVATED,
    'attention.liability_review': TagAttentionLevel.ELEVATED,
    'attention.liability_disputed': TagAttentionLevel.HIGH,
    'attention.customer_dispute': TagAttentionLevel.ELEVATED,
    'attention.identity_verification': TagAttentionLevel.ELEVATED,
    'attention.duplicate_claim': TagAttentionLevel.HIGH,
    'attention.material_conflict': TagAttentionLevel.HIGH,
    'attention.complex_loss': TagAttentionLevel.ELEVATED,
    'attention.privacy_sensitive': TagAttentionLevel.NOTICE,
}


def _family_mapping() -> dict[str, tuple[str, ...]]:
    groups = (
        (_MOTOR_ONLY_CODES, ('motor',)),
        (_HOME_ONLY_CODES, ('home',)),
        (_CONTENTS_ONLY_CODES, ('contents',)),
        (_HOME_CONTENTS_CODES, ('home', 'contents')),
        (_ALL_FAMILY_CODES, CLAIM_FAMILIES),
    )
    mapping: dict[str, tuple[str, ...]] = {}
    for codes, families in groups:
        for code in codes:
            if code in mapping:
                raise ValueError(f'Duplicate staff tag family mapping: {code}.')
            mapping[code] = families
    return mapping


_FAMILY_MAPPING = MappingProxyType(_family_mapping())


def _build_registry() -> dict[str, StaffTagDefinition]:
    registry: dict[str, StaffTagDefinition] = {}
    prefixes: dict[TagCategory, str | tuple[str, ...]] = {
        TagCategory.CLAIM_TYPE: 'claim_type.',
        TagCategory.INCIDENT: 'incident.',
        TagCategory.PEOPLE_SAFETY: ('injury.', 'safety.'),
        TagCategory.STAKEHOLDER: 'stakeholder.',
        TagCategory.IMPACT: 'impact.',
        TagCategory.EVIDENCE: 'evidence.',
        TagCategory.PROGRESS: 'progress.',
        TagCategory.ATTENTION: 'attention.',
    }
    definition_codes = {definition.code for definition in _DEFINITIONS}
    family_codes = set(_FAMILY_MAPPING)
    if family_codes != definition_codes:
        missing = sorted(definition_codes - family_codes)
        unknown = sorted(family_codes - definition_codes)
        raise ValueError(f'Invalid staff tag family map; missing={missing}, unknown={unknown}.')
    if set(_ATTENTION_LEVELS) != {
        definition.code
        for definition in _DEFINITIONS
        if definition.category is TagCategory.ATTENTION
    }:
        raise ValueError('Every Attention tag requires exactly one attention level.')
    for definition in _DEFINITIONS:
        if definition.code in registry:
            raise ValueError(f'Duplicate staff tag code: {definition.code}.')
        if not definition.code.startswith(prefixes[definition.category]):
            raise ValueError(
                f'Staff tag {definition.code} does not match {definition.category.value}.'
            )
        rule = _PROJECTION_RULES.get(definition.code)
        enriched = replace(
            definition,
            applicable_claim_families=_FAMILY_MAPPING[definition.code],
            source_types=rule.source_types if rule is not None else (),
            activation_rule_ref=(rule.activation_rule_ref if rule is not None else 'unavailable'),
            exit_rule_ref=(rule.exit_rule_ref if rule is not None else 'unavailable'),
            projection_mode=(
                rule.projection_mode if rule is not None else TagProjectionMode.UNAVAILABLE
            ),
            attention_level=_ATTENTION_LEVELS.get(definition.code),
            filterable=(definition.status is TagDefinitionStatus.PUBLISHED and rule is not None),
        )
        registry[definition.code] = enriched
    return registry


STAFF_TAG_REGISTRY = MappingProxyType(_build_registry())


def get_staff_tag_definition(code: str) -> StaffTagDefinition:
    """Return one published tag definition.

    Args:
        code: Stable namespaced tag code.

    Returns:
        The matching published definition.

    Raises:
        ValueError: The code is unknown or is not published.
    """

    definition = STAFF_TAG_REGISTRY.get(code)
    if definition is None or definition.status is not TagDefinitionStatus.PUBLISHED:
        raise ValueError(f'Unknown published staff tag: {code}.')
    return definition


def _is_filterable_staff_tag_definition(definition: StaffTagDefinition) -> bool:
    return definition.status is TagDefinitionStatus.PUBLISHED and definition.filterable


def get_filterable_staff_tag_definition(code: str) -> StaffTagDefinition:
    """Return one published tag definition accepted by staff queue filters.

    Args:
        code: Stable namespaced tag code.

    Returns:
        The matching published, filterable definition.

    Raises:
        ValueError: The code is unknown, unpublished, or not filterable.
    """

    definition = STAFF_TAG_REGISTRY.get(code)
    if definition is None or not _is_filterable_staff_tag_definition(definition):
        raise ValueError(f'Unknown filterable staff tag: {code}.')
    return definition


def list_filterable_staff_tag_definitions() -> list[StaffTagDefinition]:
    """Return the canonical published tag options exposed to staff filters.

    Returns:
        Published, filterable definitions in stable label and code order.
    """

    return sorted(
        (
            definition
            for definition in STAFF_TAG_REGISTRY.values()
            if _is_filterable_staff_tag_definition(definition)
        ),
        key=lambda definition: (definition.staff_label.casefold(), definition.code),
    )

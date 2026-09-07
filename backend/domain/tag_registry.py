"""Versioned staff-facing classification tags for Workbench projections."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

TAG_REGISTRY_ID: Final = 'northwind-fnol-staff-tags'
TAG_REGISTRY_VERSION: Final = '0.2'


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
    VISIBLE = 'visible'
    SAFE_SUMMARY_ONLY = 'safe_summary_only'
    STAFF_ONLY = 'staff_only'


class TagBasis(StrEnum):
    REPORTED = 'reported'
    DERIVED = 'derived'
    VERIFIED = 'verified'
    STAFF_ASSESSED = 'staff_assessed'


class TagInstanceStatus(StrEnum):
    PROPOSED = 'proposed'
    ACTIVE = 'active'
    DISPUTED = 'disputed'
    RETIRED = 'retired'


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
    filterable: bool = True


_CATEGORY_DEFAULTS: dict[
    TagCategory,
    tuple[TagVisibility, tuple[str, ...], int, bool, str],
] = {
    TagCategory.CLAIM_TYPE: (
        TagVisibility.VISIBLE,
        ('content_branch', 'confirmed_fact'),
        50,
        False,
        'Classifies the policy or loss scope',
    ),
    TagCategory.INCIDENT: (
        TagVisibility.VISIBLE,
        ('content_branch', 'confirmed_fact'),
        60,
        False,
        'Describes the reported incident',
    ),
    TagCategory.PEOPLE_SAFETY: (
        TagVisibility.SAFE_SUMMARY_ONLY,
        ('confirmed_fact', 'staff_assessment', 'emergency_source'),
        10,
        True,
        'Summarises reported people and safety context',
    ),
    TagCategory.STAKEHOLDER: (
        TagVisibility.VISIBLE,
        ('confirmed_fact', 'external_operation'),
        70,
        False,
        'Identifies a participant or service party',
    ),
    TagCategory.IMPACT: (
        TagVisibility.SAFE_SUMMARY_ONLY,
        ('confirmed_fact', 'external_result', 'staff_assessment'),
        30,
        False,
        'Summarises the reported practical impact',
    ),
    TagCategory.EVIDENCE: (
        TagVisibility.SAFE_SUMMARY_ONLY,
        ('evidence_record', 'work_item'),
        80,
        False,
        'Summarises available or pending evidence',
    ),
    TagCategory.PROGRESS: (
        TagVisibility.SAFE_SUMMARY_ONLY,
        ('lifecycle', 'work_item', 'handoff', 'external_operation'),
        40,
        False,
        'Summarises current claim progress',
    ),
    TagCategory.ATTENTION: (
        TagVisibility.STAFF_ONLY,
        ('review_signal', 'staff_decision'),
        20,
        True,
        'Flags a source-linked matter for staff attention',
    ),
}


def _rows(
    category: TagCategory,
    values: tuple[tuple[str, str, TagScope], ...],
) -> list[StaffTagDefinition]:
    visibility, sources, weight, authority, description = _CATEGORY_DEFAULTS[category]
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
                visibility=visibility,
                applicable_claim_families=('motor', 'home', 'contents'),
                source_types=sources,
                activation_rule_ref=f'tag.{code}.activate.v1',
                exit_rule_ref=f'tag.{code}.retire.v1',
                queue_display_weight=weight,
                requires_professional_authority=authority,
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
    for definition in _DEFINITIONS:
        if definition.code in registry:
            raise ValueError(f'Duplicate staff tag code: {definition.code}.')
        if not definition.code.startswith(prefixes[definition.category]):
            raise ValueError(
                f'Staff tag {definition.code} does not match {definition.category.value}.'
            )
        registry[definition.code] = definition
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

"""Project human-readable staff tags from authoritative Claim records."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from backend.domain.models import (
    AgentAction,
    AssessorRoutingStatus,
    Coverage,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    FormSource,
    FormStatus,
    HandoffRecord,
    HandoffStatus,
    HandoffType,
    NeededFor,
    ResponsibleParty,
    Severity,
    SignalDecisionRecord,
    SignalDecisionValue,
    SupportNeed,
    Urgency,
    WorkflowState,
    WorkingClaim,
)
from backend.domain.retrieval import ReviewSignalRecord
from backend.domain.tag_registry import (
    TAG_REGISTRY_VERSION,
    StaffTag,
    TagBasis,
    TagFreshness,
    TagInstanceStatus,
    TagProjectionMode,
    TagSourceActor,
    get_staff_tag_definition,
)

_PENDING_FILE_STATES = {
    EvidenceFileStatus.AWAITING_UPLOAD,
    EvidenceFileStatus.UPLOADING,
    EvidenceFileStatus.UPLOADED,
    EvidenceFileStatus.PROCESSING,
}
_PENDING_EVIDENCE_STATES = {
    EvidenceStatus.PENDING_GENERATION,
    EvidenceStatus.INCOMPLETE,
    EvidenceStatus.UNOFFICIAL,
}
_CLOSED_HANDOFF_STATES = {HandoffStatus.RESOLVED, HandoffStatus.CANCELLED}


class _TagAdder(Protocol):
    def __call__(
        self,
        code: str,
        *,
        basis: TagBasis,
        source_refs: Sequence[str],
        activated_at: datetime,
        status: TagInstanceStatus = TagInstanceStatus.ACTIVE,
        source_actor: TagSourceActor | None = None,
        freshness: TagFreshness = TagFreshness.CURRENT,
    ) -> None: ...


def _basis_for(source: FormSource) -> TagBasis:
    if source is FormSource.CLAIMANT:
        return TagBasis.REPORTED
    if source is FormSource.STAFF:
        return TagBasis.STAFF_ASSESSED
    if source in {FormSource.DOCUMENT, FormSource.IMAGE}:
        return TagBasis.VERIFIED
    return TagBasis.DERIVED


def _source_actor_for_form(source: FormSource) -> TagSourceActor:
    if source is FormSource.CLAIMANT:
        return TagSourceActor.CLAIMANT
    if source is FormSource.STAFF:
        return TagSourceActor.STAFF
    return TagSourceActor.SYSTEM


def _source_actor_for_evidence(source: EvidenceSource) -> TagSourceActor:
    if source is EvidenceSource.CLAIMANT:
        return TagSourceActor.CLAIMANT
    if source is EvidenceSource.STAFF:
        return TagSourceActor.STAFF
    return TagSourceActor.EXTERNAL_SERVICE


def _source_actor_for_basis(basis: TagBasis) -> TagSourceActor:
    if basis is TagBasis.REPORTED:
        return TagSourceActor.CLAIMANT
    if basis is TagBasis.STAFF_ASSESSED:
        return TagSourceActor.STAFF
    return TagSourceActor.SYSTEM


def _status_for(field_status: FormStatus) -> TagInstanceStatus:
    if field_status is FormStatus.DISPUTED:
        return TagInstanceStatus.DISPUTED
    return TagInstanceStatus.ACTIVE


def _signal_is_active(
    signal_id: str,
    decisions: Sequence[SignalDecisionRecord],
) -> bool:
    matching = [item for item in decisions if item.signal_id == signal_id]
    if not matching:
        return True
    latest = max(matching, key=lambda item: item.created_at)
    return latest.decision not in {SignalDecisionValue.DISMISSED, SignalDecisionValue.RESOLVED}


def project_staff_tags(
    claim: WorkingClaim,
    *,
    evidence: Sequence[EvidenceRecord],
    handoffs: Sequence[HandoffRecord],
    review_signals: Sequence[ReviewSignalRecord],
    signal_decisions: Sequence[SignalDecisionRecord],
) -> list[StaffTag]:
    """Project active staff tags without creating a competing Claim state.

    Args:
        claim: Authoritative Claim record.
        evidence: Persisted Evidence records for the Claim.
        handoffs: Persisted handoff records for the Claim.
        review_signals: Source-linked review signals for authorised staff.
        signal_decisions: Staff decisions used to retire resolved signals.

    Returns:
        Stable, human-readable tags sorted for Workbench display.
    """

    projected: dict[str, StaffTag] = {}

    def add(
        code: str,
        *,
        basis: TagBasis,
        source_refs: Sequence[str],
        activated_at: datetime,
        status: TagInstanceStatus = TagInstanceStatus.ACTIVE,
        source_actor: TagSourceActor | None = None,
        freshness: TagFreshness = TagFreshness.CURRENT,
    ) -> None:
        definition = get_staff_tag_definition(code)
        if definition.projection_mode is TagProjectionMode.UNAVAILABLE:
            raise ValueError(f'Staff tag {code} has no implemented projection rule.')
        family = (claim.incident_type or '').strip().lower()
        if code != 'claim_type.unconfirmed' and family not in definition.applicable_claim_families:
            return
        refs = list(dict.fromkeys(ref for ref in source_refs if ref))
        if not refs:
            raise ValueError(f'Staff tag {code} requires at least one source reference.')
        projected[code] = StaffTag(
            tag_instance_id=f'{claim.claim_id}:{code}',
            code=code,
            registry_version=TAG_REGISTRY_VERSION,
            label=definition.staff_label,
            description=definition.staff_description,
            category=definition.category,
            status=status,
            visibility=definition.visibility,
            basis=basis,
            source_actor=source_actor or _source_actor_for_basis(basis),
            freshness=freshness,
            projection_mode=definition.projection_mode,
            attention_level=definition.attention_level,
            source_refs=refs,
            activated_at=activated_at,
            display_weight=definition.queue_display_weight,
        )

    _project_claim_type(claim, add)
    _project_incident(claim, add)
    _project_people_and_safety(claim, add)
    _project_stakeholders(claim, evidence, add)
    _project_impact(claim, add)
    _project_evidence(evidence, add)
    _project_progress(claim, evidence, handoffs, add)
    _project_attention(claim, evidence, review_signals, signal_decisions, add)

    return sorted(
        projected.values(),
        key=lambda item: (item.display_weight, item.category.value, item.label, item.code),
    )


def _project_claim_type(claim: WorkingClaim, add: _TagAdder) -> None:
    add_tag = add
    family = (claim.incident_type or '').strip().lower()
    field = claim.form.get('claim.product_family')
    if family in {'motor', 'home', 'contents'}:
        if field is not None and field.value == family:
            basis = _basis_for(field.source)
            refs = [*field.source_refs, 'field:claim.product_family']
            activated_at = field.updated_at
            status = _status_for(field.status)
            source_actor = _source_actor_for_form(field.source)
        else:
            basis = TagBasis.DERIVED
            refs = [f'claim:{claim.claim_id}:incident_type']
            activated_at = claim.created_at
            status = TagInstanceStatus.ACTIVE
            source_actor = TagSourceActor.SYSTEM
        add_tag(
            f'claim_type.{family}',
            basis=basis,
            source_refs=refs,
            activated_at=activated_at,
            status=status,
            source_actor=source_actor,
        )
        return
    add_tag(
        'claim_type.unconfirmed',
        basis=TagBasis.DERIVED,
        source_refs=[f'claim:{claim.claim_id}:incident_type'],
        activated_at=claim.created_at,
        source_actor=TagSourceActor.SYSTEM,
    )


def _project_incident(claim: WorkingClaim, add: _TagAdder) -> None:
    field = claim.form.get('incident.type')
    if field is None or field.status is FormStatus.MISSING:
        add(
            'incident.cause_unconfirmed',
            basis=TagBasis.DERIVED,
            source_refs=['field:incident.type'],
            activated_at=claim.created_at,
            source_actor=TagSourceActor.SYSTEM,
        )
        return
    if field.status not in {FormStatus.CONFIRMED, FormStatus.DISPUTED}:
        return
    if not isinstance(field.value, str):
        return

    family = (claim.incident_type or '').strip().lower()
    subtype = field.value.strip().lower()
    code_by_family_and_subtype = {
        ('motor', 'collision'): 'incident.collision',
        ('motor', 'theft'): 'incident.vehicle_theft',
        ('contents', 'theft'): 'incident.contents_theft',
        ('motor', 'fire'): 'incident.fire_smoke',
        ('home', 'fire'): 'incident.fire_smoke',
        ('contents', 'fire'): 'incident.fire_smoke',
        ('home', 'water'): 'incident.water_escape',
        ('contents', 'water'): 'incident.water_escape',
    }
    code = code_by_family_and_subtype.get((family, subtype))
    if code is None:
        return
    add(
        code,
        basis=_basis_for(field.source),
        source_refs=[*field.source_refs, 'field:incident.type'],
        activated_at=field.updated_at,
        status=_status_for(field.status),
        source_actor=_source_actor_for_form(field.source),
    )


def _project_people_and_safety(claim: WorkingClaim, add: _TagAdder) -> None:
    add_tag = add
    injury = claim.form.get('incident.injury_or_danger')
    if injury is None or injury.status is FormStatus.MISSING:
        add_tag(
            'injury.status_unknown',
            basis=TagBasis.DERIVED,
            source_refs=['field:incident.injury_or_danger'],
            activated_at=claim.created_at,
            source_actor=TagSourceActor.SYSTEM,
        )
    elif injury.status is FormStatus.CONFIRMED and injury.value is False:
        refs = [*injury.source_refs, 'field:incident.injury_or_danger']
        add_tag(
            'injury.none_reported',
            basis=_basis_for(injury.source),
            source_refs=refs,
            activated_at=injury.updated_at,
            status=_status_for(injury.status),
            source_actor=_source_actor_for_form(injury.source),
        )
    elif injury.status is FormStatus.CONFIRMED and injury.value is True:
        add_tag(
            'injury.reported_unassessed',
            basis=_basis_for(injury.source),
            source_refs=[*injury.source_refs, 'field:incident.injury_or_danger'],
            activated_at=injury.updated_at,
            status=_status_for(injury.status),
            source_actor=_source_actor_for_form(injury.source),
        )

    # The current combined injury/danger field can establish a safe scene only when the
    # claimant explicitly answers false. Generic urgency does not prove an unsafe scene:
    # it may originate from injury or another urgent need. Keep the scene classification
    # uncertain until a dedicated source-backed safety fact exists.
    if injury is not None and injury.status is FormStatus.CONFIRMED and injury.value is False:
        add_tag(
            'safety.scene_safe_reported',
            basis=_basis_for(injury.source),
            source_refs=[*injury.source_refs, 'field:incident.injury_or_danger'],
            activated_at=injury.updated_at,
            source_actor=_source_actor_for_form(injury.source),
        )
    else:
        add_tag(
            'safety.scene_uncertain',
            basis=TagBasis.DERIVED,
            source_refs=['field:incident.injury_or_danger'],
            activated_at=claim.created_at,
            source_actor=TagSourceActor.SYSTEM,
        )

    if claim.claim_state.urgency is Urgency.IMMEDIATE_SAFETY_RISK:
        add_tag(
            'safety.immediate_help_needed',
            basis=TagBasis.DERIVED,
            source_refs=[f'claim:{claim.claim_id}:urgency'],
            activated_at=claim.updated_at,
            source_actor=TagSourceActor.SYSTEM,
        )

    if claim.claim_state.customer_support.value == 'accessibility_required':
        add_tag(
            'safety.accessibility_support',
            basis=TagBasis.REPORTED,
            source_refs=[f'claim:{claim.claim_id}:customer_support'],
            activated_at=claim.updated_at,
            source_actor=TagSourceActor.CLAIMANT,
        )


def _project_stakeholders(
    claim: WorkingClaim,
    evidence: Sequence[EvidenceRecord],
    add: _TagAdder,
) -> None:
    add_tag = add
    police_field = claim.form.get('authorities.police_report_reference')
    police_evidence = [item for item in evidence if item.kind == 'police_report']
    confirmed_field = None
    if (
        police_field is not None
        and police_field.status in {FormStatus.CONFIRMED, FormStatus.DISPUTED}
        and bool(police_field.value)
    ):
        confirmed_field = police_field
    if confirmed_field is not None or police_evidence:
        source_times = [item.created_at for item in police_evidence]
        source_refs = [f'evidence:{item.evidence_id}' for item in police_evidence]
        if confirmed_field is not None:
            source_times.append(confirmed_field.updated_at)
            source_refs.extend(
                [*confirmed_field.source_refs, 'field:authorities.police_report_reference']
            )
        if police_evidence and confirmed_field is None:
            basis = TagBasis.VERIFIED
            source_actor = _source_actor_for_evidence(police_evidence[0].source)
        elif confirmed_field is not None and not police_evidence:
            basis = _basis_for(confirmed_field.source)
            source_actor = _source_actor_for_form(confirmed_field.source)
        else:
            basis = TagBasis.DERIVED
            source_actor = TagSourceActor.SYSTEM
        add_tag(
            'stakeholder.police',
            basis=basis,
            source_refs=source_refs,
            activated_at=min(source_times),
            status=(
                TagInstanceStatus.DISPUTED
                if confirmed_field is not None and confirmed_field.status is FormStatus.DISPUTED
                else TagInstanceStatus.ACTIVE
            ),
            source_actor=source_actor,
        )
    if confirmed_field is not None:
        add_tag(
            'evidence.police_reference',
            basis=_basis_for(confirmed_field.source),
            source_refs=[
                *confirmed_field.source_refs,
                'field:authorities.police_report_reference',
            ],
            activated_at=confirmed_field.updated_at,
            status=_status_for(confirmed_field.status),
            source_actor=_source_actor_for_form(confirmed_field.source),
        )

    emergency = claim.form.get('authorities.emergency_services_notified')
    if (
        emergency is not None
        and emergency.status is FormStatus.CONFIRMED
        and emergency.value is True
    ):
        add_tag(
            'stakeholder.emergency_services',
            basis=_basis_for(emergency.source),
            source_refs=[*emergency.source_refs, 'field:authorities.emergency_services_notified'],
            activated_at=emergency.updated_at,
            source_actor=_source_actor_for_form(emergency.source),
        )


def _project_impact(claim: WorkingClaim, add: _TagAdder) -> None:
    add_tag = add
    family = (claim.incident_type or '').strip().lower()
    drivable = claim.form.get('vehicle.drivable')
    if drivable is None or drivable.status is FormStatus.MISSING:
        if family == 'motor':
            add_tag(
                'impact.vehicle_safety_unknown',
                basis=TagBasis.DERIVED,
                source_refs=['field:vehicle.drivable'],
                activated_at=claim.created_at,
            )
    elif drivable.status is FormStatus.CONFIRMED and isinstance(drivable.value, bool):
        add_tag(
            'impact.vehicle_drivable' if drivable.value else 'impact.vehicle_not_drivable',
            basis=_basis_for(drivable.source),
            source_refs=[*drivable.source_refs, 'field:vehicle.drivable'],
            activated_at=drivable.updated_at,
        )

    affected_areas = claim.form.get('property.affected_areas')
    if affected_areas is None or affected_areas.status is not FormStatus.CONFIRMED:
        return
    if isinstance(affected_areas.value, list) and len(affected_areas.value) > 1:
        add_tag(
            'impact.multiple_areas_items',
            basis=_basis_for(affected_areas.source),
            source_refs=[*affected_areas.source_refs, 'field:property.affected_areas'],
            activated_at=affected_areas.updated_at,
        )


def _is_pending_evidence(item: EvidenceRecord) -> bool:
    return item.status in _PENDING_EVIDENCE_STATES or item.file_status in _PENDING_FILE_STATES


def _project_evidence(evidence: Sequence[EvidenceRecord], add: _TagAdder) -> None:
    add_tag = add
    ready = [
        item
        for item in evidence
        if item.status is EvidenceStatus.RECEIVED and item.file_status is EvidenceFileStatus.READY
    ]
    pending = [item for item in evidence if _is_pending_evidence(item)]
    kind_to_tag = {
        'incident_image': 'evidence.photos_supplied',
        'photo': 'evidence.photos_supplied',
        'video': 'evidence.video_supplied',
        'dashcam': 'evidence.dashcam_available',
        'receipt': 'evidence.proof_of_ownership',
        'invoice': 'evidence.proof_of_ownership',
        'proof_of_ownership': 'evidence.proof_of_ownership',
        'repair_quote': 'evidence.repair_quote',
        'assessment_report': 'evidence.assessment_report',
    }
    for item in ready:
        code = kind_to_tag.get(item.kind)
        if code is not None:
            add_tag(
                code,
                basis=TagBasis.VERIFIED,
                source_refs=[f'evidence:{item.evidence_id}'],
                activated_at=item.created_at,
            )
    for item in evidence:
        if item.kind == 'police_report' and item.status is EvidenceStatus.PENDING_GENERATION:
            add_tag(
                'evidence.police_report_pending',
                basis=TagBasis.VERIFIED,
                source_refs=[f'evidence:{item.evidence_id}'],
                activated_at=item.created_at,
            )
    if ready and pending:
        combined = [*ready, *pending]
        add_tag(
            'evidence.partial',
            basis=TagBasis.DERIVED,
            source_refs=[f'evidence:{item.evidence_id}' for item in combined],
            activated_at=max(item.updated_at for item in combined),
        )
    if ready and not pending:
        add_tag(
            'evidence.ready_for_review',
            basis=TagBasis.DERIVED,
            source_refs=[f'evidence:{item.evidence_id}' for item in ready],
            activated_at=max(item.updated_at for item in ready),
        )


def _project_progress(
    claim: WorkingClaim,
    evidence: Sequence[EvidenceRecord],
    handoffs: Sequence[HandoffRecord],
    add: _TagAdder,
) -> None:
    add_tag = add
    pending = [item for item in evidence if _is_pending_evidence(item)]
    open_handoffs = [item for item in handoffs if item.status not in _CLOSED_HANDOFF_STATES]
    for handoff in open_handoffs:
        source_refs = [f'handoff:{handoff.handoff_id}']
        if (
            handoff.type is HandoffType.HUMAN_SUPPORT
            and handoff.support_need is SupportNeed.HUMAN_REQUESTED
            and handoff.status in {HandoffStatus.REQUESTED, HandoffStatus.QUEUED}
        ):
            add_tag(
                'progress.staff_assistance_requested',
                basis=TagBasis.REPORTED,
                source_refs=source_refs,
                activated_at=handoff.created_at,
            )
        if handoff.status in {HandoffStatus.ACCEPTED, HandoffStatus.IN_PROGRESS}:
            add_tag(
                'progress.staff_assisting',
                basis=TagBasis.VERIFIED,
                source_refs=source_refs,
                activated_at=handoff.accepted_at or handoff.created_at,
            )

    if claim.claim_state.workflow_state is WorkflowState.COLLECTING and not open_handoffs:
        add_tag(
            'progress.new_report',
            basis=TagBasis.DERIVED,
            source_refs=[f'claim:{claim.claim_id}:workflow_state'],
            activated_at=claim.created_at,
        )

    missing_required: list[str] = []
    for code, field in claim.form.items():
        if field.status is FormStatus.MISSING and field.needed_for is NeededFor.CURRENT_ACTION:
            missing_required.append(code)
    if missing_required:
        add_tag(
            'progress.details_incomplete',
            basis=TagBasis.DERIVED,
            source_refs=[f'field:{code}' for code in missing_required],
            activated_at=claim.updated_at,
        )

    claimant_pending = [
        item for item in pending if item.responsible_party is ResponsibleParty.CLAIMANT
    ]
    if claimant_pending:
        add_tag(
            'progress.awaiting_claimant',
            basis=TagBasis.DERIVED,
            source_refs=[f'evidence:{item.evidence_id}' for item in claimant_pending],
            activated_at=claim.updated_at,
        )
    external_pending = [
        item for item in pending if item.responsible_party is ResponsibleParty.EXTERNAL_PARTY
    ]
    if external_pending:
        add_tag(
            'progress.awaiting_external',
            basis=TagBasis.DERIVED,
            source_refs=[f'evidence:{item.evidence_id}' for item in external_pending],
            activated_at=claim.updated_at,
        )

    if claim.claim_state.next_action is AgentAction.CREATE_CLAIM:
        add_tag(
            'progress.ready_to_lodge',
            basis=TagBasis.DERIVED,
            source_refs=[f'claim:{claim.claim_id}:next_action'],
            activated_at=claim.updated_at,
        )
    if claim.external_claim is not None and claim.external_claim.creation_status.value == 'created':
        add_tag(
            'progress.claim_lodged',
            basis=TagBasis.VERIFIED,
            source_refs=[
                f'external_claim:{claim.external_claim.external_claim_id or claim.claim_id}'
            ],
            activated_at=claim.external_claim.created_at,
        )

    routing = claim.assessor_routing
    if routing is None:
        return
    if routing.routing_status is AssessorRoutingStatus.ASSIGNED:
        source_refs = [f'assessor:{routing.assessor_reference or claim.claim_id}']
        add_tag(
            'progress.assessor_assigned',
            basis=TagBasis.VERIFIED,
            source_refs=source_refs,
            activated_at=claim.updated_at,
        )
        add_tag(
            'stakeholder.assessor',
            basis=TagBasis.VERIFIED,
            source_refs=source_refs,
            activated_at=claim.updated_at,
        )
    elif routing.routing_status is AssessorRoutingStatus.QUEUED:
        source_refs = [f'assessor_queue:{routing.queue_reference or claim.claim_id}']
        add_tag(
            'progress.assessor_requested',
            basis=TagBasis.VERIFIED,
            source_refs=source_refs,
            activated_at=claim.updated_at,
        )
        add_tag(
            'progress.external_request_in_progress',
            basis=TagBasis.VERIFIED,
            source_refs=source_refs,
            activated_at=claim.updated_at,
        )


def _project_attention(
    claim: WorkingClaim,
    evidence: Sequence[EvidenceRecord],
    review_signals: Sequence[ReviewSignalRecord],
    signal_decisions: Sequence[SignalDecisionRecord],
    add: _TagAdder,
) -> None:
    add_tag = add
    if claim.claim_state.coverage in {Coverage.AMBIGUOUS, Coverage.REVIEW_REQUIRED}:
        add_tag(
            'attention.coverage_review',
            basis=TagBasis.DERIVED,
            source_refs=[f'claim:{claim.claim_id}:coverage'],
            activated_at=claim.updated_at,
        )
    if claim.claim_state.severity is Severity.COMPLEX:
        add_tag(
            'attention.complex_loss',
            basis=TagBasis.DERIVED,
            source_refs=[f'claim:{claim.claim_id}:severity'],
            activated_at=claim.updated_at,
        )

    inconsistent = [item for item in evidence if item.status is EvidenceStatus.INCONSISTENT]
    if inconsistent:
        refs = [f'evidence:{item.evidence_id}' for item in inconsistent]
        activated_at = max(item.updated_at for item in inconsistent)
        add_tag(
            'evidence.source_conflict',
            basis=TagBasis.VERIFIED,
            source_refs=refs,
            activated_at=activated_at,
        )
        add_tag(
            'attention.material_conflict',
            basis=TagBasis.DERIVED,
            source_refs=refs,
            activated_at=activated_at,
        )

    for signal in review_signals:
        if not _signal_is_active(signal.signal_id, signal_decisions):
            continue
        combined_codes = {signal.code, *signal.reason_codes}
        if any(
            'POLICY' in value and ('UNCERTAINT' in value or 'REVIEW' in value)
            for value in combined_codes
        ):
            add_tag(
                'attention.coverage_review',
                basis=TagBasis.DERIVED,
                source_refs=[signal.signal_id, *signal.source_refs],
                activated_at=signal.created_at,
            )
        if any('CONFLICT' in value or 'INCONSISTENC' in value for value in combined_codes):
            add_tag(
                'attention.material_conflict',
                basis=TagBasis.DERIVED,
                source_refs=[signal.signal_id, *signal.source_refs],
                activated_at=signal.created_at,
            )

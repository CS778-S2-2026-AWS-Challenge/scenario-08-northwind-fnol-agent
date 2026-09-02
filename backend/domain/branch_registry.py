"""Provider-neutral branch registry and deterministic dynamic-form evaluator.

The registry is a checked-in, versioned snapshot for the VP.  It is deliberately
small enough to review in source control while keeping the application-facing
port replaceable by a future Control Plane publication.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from backend.domain.field_registry import REGISTERED_FIELD_CODES
from backend.domain.models import (
    AgentAction,
    BranchEvaluationResult,
    BranchResult,
    FieldSelectionResult,
    FieldSelectionState,
    FormStatus,
    WorkingClaim,
)

FAMILY_NAMES = ('motor', 'home', 'contents')
COMMON_FIELDS = frozenset(
    {
        'claim.product_family',
        'incident.description',
        'incident.occurred_at',
        'incident.location',
        'incident.cause',
        'loss.description',
        'claimant.client_number',
        'claimant.role',
        'claimant.contact_preference',
        'policy.policy_number',
        'incident.injury_or_danger',
    }
)
FAMILY_FIELDS = {
    'motor': frozenset(
        {
            'incident.type',
            'vehicle.registration',
            'vehicle.damage_description',
            'vehicle.drivable',
            'parties.other_parties',
            'authorities.police_report_reference',
            'authorities.emergency_services_notified',
            'collision.occurred',
            'collision.impact_area',
            'collision.movement',
            'other_vehicle.identity',
            'other_party.contact',
            'witness.details',
            'road.conditions',
            'weather.visibility',
            'authority.police_status',
            'authority.police_reference',
            'repairer.details',
            'motor.evidence_refs',
        }
    ),
    'home': frozenset(
        {
            'incident.type',
            'property.address',
            'property.occupancy_relationship',
            'property.occupancy',
            'property.affected_areas',
            'property.building_damage',
            'property.fixture_damage',
            'property.cause_source',
            'property.severity',
            'property.ongoing_risk',
            'property.habitable',
            'property.utilities',
            'mitigation.emergency_action',
            'mitigation.temporary_repair',
            'mitigation.contractor',
            'accommodation.required',
            'accommodation.details',
            'weather.event',
            'home.evidence_refs',
        }
    ),
    'contents': frozenset(
        {
            'incident.type',
            'contents.items',
            'contents.item.description',
            'contents.item.category',
            'contents.item.quantity',
            'contents.item.brand',
            'contents.item.model',
            'contents.item.serial_number',
            'contents.item.ownership',
            'contents.item.purchase_date',
            'contents.item.purchase_source',
            'contents.item.estimated_value',
            'contents.item.replacement_need',
            'contents.item.loss_type',
            'contents.discovery_at',
            'theft.entry_context',
            'contents.receipt_availability',
            'contents.proof_of_ownership',
            'contents.police_status',
            'contents.police_reference',
            'contents.item.evidence_refs',
            'contents.item_group',
        }
    ),
}

SYSTEM_OWNED_FIELDS = frozenset({'claim.product_family'})
FAMILY_PATTERNS = {
    'motor': re.compile(
        r'\b(car|vehicle|motor|driv(?:e|ing)|collision|crash|road|traffic)\b', re.I
    ),
    'home': re.compile(r'\b(home|house|property|roof|room|building|pipe|flood|storm)\b', re.I),
    'contents': re.compile(r'\b(contents|belongings|item|laptop|phone|stolen|theft|lost)\b', re.I),
}


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    code: str
    family: str | None = None
    system_owned: bool = False


@dataclass(frozen=True, slots=True)
class ContentBranch:
    branch_id: str
    family: str | None
    fields: frozenset[str]


@dataclass(frozen=True, slots=True)
class BranchRegistrySnapshot:
    version: str
    fields: tuple[FieldDefinition, ...]
    branches: tuple[ContentBranch, ...]

    @property
    def field_codes(self) -> frozenset[str]:
        return frozenset(field.code for field in self.fields)

    @property
    def branch_by_id(self) -> dict[str, ContentBranch]:
        return {branch.branch_id: branch for branch in self.branches}


def build_default_registry() -> BranchRegistrySnapshot:
    """Return the immutable VP registry snapshot used by the local runtime."""

    all_codes = set(REGISTERED_FIELD_CODES) | COMMON_FIELDS
    for family_fields in FAMILY_FIELDS.values():
        all_codes.update(family_fields)
    definitions = tuple(
        FieldDefinition(
            code=code,
            family=next(
                (family for family, fields in FAMILY_FIELDS.items() if code in fields),
                None,
            ),
            system_owned=code in SYSTEM_OWNED_FIELDS,
        )
        for code in sorted(all_codes)
    )
    branches = [
        ContentBranch(f'family.{family}', family, frozenset(COMMON_FIELDS | FAMILY_FIELDS[family]))
        for family in FAMILY_NAMES
    ]
    branches.extend(
        [
            ContentBranch(
                'incident.collision',
                'motor',
                frozenset({'collision.occurred', 'collision.impact_area', 'collision.movement'}),
            ),
            ContentBranch(
                'participant.another_party',
                None,
                frozenset(
                    {'parties.other_parties', 'other_vehicle.identity', 'other_party.contact'}
                ),
            ),
            ContentBranch('participant.witness', None, frozenset({'witness.details'})),
            ContentBranch(
                'authority.police',
                None,
                frozenset(
                    {
                        'authority.police_status',
                        'authority.police_reference',
                        'authorities.police_report_reference',
                    }
                ),
            ),
            ContentBranch(
                'evidence.pending', None, frozenset({'authorities.police_report_reference'})
            ),
            ContentBranch(
                'accommodation.temporary',
                'home',
                frozenset({'accommodation.required', 'accommodation.details'}),
            ),
            ContentBranch(
                'contents.theft',
                'contents',
                frozenset(
                    {'theft.entry_context', 'contents.police_status', 'contents.police_reference'}
                ),
            ),
        ]
    )
    return BranchRegistrySnapshot(version='vp-1', fields=definitions, branches=tuple(branches))


class BranchRuleEvaluator:
    """Pure deterministic branch/form evaluator.

    The evaluator reads a claim snapshot and produces a proposal.  It never
    calls a model/provider, writes Claim State, or persists an evaluation.
    """

    def __init__(self, registry: BranchRegistrySnapshot | None = None) -> None:
        self.registry = registry or build_default_registry()

    def evaluate(
        self,
        claim: WorkingClaim,
        *,
        latest_message: str | None = None,
        current_action: AgentAction | str | None = None,
        recomputation_reason: str = 'turn',
    ) -> BranchEvaluationResult:
        text = latest_message or ''
        family_candidates = self._family_candidates(claim, text)
        selected_family = family_candidates[0] if len(family_candidates) == 1 else None
        conflict = family_candidates if len(family_candidates) > 1 else []
        active: list[str] = []
        candidate: list[str] = []
        suspended: list[str] = []
        exited: list[str] = []
        branch_results: list[BranchResult] = []

        for family in FAMILY_NAMES:
            branch_id = f'family.{family}'
            if selected_family == family:
                active.append(branch_id)
                branch_results.append(
                    BranchResult(
                        branch_id=branch_id,
                        status='active',
                        reason='The claim has one deterministic family classification.',
                        registered_fields=sorted(COMMON_FIELDS | FAMILY_FIELDS[family]),
                    )
                )
            elif family in family_candidates:
                candidate.append(branch_id)
                branch_results.append(
                    BranchResult(
                        branch_id=branch_id,
                        status='candidate',
                        reason='The family is mentioned but conflicts with another candidate.',
                        registered_fields=sorted(COMMON_FIELDS | FAMILY_FIELDS[family]),
                    )
                )
            else:
                branch_results.append(
                    BranchResult(
                        branch_id=branch_id,
                        status='exited',
                        reason='No current evidence activates this family.',
                        registered_fields=[],
                    )
                )
                exited.append(branch_id)

        conditional = self._conditional_branches(selected_family, claim, text)
        for branch_id, reason, fields in conditional:
            active.append(branch_id)
            branch_results.append(
                BranchResult(
                    branch_id=branch_id,
                    status='active',
                    reason=reason,
                    registered_fields=sorted(fields),
                )
            )

        active_fields = set(COMMON_FIELDS)
        for branch_id in active:
            branch = self.registry.branch_by_id.get(branch_id)
            if branch is not None:
                active_fields.update(branch.fields)
        # When family evidence conflicts, retain candidate family fields for
        # proposal capture and clarification, but do not mark either family
        # active or expose those fields as claimant-required questions.
        if selected_family is None and conflict:
            for family in conflict:
                active_fields.update(FAMILY_FIELDS[family])
        selections = [
            self._select_field(
                field.code,
                active_fields,
                claim,
                selected_family,
                current_action,
                conflict,
            )
            for field in self.registry.fields
        ]
        return BranchEvaluationResult(
            claim_id=claim.claim_id,
            evaluated_against_claim_revision=claim.revision,
            registry_version=self.registry.version,
            selected_family=selected_family,
            unresolved_family_conflict=conflict,
            active_branches=active,
            candidate_branches=candidate,
            suspended_branches=suspended,
            exited_branches=exited,
            branch_results=branch_results,
            field_selection=selections,
            work_item_intents=self._work_item_intents(selections),
            handoff_intents=self._handoff_intents(claim),
            evidence_intents=self._evidence_intents(claim),
            consent_intents=[],
            integration_intents=[],
            interruption_result=self._interruption(claim),
            recomputation_reason=recomputation_reason,
        )

    def _family_candidates(self, claim: WorkingClaim, text: str) -> list[str]:
        explicit = claim.form.get('claim.product_family')
        if (
            explicit is not None
            and explicit.value in FAMILY_NAMES
            and explicit.status is not FormStatus.DISPUTED
        ):
            return [str(explicit.value)]
        incident_type = claim.form.get('incident.type')
        if (
            incident_type is not None
            and incident_type.value in FAMILY_NAMES
            and incident_type.status is not FormStatus.DISPUTED
        ):
            return [str(incident_type.value)]
        if claim.incident_type in FAMILY_NAMES:
            return [claim.incident_type]
        return [family for family in FAMILY_NAMES if FAMILY_PATTERNS[family].search(text)]

    def _conditional_branches(
        self, selected_family: str | None, claim: WorkingClaim, text: str
    ) -> list[tuple[str, str, frozenset[str]]]:
        branches: list[tuple[str, str, frozenset[str]]] = []
        values = {code: str(field.value).lower() for code, field in claim.form.items()}
        if selected_family == 'motor' and (
            'parties.other_parties' in values
            or re.search(r'\b(other driver|another car|rear[- ]?ended|hit me)\b', text, re.I)
        ):
            branches.append(
                (
                    'incident.collision',
                    'Collision wording activates the motor collision branch.',
                    self.registry.branch_by_id['incident.collision'].fields,
                )
            )
            branches.append(
                (
                    'participant.another_party',
                    'Another party is explicitly mentioned.',
                    self.registry.branch_by_id['participant.another_party'].fields,
                )
            )
        if re.search(r'\b(police|police report|constable|incident number)\b', text, re.I) or any(
            code in values
            for code in ('authority.police_status', 'authorities.police_report_reference')
        ):
            branches.append(
                (
                    'authority.police',
                    'Police involvement or a police report is recorded.',
                    self.registry.branch_by_id['authority.police'].fields,
                )
            )
        if re.search(
            r'\b(later|pending|not yet|will provide|waiting)\b.*\b(report|police)\b', text, re.I
        ):
            branches.append(
                (
                    'evidence.pending',
                    'The message states that required evidence is not yet available.',
                    self.registry.branch_by_id['evidence.pending'].fields,
                )
            )
        if selected_family == 'home' and re.search(
            r'\b(not habitable|temporary accommodation|hotel)\b', text, re.I
        ):
            branches.append(
                (
                    'accommodation.temporary',
                    'The home is not habitable or accommodation is requested.',
                    self.registry.branch_by_id['accommodation.temporary'].fields,
                )
            )
        if selected_family == 'contents' and re.search(
            r'\b(stolen|theft|burglary|break[- ]?in)\b', text, re.I
        ):
            branches.append(
                (
                    'contents.theft',
                    'Theft wording activates the contents authority branch.',
                    self.registry.branch_by_id['contents.theft'].fields,
                )
            )
        if claim.form.get('witness.details') is not None or re.search(r'\bwitness\b', text, re.I):
            branches.append(
                (
                    'participant.witness',
                    'A witness is mentioned.',
                    self.registry.branch_by_id['participant.witness'].fields,
                )
            )
        return branches

    def _select_field(
        self,
        code: str,
        active_fields: set[str],
        claim: WorkingClaim,
        selected_family: str | None,
        current_action: AgentAction | str | None,
        family_conflict: list[str] | None = None,
    ) -> FieldSelectionResult:
        field = next(item for item in self.registry.fields if item.code == code)
        stored = claim.form.get(code)
        value_state = stored.status if stored is not None else FormStatus.MISSING
        if field.system_owned:
            return FieldSelectionResult(
                field_code=code,
                selection_state=FieldSelectionState.SYSTEM_OWNED,
                value_state=value_state,
                source=stored.source if stored else None,
                reason='The value is owned by routing or identity, not a claimant question.',
            )
        if code not in active_fields or (
            field.family is not None
            and selected_family != field.family
            and not (selected_family is None and field.family in (family_conflict or []))
        ):
            return FieldSelectionResult(
                field_code=code,
                selection_state=FieldSelectionState.INACTIVE,
                value_state=value_state,
                source=stored.source if stored else None,
                reason='The field is outside the selected content branch.',
            )
        if code.endswith('police_report_reference') and self._police_pending(claim):
            return FieldSelectionResult(
                field_code=code,
                selection_state=FieldSelectionState.PENDING_LATER,
                value_state=value_state,
                source=stored.source if stored else None,
                reason='The claimant has recorded the evidence as pending for a later action.',
            )
        if value_state is not FormStatus.MISSING:
            return FieldSelectionResult(
                field_code=code,
                selection_state=FieldSelectionState.CANDIDATE_NOW,
                value_state=value_state,
                source=stored.source if stored else None,
                reason='A value exists; do not ask the claimant to repeat it.',
            )
        action = current_action.value if isinstance(current_action, AgentAction) else current_action
        required = self._required_now(code, selected_family, action)
        state = FieldSelectionState.REQUIRED_NOW if required else FieldSelectionState.CANDIDATE_NOW
        return FieldSelectionResult(
            field_code=code,
            selection_state=state,
            value_state=value_state,
            source=None,
            reason='Missing and required for the current safe action.'
            if required
            else 'Relevant but not blocking the current safe action.',
        )

    @staticmethod
    def _required_now(code: str, family: str | None, action: AgentAction | str | None) -> bool:
        if action in {AgentAction.CREATE_CLAIM.value, 'create_claim', 'confirm'}:
            return code in {'incident.description', 'incident.occurred_at', 'incident.location'}
        if action in {AgentAction.ASK.value, 'intake', None}:
            return code == 'incident.description'
        return False

    @staticmethod
    def _police_pending(claim: WorkingClaim) -> bool:
        evidence = claim.form.get('authorities.police_report_reference')
        return evidence is not None and evidence.status is FormStatus.PENDING_GENERATION

    @staticmethod
    def _work_item_intents(selections: Iterable[FieldSelectionResult]) -> list[dict[str, object]]:
        return [
            {
                'type': 'field',
                'field_code': item.field_code,
                'selection_state': item.selection_state.value,
            }
            for item in selections
            if item.selection_state
            in {FieldSelectionState.REQUIRED_NOW, FieldSelectionState.PENDING_LATER}
        ]

    @staticmethod
    def _handoff_intents(claim: WorkingClaim) -> list[dict[str, object]]:
        if claim.claim_state.workflow_state.value == 'professional_review':
            return [{'type': 'professional_review', 'required': True}]
        return []

    @staticmethod
    def _evidence_intents(claim: WorkingClaim) -> list[dict[str, object]]:
        return (
            [{'type': 'pending', 'count': claim.evidence_summary.pending}]
            if claim.evidence_summary.pending
            else []
        )

    @staticmethod
    def _interruption(claim: WorkingClaim) -> dict[str, object]:
        if claim.claim_state.urgency.value in {'urgent', 'immediate_safety_risk'}:
            return {'control': 'interrupt', 'reason': 'urgent_safety'}
        if claim.claim_state.customer_support.value in {
            'human_requested',
            'accessibility_required',
        }:
            return {'control': 'handoff', 'reason': 'human_support'}
        return {'control': 'continue'}


__all__ = [
    'BranchRegistrySnapshot',
    'BranchRuleEvaluator',
    'ContentBranch',
    'FieldDefinition',
    'build_default_registry',
]

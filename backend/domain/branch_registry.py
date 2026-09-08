"""Provider-neutral Dynamic Form branch registry and deterministic evaluator."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from backend.domain.field_registry import FIELD_REGISTRY_VERSION, REGISTERED_FIELD_CODES
from backend.domain.models import (
    AgentAction,
    BranchEvaluationRecord,
    BranchEvaluationResult,
    BranchResult,
    FieldSelectionResult,
    FieldSelectionState,
    FormStatus,
    TemporalFactValue,
    WorkingClaim,
)
from backend.domain.support_intent import (
    SupportIntent,
    detect_support_intent,
    support_need_for_intent,
)

BRANCH_RULES_VERSION = 'vp-dynamic-form-branch-rules-v1'
FAMILY_NAMES = ('motor', 'home', 'contents')
FAMILY_RULE_IDS = {
    'motor': 'BR-FAMILY-MOTOR-001',
    'home': 'BR-FAMILY-HOME-001',
    'contents': 'BR-FAMILY-CONTENTS-001',
}
CONDITIONAL_TRANSITION_STATUS = {
    'incident.collision': 'suspended',
    'participant.another_party': 'exited',
    'participant.witness': 'exited',
    'authority.police': 'suspended',
    'evidence.pending': 'exited',
    'accommodation.temporary': 'exited',
    'contents.theft': 'suspended',
    'safety.injury_or_danger': 'suspended',
    'mitigation.emergency': 'exited',
    'professional_review': 'exited',
    'human_support': 'exited',
}

# Only fields already supported by the generic form contract are executable here.
# The complete VP catalogue remains design input until each candidate or separate
# record receives its typed domain, API, persistence, and visibility contracts.
COMMON_FIELDS = frozenset(
    {
        'policy.policy_number',
        'claimant.client_number',
        'claimant.role',
        'claimant.contact_preference',
        'claim.product_family',
        'incident.type',
        'incident.occurred_at',
        'incident.location',
        'incident.description',
        'incident.injury_or_danger',
        'incident.cause',
        'loss.description',
        'parties.other_parties',
    }
)
FAMILY_FIELDS = {
    'motor': frozenset(
        {
            'authorities.police_report_reference',
            'authorities.emergency_services_notified',
            'vehicle.registration',
            'vehicle.damage_description',
            'vehicle.drivable',
        }
    ),
    'home': frozenset(
        {
            'property.address',
            'property.affected_areas',
            'property.ongoing_risk',
            'property.habitable',
        }
    ),
    'contents': frozenset(),
}
SYSTEM_OWNED_FIELDS = frozenset({'claimant.client_number'})
CLAIMANT_HIDDEN_FIELDS = frozenset({'claimant.client_number'})
FAMILY_PATTERNS = {
    'motor': re.compile(
        r'\b(car|vehicle|motor|driv(?:e|ing)|collision|crash|road|traffic)\b', re.I
    ),
    'home': re.compile(r'\b(home|house|property|roof|room|building|pipe|flood|storm)\b', re.I),
    'contents': re.compile(r'\b(contents|belongings|item|laptop|phone|stolen|theft|lost)\b', re.I),
}

FIELD_VALUE_CONTRACTS: dict[str, tuple[str, frozenset[str]]] = {
    'policy.policy_number': ('text', frozenset()),
    'claimant.client_number': ('text', frozenset()),
    'claimant.role': ('text', frozenset()),
    'claimant.contact_preference': (
        'enum',
        frozenset({'in_app', 'email', 'phone', 'sms'}),
    ),
    'claim.product_family': ('enum', frozenset(FAMILY_NAMES)),
    'incident.type': (
        'enum',
        frozenset({'collision', 'fire', 'water', 'theft', 'weather', 'other'}),
    ),
    'incident.occurred_at': ('temporal', frozenset()),
    'incident.location': ('location', frozenset()),
    'incident.description': ('text', frozenset()),
    'incident.injury_or_danger': ('boolean', frozenset()),
    'incident.cause': ('text', frozenset()),
    'loss.description': ('text', frozenset()),
    'parties.other_parties': ('boolean', frozenset()),
    'authorities.police_report_reference': ('text', frozenset()),
    'authorities.emergency_services_notified': ('boolean', frozenset()),
    'vehicle.registration': ('text', frozenset()),
    'vehicle.damage_description': ('text', frozenset()),
    'vehicle.drivable': ('boolean', frozenset()),
    'property.address': ('location', frozenset()),
    'property.affected_areas': ('text_list', frozenset()),
    'property.ongoing_risk': (
        'enum',
        frozenset({'none', 'active_leak', 'fire', 'collapse', 'exposure', 'other'}),
    ),
    'property.habitable': ('boolean', frozenset()),
}


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    code: str
    value_type: str
    allowed_values: frozenset[str] = frozenset()
    families: frozenset[str] = frozenset()
    system_owned: bool = False
    claimant_visible: bool = True


@dataclass(frozen=True, slots=True)
class ContentBranch:
    branch_id: str
    rule_id: str
    family: str | None
    fields: frozenset[str]


@dataclass(frozen=True, slots=True)
class BranchRegistrySnapshot:
    field_registry_version: str
    branch_rules_version: str
    fields: tuple[FieldDefinition, ...]
    branches: tuple[ContentBranch, ...]

    @property
    def field_codes(self) -> frozenset[str]:
        return frozenset(field.code for field in self.fields)

    @property
    def branch_by_id(self) -> dict[str, ContentBranch]:
        return {branch.branch_id: branch for branch in self.branches}

    @property
    def field_by_code(self) -> dict[str, FieldDefinition]:
        return {field.code: field for field in self.fields}


def build_default_registry() -> BranchRegistrySnapshot:
    """Return the checked-in executable VP registry snapshot."""

    executable_codes = set(REGISTERED_FIELD_CODES)
    if executable_codes != FIELD_VALUE_CONTRACTS.keys():
        missing = sorted(executable_codes - FIELD_VALUE_CONTRACTS.keys())
        extra = sorted(FIELD_VALUE_CONTRACTS.keys() - executable_codes)
        raise RuntimeError(
            f'Field value contracts do not match the registry: {missing=}, {extra=}.'
        )
    fields = tuple(
        FieldDefinition(
            code=code,
            value_type=FIELD_VALUE_CONTRACTS[code][0],
            allowed_values=FIELD_VALUE_CONTRACTS[code][1],
            families=frozenset(
                family for family, family_fields in FAMILY_FIELDS.items() if code in family_fields
            ),
            system_owned=code in SYSTEM_OWNED_FIELDS,
            claimant_visible=code not in CLAIMANT_HIDDEN_FIELDS,
        )
        for code in sorted(executable_codes)
    )
    branches = [
        ContentBranch(
            branch_id=f'family.{family}',
            rule_id=FAMILY_RULE_IDS[family],
            family=family,
            fields=frozenset((COMMON_FIELDS | FAMILY_FIELDS[family]) & executable_codes),
        )
        for family in FAMILY_NAMES
    ]
    branches.extend(
        [
            ContentBranch(
                'incident.collision',
                'BR-COLLISION-001',
                None,
                frozenset({'parties.other_parties'} & executable_codes),
            ),
            ContentBranch(
                'participant.another_party',
                'BR-PARTICIPANT-OTHER-001',
                None,
                frozenset({'parties.other_parties'} & executable_codes),
            ),
            ContentBranch('participant.witness', 'BR-PARTICIPANT-WITNESS-001', None, frozenset()),
            ContentBranch(
                'authority.police',
                'BR-AUTHORITY-POLICE-001',
                None,
                frozenset(
                    {
                        'authorities.police_report_reference',
                        'authorities.emergency_services_notified',
                    }
                    & executable_codes
                ),
            ),
            ContentBranch(
                'evidence.pending',
                'BR-EVIDENCE-PENDING-001',
                None,
                frozenset({'authorities.police_report_reference'} & executable_codes),
            ),
            ContentBranch('accommodation.temporary', 'BR-ACCOMMODATION-001', 'home', frozenset()),
            ContentBranch('contents.theft', 'BR-THEFT-001', None, frozenset()),
            ContentBranch(
                'safety.injury_or_danger',
                'BR-SAFETY-001',
                None,
                frozenset({'incident.injury_or_danger'} & executable_codes),
            ),
            ContentBranch('mitigation.emergency', 'BR-MITIGATION-001', None, frozenset()),
            ContentBranch('professional_review', 'BR-REVIEW-001', None, frozenset()),
            ContentBranch('human_support', 'BR-HUMAN-SUPPORT-001', None, frozenset()),
        ]
    )
    return BranchRegistrySnapshot(
        field_registry_version=FIELD_REGISTRY_VERSION,
        branch_rules_version=BRANCH_RULES_VERSION,
        fields=fields,
        branches=tuple(branches),
    )


class BranchRuleEvaluator:
    """Evaluate branch and field relevance without I/O or Claim State mutation."""

    def __init__(
        self,
        registry: BranchRegistrySnapshot | None = None,
        *,
        disabled_rule_ids: frozenset[str] | None = None,
        observation_rule_ids: frozenset[str] | None = None,
    ) -> None:
        self.registry = registry or build_default_registry()
        self.disabled_rule_ids = disabled_rule_ids or frozenset()
        self.observation_rule_ids = observation_rule_ids or frozenset()

    def evaluate(
        self,
        claim: WorkingClaim,
        *,
        latest_message: str | None = None,
        trigger_source_refs: Sequence[str] = (),
        current_action: AgentAction | str | None = None,
        recomputation_reason: str = 'turn',
        previous_evaluation: BranchEvaluationRecord | None = None,
    ) -> BranchEvaluationResult:
        text = latest_message or ''
        support_intent = detect_support_intent(text)
        selected_family, family_candidates, family_sources = self._family_state(
            claim, text, trigger_source_refs
        )
        unresolved_conflict = (
            sorted(family_candidates)
            if selected_family is None and len(family_candidates) > 1
            else []
        )
        branch_results: list[BranchResult] = []

        for family in FAMILY_NAMES:
            branch = self.registry.branch_by_id[f'family.{family}']
            if selected_family == family:
                status = 'active'
                reason = 'A confirmed family fact activates this mutually exclusive branch.'
            elif family in family_candidates:
                status = 'candidate'
                reason = 'Proposed or message evidence identifies a family candidate.'
            else:
                status = 'exited'
                reason = 'No current evidence supports this family.'
            branch_results.append(
                self._branch_result(branch, status, reason, family_sources.get(family, []))
            )

        branch_results.extend(
            self._conditional_branches(
                selected_family,
                claim,
                text,
                trigger_source_refs,
                support_intent,
            )
        )
        branch_results = self._reconcile_previous_conditional_branches(
            branch_results,
            previous_evaluation,
            trigger_source_refs,
        )
        branch_results = [self._apply_controlled_rule_policy(result) for result in branch_results]
        active = [result.branch_id for result in branch_results if result.status == 'active']
        candidate = [result.branch_id for result in branch_results if result.status == 'candidate']
        suspended = [result.branch_id for result in branch_results if result.status == 'suspended']
        exited = [result.branch_id for result in branch_results if result.status == 'exited']

        permitted_fields = set(COMMON_FIELDS & self.registry.field_codes)
        for branch_id in active:
            permitted_fields.update(self.registry.branch_by_id[branch_id].fields)
        if selected_family is None and len(family_candidates) == 1:
            candidate_family = next(iter(family_candidates))
            permitted_fields.update(FAMILY_FIELDS[candidate_family] & self.registry.field_codes)

        selections = [
            self._select_field(
                definition,
                permitted_fields,
                claim,
                selected_family,
                family_candidates,
                current_action,
            )
            for definition in self.registry.fields
        ]
        return BranchEvaluationResult(
            claim_id=claim.claim_id,
            evaluated_against_claim_revision=claim.revision,
            field_registry_version=self.registry.field_registry_version,
            branch_rules_version=self.registry.branch_rules_version,
            selected_family=selected_family,
            unresolved_family_conflict=unresolved_conflict,
            active_branches=active,
            candidate_branches=candidate,
            suspended_branches=suspended,
            exited_branches=exited,
            branch_results=branch_results,
            field_selection=selections,
            work_item_intents=self._work_item_intents(selections),
            handoff_intents=self._handoff_intents(
                claim,
                support_intent,
                trigger_source_refs,
            ),
            evidence_intents=self._evidence_intents(claim),
            consent_intents=[],
            integration_intents=[],
            interruption_result=self._interruption(claim, support_intent),
            permitted_actions=list(AgentAction),
            permitted_tools=[],
            recomputation_reason=recomputation_reason,
        )

    def _apply_controlled_rule_policy(self, result: BranchResult) -> BranchResult:
        if result.rule_id in self.disabled_rule_ids and result.status != 'exited':
            return result.model_copy(
                update={
                    'status': 'exited',
                    'registered_fields': [],
                    'reason': 'The published controlled-rule configuration disables this rule.',
                }
            )
        if result.rule_id in self.observation_rule_ids and result.status == 'active':
            return result.model_copy(
                update={
                    'status': 'candidate',
                    'registered_fields': [],
                    'reason': (
                        'The published controlled-rule configuration keeps this rule in '
                        'observation mode without activating its effects.'
                    ),
                }
            )
        return result

    def _family_state(
        self, claim: WorkingClaim, text: str, trigger_source_refs: Sequence[str]
    ) -> tuple[str | None, set[str], dict[str, list[str]]]:
        authoritative: set[str] = set()
        candidates: set[str] = set()
        sources: dict[str, list[str]] = {family: [] for family in FAMILY_NAMES}
        product_family_field = claim.form.get('claim.product_family')
        form_family: str | None = None
        if product_family_field is not None and isinstance(product_family_field.value, str):
            normalised = product_family_field.value.strip().lower()
            if normalised in FAMILY_NAMES:
                form_family = normalised
                sources[form_family].extend(product_family_field.source_refs)
                if product_family_field.status is FormStatus.CONFIRMED:
                    authoritative.add(form_family)
                elif product_family_field.status in {FormStatus.PROPOSED, FormStatus.DISPUTED}:
                    candidates.add(form_family)

        canonical_family = (
            claim.incident_type.strip().lower()
            if isinstance(claim.incident_type, str)
            and claim.incident_type.strip().lower() in FAMILY_NAMES
            else None
        )
        if canonical_family is not None:
            authoritative.add(canonical_family)
            sources[canonical_family].append(f'claim:{claim.claim_id}:incident_type')

        for family, pattern in FAMILY_PATTERNS.items():
            if pattern.search(text):
                candidates.add(family)
                sources[family].extend(trigger_source_refs)
        selected = next(iter(authoritative)) if len(authoritative) == 1 else None
        if len(authoritative) > 1:
            candidates.update(authoritative)
        if selected is not None:
            candidates.discard(selected)
        for family in sources:
            sources[family] = sorted(set(sources[family]))
        return selected, candidates, sources

    def _conditional_branches(
        self,
        selected_family: str | None,
        claim: WorkingClaim,
        text: str,
        trigger_source_refs: Sequence[str],
        support_intent: SupportIntent,
    ) -> list[BranchResult]:
        results: list[BranchResult] = []

        def add(
            branch_id: str,
            status: str,
            reason: str,
            codes: Sequence[str] = (),
            source_refs: Sequence[str] = (),
        ) -> None:
            branch = self.registry.branch_by_id[branch_id]
            refs = set(source_refs)
            if status == 'candidate':
                refs.update(trigger_source_refs)
            else:
                refs.update(self._source_refs(claim, codes))
            results.append(self._branch_result(branch, status, reason, refs))

        subtype_field = claim.form.get('incident.type')
        subtype = (
            subtype_field.value.strip().lower()
            if subtype_field is not None and isinstance(subtype_field.value, str)
            else None
        )
        subtype_confirmed = (
            subtype_field is not None and subtype_field.status is FormStatus.CONFIRMED
        )
        subtype_candidate = subtype_field is not None and subtype_field.status in {
            FormStatus.PROPOSED,
            FormStatus.DISPUTED,
        }
        subtype_refs = subtype_field.source_refs if subtype_field is not None else []

        another_party = self._confirmed_truthy(claim, 'parties.other_parties')
        collision_text = bool(
            re.search(
                r'\b(collision|crash|other driver|another car|rear[- ]?ended|hit me)\b',
                text,
                re.I,
            )
        )
        if subtype == 'collision' and subtype_confirmed:
            add(
                'incident.collision',
                'active',
                'A confirmed incident subtype records a collision.',
                ('incident.type',),
            )
        elif (subtype == 'collision' and subtype_candidate) or collision_text:
            add(
                'incident.collision',
                'candidate',
                'The incident subtype or claimant message describes a collision.',
                source_refs=subtype_refs,
            )

        if another_party:
            add(
                'participant.another_party',
                'active',
                'A confirmed fact records another participant.',
                ('parties.other_parties',),
            )
        elif re.search(
            r'\b(another person|another party|other party|other driver|another car)\b',
            text,
            re.I,
        ):
            add(
                'participant.another_party',
                'candidate',
                'The claimant message may identify another participant.',
            )

        police_codes = (
            'authorities.police_report_reference',
            'authorities.emergency_services_notified',
        )
        police_confirmed = any(self._confirmed_truthy(claim, code) for code in police_codes)
        police_text = bool(
            re.search(r'\b(police|police report|constable|incident number)\b', text, re.I)
        )
        if police_confirmed:
            add(
                'authority.police',
                'active',
                'Confirmed Claim State records Police involvement.',
                police_codes,
            )
        elif police_text:
            add(
                'authority.police',
                'candidate',
                'The claimant message mentions Police involvement.',
            )

        pending = self._police_pending(claim)
        pending_text = bool(
            re.search(
                r'\b(later|pending|not yet|will provide|waiting)\b.*\b(report|police)\b',
                text,
                re.I,
            )
        )
        if pending:
            add(
                'evidence.pending',
                'active',
                'Claim State records Police material as pending generation.',
                ('authorities.police_report_reference',),
                trigger_source_refs,
            )
        elif pending_text:
            add('evidence.pending', 'candidate', 'The claimant message describes pending material.')

        witness = claim.form.get('witness.details')
        if witness is not None and witness.status is FormStatus.CONFIRMED and bool(witness.value):
            add(
                'participant.witness',
                'active',
                'A confirmed fact records a witness.',
                ('witness.details',),
            )
        elif re.search(r'\bwitness\b', text, re.I):
            add('participant.witness', 'candidate', 'The claimant message mentions a witness.')

        if selected_family == 'home' and re.search(
            r'\b(not habitable|temporary accommodation|hotel)\b', text, re.I
        ):
            add(
                'accommodation.temporary',
                'candidate',
                'The claimant message describes a possible accommodation need.',
            )
        theft_text = bool(re.search(r'\b(stolen|theft|burglary|break[- ]?in)\b', text, re.I))
        if subtype == 'theft' and subtype_confirmed:
            add(
                'contents.theft',
                'active',
                'A confirmed incident subtype records theft or burglary.',
                ('incident.type',),
            )
        elif (subtype == 'theft' and subtype_candidate) or theft_text:
            add(
                'contents.theft',
                'candidate',
                'The incident subtype or claimant message describes possible theft.',
                source_refs=subtype_refs,
            )

        mitigation_text = bool(
            re.search(
                r'\b(active leak|fire|flood|water damage|unsafe property|'
                r'emergency repair|tow(?:ing)?)\b',
                text,
                re.I,
            )
        )
        if subtype in {'fire', 'water'} and subtype_confirmed:
            add(
                'mitigation.emergency',
                'active',
                'A confirmed fire or water subtype requires mitigation evaluation.',
                ('incident.type',),
            )
        elif (subtype in {'fire', 'water'} and subtype_candidate) or mitigation_text:
            add(
                'mitigation.emergency',
                'candidate',
                'The incident subtype or claimant message may require mitigation.',
                source_refs=subtype_refs,
            )

        safety_state = claim.claim_state.urgency.value in {'urgent', 'immediate_safety_risk'}
        safety_fact = self._confirmed_truthy(claim, 'incident.injury_or_danger')
        safety_text = bool(
            re.search(r'\b(injur(?:y|ed)|hurt|danger|unsafe|emergency)\b', text, re.I)
        )
        safety_negated = bool(
            re.search(
                r'\b(no one|nobody|not)\s+(?:was\s+)?(?:injured|hurt|in danger)\b', text, re.I
            )
        )
        if safety_state or safety_fact:
            refs = list(self._source_refs(claim, ('incident.injury_or_danger',)))
            if safety_state:
                refs.append(f'claim:{claim.claim_id}:claim_state.urgency')
            add(
                'safety.injury_or_danger',
                'active',
                'Authoritative Claim State records an urgent safety condition.',
                source_refs=refs,
            )
        elif safety_text and not safety_negated:
            add(
                'safety.injury_or_danger',
                'candidate',
                'The claimant message may describe an injury or continuing danger.',
            )

        if claim.claim_state.customer_support.value in {
            'human_requested',
            'accessibility_required',
        }:
            support_refs = [f'claim:{claim.claim_id}:claim_state.customer_support']
            if support_intent is not SupportIntent.NONE:
                support_refs.extend(trigger_source_refs)
            add(
                'human_support',
                'active',
                'Authoritative Claim State requires human support.',
                source_refs=support_refs,
            )
        elif support_intent is not SupportIntent.NONE:
            add(
                'human_support',
                'candidate',
                'The current claimant message explicitly requires human support.',
            )

        review_sources: list[str] = []
        if claim.claim_state.workflow_state.value == 'professional_review':
            review_sources.append(f'claim:{claim.claim_id}:claim_state.workflow_state')
        if claim.claim_state.coverage.value in {'ambiguous', 'review_required'}:
            review_sources.append(f'claim:{claim.claim_id}:claim_state.coverage')
        if claim.claim_state.fraud_signal.value == 'review_required':
            review_sources.append(f'claim:{claim.claim_id}:claim_state.fraud_signal')
        if review_sources:
            add(
                'professional_review',
                'active',
                'Authoritative Claim State requires professional review.',
                source_refs=review_sources,
            )
        return results

    @staticmethod
    def _reconcile_previous_conditional_branches(
        current_results: list[BranchResult],
        previous_evaluation: BranchEvaluationRecord | None,
        trigger_source_refs: Sequence[str],
    ) -> list[BranchResult]:
        if previous_evaluation is None:
            return current_results
        current_branch_ids = {result.branch_id for result in current_results}
        reconciled = list(current_results)
        for previous in previous_evaluation.branch_results:
            transition_status = CONDITIONAL_TRANSITION_STATUS.get(previous.branch_id)
            if (
                transition_status is None
                or previous.status not in {'active', 'candidate'}
                or previous.branch_id in current_branch_ids
            ):
                continue
            reconciled.append(
                previous.model_copy(
                    update={
                        'status': transition_status,
                        'reason': (
                            'The previously supported branch lost support after a source-backed '
                            'Claim correction or recalculation.'
                        ),
                        'source_refs': sorted(set(previous.source_refs) | set(trigger_source_refs)),
                        'registered_fields': [],
                    }
                )
            )
        return reconciled

    @staticmethod
    def _branch_result(
        branch: ContentBranch, status: str, reason: str, source_refs: Iterable[str]
    ) -> BranchResult:
        return BranchResult(
            branch_id=branch.branch_id,
            rule_id=branch.rule_id,
            source_refs=sorted(set(source_refs)),
            status=status,
            reason=reason,
            registered_fields=sorted(branch.fields) if status in {'active', 'candidate'} else [],
        )

    @staticmethod
    def _source_refs(claim: WorkingClaim, codes: Sequence[str]) -> list[str]:
        refs: set[str] = set()
        for code in codes:
            stored = claim.form.get(code)
            if stored is not None:
                refs.update(stored.source_refs)
        return sorted(refs)

    @staticmethod
    def _confirmed_truthy(claim: WorkingClaim, code: str) -> bool:
        stored = claim.form.get(code)
        if stored is None or stored.status is not FormStatus.CONFIRMED:
            return False
        value = stored.value
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() not in {
                '',
                'false',
                'no',
                'none',
                'not_applicable',
            }
        return bool(value)

    def _select_field(
        self,
        definition: FieldDefinition,
        permitted_fields: set[str],
        claim: WorkingClaim,
        selected_family: str | None,
        family_candidates: set[str],
        current_action: AgentAction | str | None,
    ) -> FieldSelectionResult:
        stored = claim.form.get(definition.code)
        value_state = stored.status if stored is not None else FormStatus.MISSING
        if definition.system_owned:
            selection_state = FieldSelectionState.SYSTEM_OWNED
            reason = 'The field is owned by an identity or workflow authority.'
        elif definition.code not in permitted_fields or (
            definition.families
            and selected_family not in definition.families
            and not definition.families.intersection(family_candidates)
        ):
            selection_state = FieldSelectionState.INACTIVE
            reason = 'The field is outside the selected or single candidate family.'
        elif definition.code.endswith('police_report_reference') and self._police_pending(claim):
            selection_state = FieldSelectionState.PENDING_LATER
            reason = 'The required material is recorded as pending for a later action.'
        elif value_state is not FormStatus.MISSING:
            selection_state = FieldSelectionState.CANDIDATE_NOW
            reason = 'A value exists and must not be requested again without a reason.'
        elif self._required_now(definition.code, current_action):
            selection_state = FieldSelectionState.REQUIRED_NOW
            reason = 'The field is missing and required for the current safe action.'
        else:
            selection_state = FieldSelectionState.CANDIDATE_NOW
            reason = 'The field is relevant but does not block the current safe action.'
        return FieldSelectionResult(
            field_code=definition.code,
            selection_state=selection_state,
            value_state=value_state,
            source=stored.source if stored else None,
            reason=reason,
        )

    @staticmethod
    def _required_now(code: str, action: AgentAction | str | None) -> bool:
        raw = action.value if isinstance(action, AgentAction) else action
        normalised = raw.upper() if isinstance(raw, str) else None
        if normalised in {AgentAction.CREATE_CLAIM.value, AgentAction.CONFIRM.value}:
            return code in {'incident.description', 'incident.occurred_at', 'incident.location'}
        if normalised in {AgentAction.ASK.value, 'INTAKE'} or normalised is None:
            return code == 'incident.description'
        return False

    @staticmethod
    def _police_pending(claim: WorkingClaim) -> bool:
        evidence = claim.form.get('authorities.police_report_reference')
        return claim.evidence_summary.pending > 0 or (
            evidence is not None and evidence.status is FormStatus.PENDING_GENERATION
        )

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
    def _handoff_intents(
        claim: WorkingClaim,
        support_intent: SupportIntent,
        trigger_source_refs: Sequence[str],
    ) -> list[dict[str, object]]:
        intents: list[dict[str, object]] = []
        if claim.claim_state.urgency.value in {'urgent', 'immediate_safety_risk'}:
            intents.append({'type': 'urgent_support', 'required': True})
        support_need = support_need_for_intent(support_intent)
        if support_need is not None:
            intents.append(
                {
                    'type': 'human_support',
                    'support_need': support_need.value,
                    'required': True,
                    'source_refs': sorted(set(trigger_source_refs)),
                }
            )
        elif claim.claim_state.customer_support.value in {
            'human_requested',
            'accessibility_required',
        }:
            intents.append(
                {
                    'type': 'human_support',
                    'support_need': claim.claim_state.customer_support.value,
                    'required': True,
                }
            )
        if claim.claim_state.workflow_state.value == 'professional_review':
            intents.append({'type': 'professional_review', 'required': True})
        return intents

    @staticmethod
    def _evidence_intents(claim: WorkingClaim) -> list[dict[str, object]]:
        if claim.evidence_summary.pending:
            return [{'type': 'pending', 'count': claim.evidence_summary.pending}]
        return []

    @staticmethod
    def _interruption(
        claim: WorkingClaim,
        support_intent: SupportIntent,
    ) -> dict[str, object]:
        if claim.claim_state.urgency.value in {'urgent', 'immediate_safety_risk'}:
            return {'control': 'interrupt', 'reason': 'urgent_safety'}
        if support_intent is not SupportIntent.NONE:
            return {'control': 'handoff', 'reason': support_intent.value}
        if claim.claim_state.customer_support.value in {
            'human_requested',
            'accessibility_required',
        }:
            return {'control': 'handoff', 'reason': 'human_support'}
        return {'control': 'continue'}


def claimant_projection_fields(
    evaluation: BranchEvaluationRecord,
    registry: BranchRegistrySnapshot | None = None,
) -> list[FieldSelectionResult]:
    """Filter an evaluation to claimant-visible, currently permitted fields."""

    active_registry = registry or build_default_registry()
    definitions = active_registry.field_by_code
    return [
        field
        for field in evaluation.field_selection_results
        if field.field_code in definitions
        and definitions[field.field_code].claimant_visible
        and field.selection_state
        not in {FieldSelectionState.INACTIVE, FieldSelectionState.SYSTEM_OWNED}
    ]


def validate_registered_field_value(
    field_code: str,
    value: object,
    *,
    status: FormStatus = FormStatus.PROPOSED,
    registry: BranchRegistrySnapshot | None = None,
) -> None:
    """Validate a generic form value against its executable field contract."""

    active_registry = registry or build_default_registry()
    definition = active_registry.field_by_code.get(field_code)
    if definition is None:
        raise ValueError(f'Unknown registered field: {field_code}.')
    if value is None and status in {
        FormStatus.MISSING,
        FormStatus.PENDING_GENERATION,
        FormStatus.UNAVAILABLE,
        FormStatus.SUPERSEDED,
    }:
        return
    valid = False
    if definition.value_type == 'text':
        valid = isinstance(value, str) and bool(value.strip())
    elif definition.value_type == 'boolean':
        valid = isinstance(value, bool)
    elif definition.value_type == 'enum':
        valid = isinstance(value, str) and value.strip().lower() in definition.allowed_values
    elif definition.value_type == 'location':
        valid = (isinstance(value, str) and bool(value.strip())) or (
            isinstance(value, Mapping) and bool(value)
        )
    elif definition.value_type == 'text_list':
        valid = (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, str) and bool(item.strip()) for item in value)
        )
    elif definition.value_type == 'temporal':
        valid = isinstance(value, str) and bool(value.strip())
        if isinstance(value, Mapping):
            try:
                TemporalFactValue.model_validate(value)
                valid = True
            except ValueError:
                valid = False
    if not valid:
        allowed = (
            f' Allowed values: {", ".join(sorted(definition.allowed_values))}.'
            if definition.allowed_values
            else ''
        )
        raise ValueError(f'{field_code} requires a {definition.value_type} value.{allowed}')


__all__ = [
    'BRANCH_RULES_VERSION',
    'BranchRegistrySnapshot',
    'BranchRuleEvaluator',
    'ContentBranch',
    'FieldDefinition',
    'build_default_registry',
    'claimant_projection_fields',
    'validate_registered_field_value',
]

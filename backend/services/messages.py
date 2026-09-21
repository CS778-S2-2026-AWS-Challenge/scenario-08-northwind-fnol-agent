import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from functools import wraps
from typing import ParamSpec, TypeVar, cast

from backend.adapters.claims_service import AssessorServiceAdapter
from backend.adapters.evidence_storage import EvidenceStorage, EvidenceStorageError
from backend.adapters.policy_history import PolicyHistoryAdapter
from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.agent_action_commands import ClaimContextCommand, build_claim_context_command
from backend.domain.agent_action_registry import (
    ActionActorRole,
    ExecutionAuthority,
    action_contract,
)
from backend.domain.audit import AuditEventEnvelope
from backend.domain.branch_registry import (
    BranchRuleEvaluator,
    validate_registered_field_value,
)
from backend.domain.field_registry import REGISTERED_FIELD_CODES
from backend.domain.ids import new_id
from backend.domain.model_gateway import ModelGatewayError
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AgentDecisionRecord,
    AgentProposalSource,
    AssertionRelation,
    AuthorityOutcome,
    BranchEvaluationRecord,
    BranchEvaluationResult,
    ClaimantContentsItem,
    ClaimantDecision,
    ClaimantExternalServiceAction,
    ClaimantMessage,
    ClaimantTurnRecovery,
    ContentsItem,
    CreateMessageRequest,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    FormChange,
    FormSource,
    FormStatus,
    HandoffRecord,
    HandoffType,
    MessageRecord,
    MessageTurnResponse,
    MessageVisibility,
    ProposedFormChange,
    QuestionRecord,
    ResponsibleParty,
    RuntimeTraceRecord,
    SessionRecord,
    StructuredFormField,
    WorkingClaim,
)
from backend.domain.realtime import AgentTurnProgressStage
from backend.domain.recovery_policy_registry import (
    RecoveryTrigger,
    claimant_recovery_projection,
    classify_recovery,
)
from backend.domain.retrieval import (
    ClaimHistoryRetrievalRecord,
    ClaimHistorySearchRequest,
    PolicyRetrievalRecord,
    PolicySearchRequest,
    RetrievalStatus,
)
from backend.domain.runtime import (
    RuntimeWorkItemRecord,
)
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.agent import (
    AgentEvidenceReference,
    AgentProposal,
    AgentTurnContext,
    AgentTurnProvider,
    detect_safety_interrupt,
    validate_proposal,
)
from backend.services.agent_action_execution import (
    ClaimantRuntimeActionDispatcher,
    ClaimContextHandlerOutcome,
)
from backend.services.agent_action_mapping import map_claim_context_execution_to_api
from backend.services.agent_external_lifecycle import (
    ExternalLifecycleContextError,
    build_agent_external_lifecycle_context,
)
from backend.services.agent_tools import (
    read_evidence_history_for_runtime,
    validate_evidence_proposal,
)
from backend.services.agent_turn_progress import AgentTurnProgressReporter
from backend.services.branching import (
    claimant_dynamic_form_projection,
    latest_applied_branch_evaluation,
)
from backend.services.claimant_action_projection import project_claimant_primary_action
from backend.services.claimant_form_projection import project_claimant_form_fields
from backend.services.evidence_visibility import default_evidence_visibility
from backend.services.external_capability_dispatcher import ExternalCapabilityDispatcher
from backend.services.external_service_eligibility import eligible_service_ids
from backend.services.external_service_entry import ExternalServiceEntryDecision
from backend.services.external_service_offers import (
    continue_granted_service_offers,
    message_external_actions,
    select_registered_service_intents,
)
from backend.services.external_services import claimant_assessor_action, claimant_next_step
from backend.services.fact_resolution import (
    provenance_messages_for_fields,
    resolve_contents_item_change,
    resolve_form_change,
)
from backend.services.handoffs import (
    claimant_handoff,
    commit_detected_handoff,
)
from backend.services.retrieval import search_claim_history, search_policy
from backend.services.runtime_agent_policy import (
    RuntimeAgentPolicyResolver,
    RuntimeAgentPolicySnapshot,
    enforce_agent_proposal,
)
from backend.services.runtime_configuration import RuntimeConfigurationResolutionError
from backend.services.support import (
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)
from backend.services.turn_family_resolution import resolve_turn_family
from backend.services.turn_reducer import compose_reply, reduce_turn
from backend.services.turn_router import route_turn

logger = logging.getLogger(__name__)

INTERNAL_ONLY_REASON_CODES = frozenset(
    {
        'SAFETY_STATUS_REQUIRED',
        'SAFETY_STATUS_UNCLEAR',
        'SAFETY_STATUS_RECORDED',
        'POLICY_WORDING_REVIEW_NEEDED',
        'PROFESSIONAL_REVIEW_REQUIRED',
        'EVIDENCE_PENDING_GENERATION',
        'ADDITIONAL_CONTEXT_RECORDED',
    }
)

_CONTEXT_TOOL_OPERATIONS = {
    'policy_history': frozenset({'search_policy'}),
    'claim_history': frozenset({'search_claim_history', 'lookup'}),
    'evidence.history': frozenset({'list'}),
}
_ACTION_TOOL_OPERATIONS = {
    'evidence_registry': frozenset({'record_pending_generation'}),
    'professional_review': frozenset({'create_policy_review'}),
}

_MODEL_EVIDENCE_FILE_STATES = frozenset(
    {
        EvidenceFileStatus.UPLOADED,
        EvidenceFileStatus.PROCESSING,
        EvidenceFileStatus.READY,
    }
)
_MODEL_EVIDENCE_MEDIA_TYPES = frozenset({'image/jpeg', 'image/png', 'application/pdf'})


@dataclass(frozen=True, slots=True)
class _TurnEvidenceResolver:
    repository: PersistenceRepository
    storage: EvidenceStorage
    claim_id: str
    customer_id: str
    allowed_media_types: dict[str, str]

    def resolve(self, evidence_id: str, media_type: str) -> bytes | None:
        if self.allowed_media_types.get(evidence_id) != media_type:
            return None
        evidence = self.repository.get_evidence(
            self.claim_id,
            evidence_id,
            self.customer_id,
        )
        if (
            evidence is None
            or evidence.file_status not in _MODEL_EVIDENCE_FILE_STATES
            or evidence.media_type != media_type
            or default_evidence_visibility(evidence.source) is MessageVisibility.INTERNAL_ONLY
            or evidence.status
            in {
                EvidenceStatus.INVALID,
                EvidenceStatus.EXPIRED,
                EvidenceStatus.SUPERSEDED,
                EvidenceStatus.UNAVAILABLE,
                EvidenceStatus.MISSING,
            }
        ):
            return None
        storage_key = evidence.provenance.get('storage_key')
        if not isinstance(storage_key, str) or not storage_key:
            return None
        try:
            return self.storage.read_upload(
                claim_id=self.claim_id,
                evidence_id=evidence_id,
                storage_key=storage_key,
            )
        except EvidenceStorageError:
            return None


def _validate_tool_requests(
    proposal: AgentProposal,
    branch_evaluation: BranchEvaluationResult,
) -> None:
    if len(proposal.required_tools) > 3:
        raise ApiError(
            status_code=503,
            code='AGENT_TOOL_NOT_PERMITTED',
            message='The Agent requested too many tools for one bounded turn.',
        )
    allowed_names = set(branch_evaluation.permitted_tools)
    seen: set[tuple[str, str]] = set()
    context_tool_count = sum(
        request.get('tool') in _CONTEXT_TOOL_OPERATIONS for request in proposal.required_tools
    )
    if context_tool_count > 1:
        raise ApiError(
            status_code=503,
            code='AGENT_TOOL_NOT_PERMITTED',
            message='The Agent requested more than one context lookup in a bounded turn.',
        )
    for request in proposal.required_tools:
        tool = request.get('tool')
        operation = request.get('operation')
        if not isinstance(tool, str) or not isinstance(operation, str):
            raise ApiError(
                status_code=503,
                code='AGENT_TOOL_NOT_PERMITTED',
                message='The Agent supplied an invalid structured tool request.',
            )
        operations = _CONTEXT_TOOL_OPERATIONS.get(tool) or _ACTION_TOOL_OPERATIONS.get(tool)
        identity = (tool, operation)
        if tool not in allowed_names or operations is None or operation not in operations:
            raise ApiError(
                status_code=503,
                code='AGENT_TOOL_NOT_PERMITTED',
                message='The Agent requested an unregistered tool operation.',
            )
        if identity in seen:
            raise ApiError(
                status_code=503,
                code='AGENT_TOOL_NOT_PERMITTED',
                message='The Agent repeated a tool operation in one bounded turn.',
            )
        seen.add(identity)
        if (
            tool == 'policy_history'
            and operation == 'search_policy'
            and (
                not isinstance(request.get('policy_reference'), str)
                or not str(request['policy_reference']).strip()
            )
        ):
            raise ApiError(
                status_code=503,
                code='AGENT_TOOL_NOT_PERMITTED',
                message='The Agent supplied an invalid policy lookup request.',
            )
        if tool == 'claim_history' and operation in {'search_claim_history', 'lookup'}:
            if (
                not isinstance(request.get('history_reference'), str)
                or not str(request['history_reference']).strip()
            ):
                raise ApiError(
                    status_code=503,
                    code='AGENT_TOOL_NOT_PERMITTED',
                    message='The Agent supplied an invalid claim-history lookup request.',
                )
            limit = request.get('limit', 10)
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
                raise ApiError(
                    status_code=503,
                    code='AGENT_TOOL_NOT_PERMITTED',
                    message='The Agent supplied an invalid claim-history result limit.',
                )
        if tool == 'evidence.history' and operation == 'list':
            unexpected = set(request) - {'tool', 'operation', 'limit', 'cursor'}
            if unexpected:
                raise ApiError(
                    status_code=503,
                    code='AGENT_TOOL_NOT_PERMITTED',
                    message='The Agent supplied an invalid Evidence history request.',
                )
            limit = request.get('limit', 25)
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
                raise ApiError(
                    status_code=503,
                    code='AGENT_TOOL_NOT_PERMITTED',
                    message='The Agent supplied an invalid Evidence history limit.',
                )
            cursor = request.get('cursor')
            if cursor is not None and (not isinstance(cursor, str) or not cursor.strip()):
                raise ApiError(
                    status_code=503,
                    code='AGENT_TOOL_NOT_PERMITTED',
                    message='The Agent supplied an invalid Evidence history cursor.',
                )
        if tool == 'evidence_registry' and request.get('kind') != 'police_report':
            raise ApiError(
                status_code=503,
                code='AGENT_TOOL_NOT_PERMITTED',
                message='The Agent requested an unsupported pending-evidence operation.',
            )


def _session_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message='The session was not found.',
    )


def _claimant_message(
    message: MessageRecord,
    message_actions: list[ClaimantExternalServiceAction] | None = None,
) -> ClaimantMessage:
    return ClaimantMessage(
        message_id=message.message_id,
        actor=message.actor,
        content=message.content,
        evidence_refs=message.evidence_refs,
        in_reply_to=message.in_reply_to,
        client_message_id=message.client_message_id,
        recovery=claimant_recovery_projection(message.recovery_rule_id),
        message_actions=message_actions or [],
        created_at=message.created_at,
    )


def _claimant_decision(
    decision: AgentDecisionRecord,
    *,
    customer_next_step: CustomerNextStep | None = None,
) -> ClaimantDecision:
    return ClaimantDecision(
        decision_id=decision.decision_id,
        action=decision.action,
        action_code=decision.action_code,
        reason_codes=(
            []
            if decision.proposal_source is AgentProposalSource.MODEL_GATEWAY
            else [code for code in decision.reason_codes if code not in INTERNAL_ONLY_REASON_CODES]
        ),
        customer_reason=decision.customer_reason,
        customer_next_step=customer_next_step or decision.customer_next_step,
    )


def _message_turn_response(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    claimant_message: MessageRecord,
    decision: AgentDecisionRecord,
) -> MessageTurnResponse:
    messages = repository.list_messages(
        claim_id,
        claimant_message.session_id,
        principal.subject,
    )
    agent_message = next(
        (
            message
            for message in messages
            if message.actor is ActorType.AGENT
            and message.in_reply_to == claimant_message.message_id
            and message.recovery_rule_id is None
        ),
        None,
    )
    if agent_message is None:
        raise ApiError(
            status_code=500,
            code='INTERNAL_ERROR',
            message='The persisted agent turn could not be restored.',
            retryable=True,
        )
    handoff = (
        repository.get_handoff(claim_id, decision.handoff_id, principal.subject)
        if decision.handoff_id is not None
        else None
    )
    claim = repository.get_claim(claim_id, principal.subject)
    dynamic_form = (
        claimant_dynamic_form_projection(repository, claim) if claim is not None else None
    )
    projected_form_changes = (
        project_claimant_form_fields(
            repository,
            claim,
            decision.form_changes,
        )
        if claim is not None
        else decision.form_changes
    )
    external_service_action = claimant_assessor_action(repository, claim) if claim else None
    next_step = (
        claimant_next_step(repository, claim, external_service_action)
        if claim is not None
        else decision.customer_next_step
    )
    response_revision = claim.revision if claim is not None else decision.resulting_revision
    return MessageTurnResponse(
        claim_id=claim_id,
        session_id=claimant_message.session_id,
        claim_revision=response_revision,
        claimant_message=_claimant_message(claimant_message).model_copy(update={'recovery': None}),
        agent_message=_claimant_message(
            agent_message,
            message_external_actions(repository, claim, agent_message.message_id)
            if claim is not None
            else [],
        ),
        form_changes=[
            FormChange(field_code=field_code, field=field)
            for field_code, field in projected_form_changes.items()
        ],
        contents_item_changes=[
            _claimant_contents_item(item) for item in decision.contents_item_changes
        ],
        decision=_claimant_decision(decision, customer_next_step=next_step),
        handoff=(
            claimant_handoff(handoff)
            if handoff is not None
            and handoff.type is not HandoffType.PROFESSIONAL_REVIEW
            and handoff.support_need is not None
            else None
        ),
        dynamic_form=dynamic_form,
        primary_action=(
            project_claimant_primary_action(
                claim_id=claim_id,
                claim_revision=response_revision,
                next_step=next_step,
                external_service_action=external_service_action,
            )
            if claim is not None
            else None
        ),
    )


def _freeze_message_turn_response(
    repository: PersistenceRepository,
    idempotency: IdempotencyRecord,
    response: MessageTurnResponse,
) -> MessageTurnResponse:
    """Freeze the first safe response after optional external dispatch settles.

    A crash before this point has not delivered a successful response. Replay may
    reconstruct that first response from durable records; after freezing, later
    Claim mutations must never change a same-key response.
    """
    try:
        frozen = repository.freeze_message_response(idempotency, response.model_dump(mode='json'))
    except IdempotencyConflict as error:
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The saved message response belongs to a different attempt.',
        ) from error
    return MessageTurnResponse.model_validate(frozen)


def _message_only_response(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    session_id: str,
    revision: int,
    message: MessageRecord,
    *,
    claim: WorkingClaim | None = None,
) -> MessageTurnResponse:
    claim = claim or repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _session_not_found()
    external_service_action = claimant_assessor_action(repository, claim)
    next_step = claimant_next_step(repository, claim, external_service_action)
    return MessageTurnResponse(
        claim_id=claim_id,
        session_id=session_id,
        claim_revision=revision,
        claimant_message=_claimant_message(message),
        form_changes=[],
        handoff=None,
        decision=None,
        primary_action=project_claimant_primary_action(
            claim_id=claim_id,
            claim_revision=revision,
            next_step=next_step,
            external_service_action=external_service_action,
        ),
    )


def _namespaced_turn_response(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    claim_revision: int,
    claimant_message: MessageRecord,
    agent_message: MessageRecord,
) -> MessageTurnResponse:
    """Build the claimant projection for a Runtime trace without a legacy decision."""
    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _session_not_found()
    external_service_action = claimant_assessor_action(repository, claim)
    next_step = claimant_next_step(repository, claim, external_service_action)
    return MessageTurnResponse(
        claim_id=claim_id,
        session_id=claimant_message.session_id,
        claim_revision=claim_revision,
        claimant_message=_claimant_message(claimant_message),
        agent_message=_claimant_message(
            agent_message,
            message_external_actions(repository, claim, agent_message.message_id),
        ),
        form_changes=[],
        decision=None,
        handoff=None,
        dynamic_form=claimant_dynamic_form_projection(repository, claim),
        primary_action=project_claimant_primary_action(
            claim_id=claim_id,
            claim_revision=claim_revision,
            next_step=next_step,
            external_service_action=external_service_action,
        ),
    )


def _build_form_changes(
    existing_form: dict[str, StructuredFormField],
    proposals: list[ProposedFormChange],
    claimant_message: MessageRecord,
    timestamp: datetime,
    authority_outcome: AuthorityOutcome,
    proposal_source: AgentProposalSource,
    branch_evaluation: BranchEvaluationResult | None = None,
    grounding_source_refs: set[str] | None = None,
    evidence_media_types: dict[str, str] | None = None,
) -> dict[str, StructuredFormField]:
    form_changes: dict[str, StructuredFormField] = {}
    normalised_proposals = list(proposals)
    proposed_codes = {proposal.field_code for proposal in proposals}
    if (
        'vehicle.damage_description' in proposed_codes
        and 'loss.description' not in proposed_codes
        and (
            'loss.description' not in existing_form
            or existing_form['loss.description'].status is not FormStatus.CONFIRMED
        )
    ):
        vehicle_damage = next(
            proposal
            for proposal in proposals
            if proposal.field_code == 'vehicle.damage_description'
        )
        normalised_proposals.append(
            vehicle_damage.model_copy(update={'field_code': 'loss.description'})
        )

    for proposal in normalised_proposals:
        if proposal.relation is AssertionRelation.IRRELEVANT:
            continue
        if proposal.field_code not in REGISTERED_FIELD_CODES:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The Agent proposed an unregistered field.',
            )
        if proposal.source_evidence_id is not None:
            media_type = (evidence_media_types or {}).get(proposal.source_evidence_id)
            expected_source = (
                FormSource.IMAGE
                if media_type is not None and media_type.startswith('image/')
                else FormSource.DOCUMENT
                if media_type == 'application/pdf'
                else None
            )
            if expected_source is None or proposal.source is not expected_source:
                raise ApiError(
                    status_code=500,
                    code='INTERNAL_ERROR',
                    message='The Agent proposed an invalid Evidence source.',
                )
        elif proposal.source in {FormSource.IMAGE, FormSource.DOCUMENT}:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The Agent proposed Evidence-derived data without a source.',
            )
        try:
            validate_registered_field_value(
                proposal.field_code,
                proposal.value,
                status=proposal.status,
            )
        except ValueError as error:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The Agent proposed an invalid registered-field value.',
                details=[ErrorDetail(field=proposal.field_code, reason=str(error))],
            ) from error
        if branch_evaluation is not None:
            selection = next(
                (
                    item
                    for item in branch_evaluation.field_selection
                    if item.field_code == proposal.field_code
                ),
                None,
            )
            if selection is None or selection.selection_state.value in {
                'inactive',
                'system_owned',
            }:
                raise ApiError(
                    status_code=409,
                    code='INVALID_FIELD_BRANCH',
                    message='The Agent proposed a field outside the active form branches.',
                )
        existing_field = existing_form.get(proposal.field_code)
        if (
            existing_field is not None
            and existing_field.status is FormStatus.CONFIRMED
            and proposal.source is not FormSource.CLAIMANT
            and proposal.value == existing_field.value
        ):
            continue
        accepted_status = (
            proposal.status
            if authority_outcome is AuthorityOutcome.AUTHORISED
            and proposal.source is FormSource.CLAIMANT
            else FormStatus.PROPOSED
        )
        resolved = resolve_form_change(
            field_code=proposal.field_code,
            existing=existing_field,
            proposal=proposal,
            source_ref=proposal.source_evidence_id or claimant_message.message_id,
            message_text=str(claimant_message.content.get('text', '')) or None,
            timestamp=timestamp,
            accepted_status=accepted_status,
            updated_by=ActorReference(
                actor_type=ActorType.AGENT,
                actor_id=proposal_source.value,
            ),
        )
        if proposal.source is not FormSource.CLAIMANT and grounding_source_refs:
            assertions = list(resolved.assertions)
            if assertions:
                assertions[-1] = assertions[-1].model_copy(
                    update={
                        'source_refs': list(
                            dict.fromkeys(
                                [*assertions[-1].source_refs, *sorted(grounding_source_refs)]
                            )
                        )
                    }
                )
            resolved = resolved.model_copy(
                update={
                    'source_refs': list(
                        dict.fromkeys([*resolved.source_refs, *sorted(grounding_source_refs)])
                    ),
                    'assertions': assertions,
                }
            )
        form_changes[proposal.field_code] = resolved
    return form_changes


def _build_contents_item_changes(
    claim: WorkingClaim,
    proposal: AgentProposal,
    claimant_message: MessageRecord,
    timestamp: datetime,
    authority_outcome: AuthorityOutcome,
    branch_evaluation: BranchEvaluationResult,
    evidence_media_types: dict[str, str] | None = None,
) -> list[ContentsItem]:
    if not proposal.contents_item_changes or authority_outcome is not AuthorityOutcome.AUTHORISED:
        return []
    contents_available = branch_evaluation.selected_family == 'contents' or (
        'family.contents' in branch_evaluation.candidate_branches
    )
    if not contents_available:
        raise ApiError(
            status_code=409,
            code='INVALID_FIELD_BRANCH',
            message='The Agent proposed a contents item outside the contents claim branch.',
        )
    existing_by_id = {item.item_id: item for item in claim.contents_items}
    existing_by_description = {
        item.description.strip().casefold(): item for item in claim.contents_items
    }
    changes: list[ContentsItem] = []
    for item in proposal.contents_item_changes:
        evidence_source: FormSource | None = None
        if item.source_evidence_id is not None:
            media_type = (evidence_media_types or {}).get(item.source_evidence_id)
            evidence_source = (
                FormSource.IMAGE
                if media_type is not None and media_type.startswith('image/')
                else FormSource.DOCUMENT
                if media_type == 'application/pdf'
                else None
            )
            if evidence_source is None:
                raise ApiError(
                    status_code=500,
                    code='INTERNAL_ERROR',
                    message='The Agent proposed an invalid contents Evidence source.',
                )
        existing = existing_by_id.get(item.item_id or '')
        if item.item_id is not None and existing is None:
            raise ApiError(
                status_code=409,
                code='INVALID_CONTENTS_ITEM_REFERENCE',
                message='The Agent referenced a contents item that is not in this claim.',
            )
        if existing is None:
            existing = existing_by_description.get(item.description.strip().casefold())
        claimant_supplied = bool(
            item.reported_text
            and item.reported_text.casefold()
            in str(claimant_message.content.get('text', '')).casefold()
        )
        contents_item = resolve_contents_item_change(
            existing=existing,
            proposal=item,
            item_id=existing.item_id if existing is not None else new_id('itm'),
            source_ref=item.source_evidence_id or claimant_message.message_id,
            message_text=(
                None
                if item.source_evidence_id is not None
                else str(claimant_message.content.get('text', '')) or None
            ),
            timestamp=timestamp,
            accepted_status=(
                FormStatus.CONFIRMED
                if claimant_supplied and evidence_source is None
                else FormStatus.PROPOSED
            ),
            updated_by=ActorReference(
                actor_type=ActorType.AGENT,
                actor_id=proposal.proposal_source.value,
            ),
        )
        if evidence_source is not None:
            contents_item = contents_item.model_copy(
                update={'source': evidence_source, 'status': FormStatus.PROPOSED}
            )
        elif not claimant_supplied:
            contents_item = contents_item.model_copy(update={'source': FormSource.INFERENCE})
        changes.append(contents_item)
    return changes


def _apply_contents_item_changes(
    existing: list[ContentsItem],
    changes: list[ContentsItem],
) -> list[ContentsItem]:
    changes_by_id = {item.item_id: item for item in changes}
    projected = [changes_by_id.pop(item.item_id, item) for item in existing]
    projected.extend(changes_by_id.values())
    return projected


def _claimant_contents_item(item: ContentsItem) -> ClaimantContentsItem:
    return ClaimantContentsItem(
        item_id=item.item_id,
        description=item.description,
        category=item.category,
        quantity=item.quantity,
        brand=item.brand,
        model=item.model,
        loss_type=item.loss_type,
        ownership=item.ownership,
        estimated_value=item.estimated_value,
        source=item.source,
        source_refs=[ref for ref in item.source_refs if ref.startswith(('msg_', 'evd_'))],
        status=item.status,
        needed_for=item.needed_for,
        resolution_state=item.resolution_state,
        updated_at=item.updated_at,
    )


def _question_fields(proposal: AgentProposal, next_step: CustomerNextStep) -> list[str]:
    values = (
        list(next_step.required_items)
        if next_step.required_items
        else list(proposal.next_action_requirements)
    )
    fields: list[str] = []
    for value in values:
        field_code = value.removeprefix('confirm:')
        if (field_code in REGISTERED_FIELD_CODES or field_code == 'contents.items') and (
            field_code not in fields
        ):
            fields.append(field_code)
    return fields


def _tool_source_refs(tool_results: list[dict[str, object]]) -> set[str]:
    refs: set[str] = set()
    for result in tool_results:
        raw_refs = result.get('source_refs')
        if isinstance(raw_refs, list):
            refs.update(str(ref) for ref in raw_refs)
    return refs


def _grounding_source_refs(tool_results: list[dict[str, object]]) -> set[str]:
    return _tool_source_refs(
        [
            result
            for result in tool_results
            if result.get('tool') in {'knowledge_search', 'policy_history', 'claim_history'}
            and result.get('status') == RetrievalStatus.EVIDENCE_FOUND.value
        ]
    )


def _validate_failed_retrieval_changes(
    proposal: AgentProposal,
    message_text: str,
) -> None:
    failed_results = [
        result
        for result in proposal.tool_results
        if result.get('tool') in {'knowledge_search', 'policy_history', 'claim_history'}
        and result.get('status') != RetrievalStatus.EVIDENCE_FOUND.value
    ]
    if not failed_results:
        return
    unsupported_fields = [
        change.field_code
        for change in proposal.form_changes
        if change.source is not FormSource.CLAIMANT
    ]
    normalized_message = ' '.join(message_text.split()).casefold()
    unsupported_contents = [
        item.description
        for item in proposal.contents_item_changes
        if not item.reported_text
        or ' '.join(item.reported_text.split()).casefold() not in normalized_message
    ]
    if unsupported_fields or unsupported_contents:
        raise ApiError(
            status_code=503,
            code='AGENT_TOOL_NOT_PERMITTED',
            message='The Agent used an unavailable context result as a new Claim fact.',
            retryable=False,
        )


def _validate_evidence_history_action(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    proposal: AgentProposal,
) -> AgentProposal:
    """Do not turn an unavailable history lookup into an Evidence action."""

    history_results = [
        result for result in proposal.tool_results if result.get('tool') == 'evidence.history'
    ]
    if proposal.action_code not in {
        'claim.propose_evidence_reuse',
        'claim.propose_evidence_remove',
    }:
        latest_history = history_results[-1] if history_results else None
        page = latest_history.get('page') if isinstance(latest_history, dict) else None
        if (
            isinstance(page, dict)
            and isinstance(page.get('next_cursor'), str)
            and page['next_cursor']
        ):
            return replace(
                proposal,
                customer_response=(
                    f'{proposal.customer_response} I checked one page of your Evidence history; '
                    'more records are available, so this is not a complete not-found result.'
                ),
            )
        return proposal
    if not history_results or history_results[-1].get('status') != 'succeeded':
        raise ApiError(
            status_code=503,
            code='AGENT_TOOL_NOT_PERMITTED',
            message=(
                'The Agent cannot propose an Evidence action without a successful history lookup.'
            ),
            retryable=False,
        )
    history_items = history_results[-1].get('items', [])
    visible_evidence_ids = (
        {
            item.get('evidence_id')
            for item in history_items
            if isinstance(item, dict) and isinstance(item.get('evidence_id'), str)
        }
        if isinstance(history_items, list)
        else set()
    )
    if proposal.evidence_id not in visible_evidence_ids:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The proposed Evidence item was not present in the authorised history result.',
            retryable=False,
        )
    result = validate_evidence_proposal(
        repository,
        claim,
        action_code=proposal.action_code,
        evidence_id=proposal.evidence_id or '',
        source_claim_id=proposal.source_claim_id,
        removal_scope=proposal.removal_scope,
    )
    if result.get('status') == 'rejected':
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message=(
                'The proposed Evidence action did not satisfy its ownership, state, or input '
                'contract.'
            ),
            retryable=False,
        )
    if result.get('status') == 'unavailable':
        is_draft = result.get('reason') == 'DRAFT_REMOVAL_IS_FRONTEND_OWNED'
        return replace(
            proposal,
            customer_reason=(
                'Draft Evidence removal is controlled by the current upload composer.'
                if is_draft
                else 'Persisted Evidence removal is unavailable under the current retention API.'
            ),
            customer_response=(
                'Select the draft file in the upload composer and remove it before submitting.'
                if is_draft
                else 'I can show this Evidence in your history, but I cannot remove the persisted '
                'record because the governed retention and audit operation is not available.'
            ),
        )
    is_removal = proposal.action_code == 'claim.propose_evidence_remove'
    return replace(
        proposal,
        source_claim_id=(
            str(result['source_claim_id'])
            if isinstance(result.get('source_claim_id'), str)
            else proposal.source_claim_id
        ),
        customer_reason=(
            'The selected Evidence is eligible for a governed removal proposal.'
            if is_removal
            else 'The selected Evidence is eligible for a reuse proposal.'
        ),
        customer_response=(
            (
                f'I found Evidence {proposal.evidence_id} from Claim {proposal.source_claim_id}. '
                'No change has been made. Please confirm whether you want Northwind to remove '
                'it from your Evidence history.'
            )
            if is_removal
            else (
                f'I found Evidence {proposal.evidence_id} from Claim {proposal.source_claim_id}. '
                'It has not been attached or copied. Please confirm whether you want Northwind '
                'to reuse the original Evidence for this Claim.'
            )
        ),
        customer_next_step=CustomerNextStep(
            status='confirm_evidence_remove' if is_removal else 'confirm_evidence_reuse',
            summary=(
                'Confirm whether Northwind may remove the Evidence from your history.'
                if is_removal
                else 'Confirm whether Northwind may reuse the original Evidence for this Claim.'
            ),
            responsible_party=ResponsibleParty.CLAIMANT,
            required_items=[
                'evidence_remove_confirmation' if is_removal else 'evidence_reuse_confirmation'
            ],
        ),
    )


def _apply_question_accounting(
    session: SessionRecord,
    proposal: AgentProposal,
    next_step: CustomerNextStep,
    response_text: str,
    trigger_message_id: str,
    timestamp: datetime,
    during_handoff: bool = False,
) -> tuple[SessionRecord, CustomerNextStep, str]:
    asks_question = proposal.action in {AgentAction.ASK, AgentAction.CLARIFY} or (
        '?' in response_text and bool(_question_fields(proposal, next_step))
    )
    if not asks_question:
        return session, next_step, response_text
    if not during_handoff and session.question_turn_count >= session.question_budget:
        paused_step = CustomerNextStep(
            status='question_budget_reached',
            summary='Your report is saved. Northwind may follow up on the remaining information.',
            responsible_party=ResponsibleParty.CLAIMS_PROFESSIONAL,
            required_items=list(next_step.required_items),
        )
        return (
            session.model_copy(update={'post_session_follow_up_required': True}),
            paused_step,
            'I have saved what you shared. Northwind may follow up on the remaining information.',
        )

    fields = _question_fields(proposal, next_step)
    previously_requested = {
        field_code
        for record in session.question_history
        if not record.during_handoff
        for field_code in record.field_codes
    }
    repeated = (
        not during_handoff
        and bool(fields)
        and all(field_code in previously_requested for field_code in fields)
    )
    question = QuestionRecord(
        question_id=new_id('qst'),
        trigger_message_id=trigger_message_id,
        field_codes=fields,
        purpose=proposal.action.value.lower(),
        repeated=repeated,
        during_handoff=during_handoff,
        asked_at=timestamp,
    )
    return (
        session.model_copy(
            update={
                'question_turn_count': session.question_turn_count + 1,
                'requested_fact_count': session.requested_fact_count + len(fields),
                'repeated_question_count': session.repeated_question_count + int(repeated),
                'question_history': [*session.question_history, question],
            }
        ),
        next_step,
        response_text,
    )


def _policy_search_tool(proposal: AgentProposal) -> dict[str, object] | None:
    return next(
        (
            tool
            for tool in proposal.required_tools
            if tool.get('tool') == 'policy_history' and tool.get('operation') == 'search_policy'
        ),
        None,
    )


def _execute_policy_search(
    repository: PersistenceRepository,
    adapter: PolicyHistoryAdapter,
    claim_id: str,
    customer_id: str,
    proposal: AgentProposal,
) -> tuple[PolicyRetrievalRecord | None, dict[str, object]] | None:
    tool = _policy_search_tool(proposal)
    if tool is None:
        return None
    policy_reference = str(tool.get('policy_reference') or '')
    if not policy_reference:
        return None
    existing = next(
        (
            record
            for record in reversed(repository.list_retrieval_records(claim_id, customer_id))
            if isinstance(record, PolicyRetrievalRecord)
            and record.facts.policy_reference == policy_reference
        ),
        None,
    )
    if existing is not None:
        return (
            existing,
            {
                'tool': 'policy_history',
                'status': (
                    RetrievalStatus.AMBIGUOUS.value
                    if existing.uncertainty
                    else RetrievalStatus.EVIDENCE_FOUND.value
                ),
                'source_refs': [existing.retrieval_id],
                'limitations': [],
            },
        )
    result = search_policy(
        repository,
        adapter,
        PolicySearchRequest(
            claim_id=claim_id,
            policy_reference=policy_reference,
            question=str(tool.get('question') or '') or None,
        ),
    )
    record = next(
        (
            record
            for record in repository.list_retrieval_records(claim_id, customer_id)
            if isinstance(record, PolicyRetrievalRecord) and record.retrieval_id == result.result_id
        ),
        None,
    )
    return (
        record,
        {
            'tool': 'policy_history',
            'status': result.status.value,
            'source_refs': [record.retrieval_id] if record is not None else [],
            'limitations': list(result.limitations),
        },
    )


def _policy_context_for_turn(
    repository: PersistenceRepository,
    adapter: PolicyHistoryAdapter,
    claim: WorkingClaim,
    customer_id: str,
    question: str,
    max_tokens: int,
) -> dict[str, object]:
    """Resolve policy facts from the current Claim's authoritative reference."""

    policy_field = claim.form.get('policy.policy_number')
    policy_reference = str(policy_field.value).strip() if policy_field is not None else ''
    if not policy_reference:
        return {
            'status': RetrievalStatus.NO_EVIDENCE.value,
            'source_refs': [],
            'facts': None,
            'uncertainty': [],
            'limitations': ['The current Claim has no confirmed policy reference.'],
        }
    existing = next(
        (
            record
            for record in reversed(repository.list_retrieval_records(claim.claim_id, customer_id))
            if isinstance(record, PolicyRetrievalRecord)
            and record.facts.policy_reference == policy_reference
        ),
        None,
    )
    if existing is not None:
        return {
            'status': (
                RetrievalStatus.AMBIGUOUS.value
                if existing.uncertainty
                else RetrievalStatus.EVIDENCE_FOUND.value
            ),
            'source_refs': [existing.retrieval_id],
            'facts': existing.facts.model_dump(mode='json'),
            'uncertainty': [item.model_dump(mode='json') for item in existing.uncertainty],
            'limitations': [],
        }
    result = search_policy(
        repository,
        adapter,
        PolicySearchRequest(
            claim_id=claim.claim_id,
            policy_reference=policy_reference,
            question=question[:500] or None,
        ),
    )
    # The projection is already bounded; retain the argument so every loader
    # shares the same turn-scoped resolver contract.
    _ = max_tokens
    return {
        'status': result.status.value,
        'source_refs': [result.result_id] if result.facts is not None else [],
        'facts': result.facts.model_dump(mode='json') if result.facts is not None else None,
        'uncertainty': [item.model_dump(mode='json') for item in result.uncertainty],
        'limitations': list(result.limitations),
    }


def _claim_history_context_for_turn(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    customer_id: str,
    max_tokens: int,
) -> dict[str, object]:
    """Return a bounded claimant-owned cross-Claim projection without internal fields."""

    max_items = max(1, min(10, max_tokens // 80))
    claims = sorted(
        (
            item
            for item in repository.list_claims_for_customer(customer_id)
            if item.claim_id != claim.claim_id
        ),
        key=lambda item: (item.updated_at, item.claim_id),
        reverse=True,
    )[:max_items]
    return {
        'status': (
            RetrievalStatus.EVIDENCE_FOUND.value if claims else RetrievalStatus.NO_EVIDENCE.value
        ),
        'claims': [
            {
                'claim_id': item.claim_id,
                'revision': item.revision,
                'product_family': item.incident_type,
                'workflow_state': item.claim_state.workflow_state.value,
                'next_action': item.claim_state.next_action.value,
                'created_at': item.created_at.isoformat(),
                'updated_at': item.updated_at.isoformat(),
            }
            for item in claims
        ],
        'source_refs': [f'claim:{item.claim_id}:revision:{item.revision}' for item in claims],
        'limitations': (
            [] if claims else ['No other Claim is available in the authenticated customer scope.']
        ),
    }


def _claim_history_search_tool(proposal: AgentProposal) -> dict[str, object] | None:
    return next(
        (
            tool
            for tool in proposal.required_tools
            if tool.get('tool') in {'policy_history', 'claim_history'}
            and tool.get('operation') in {'search_claim_history', 'lookup'}
        ),
        None,
    )


def _execute_claim_history_search(
    repository: PersistenceRepository,
    adapter: PolicyHistoryAdapter,
    claim_id: str,
    customer_id: str,
    proposal: AgentProposal,
) -> tuple[ClaimHistoryRetrievalRecord | None, dict[str, object]] | None:
    tool = _claim_history_search_tool(proposal)
    if tool is None:
        return None
    raw_reference = tool.get('history_reference')
    if not isinstance(raw_reference, str):
        return None
    history_reference = raw_reference.strip()
    if not history_reference:
        return None
    if 'limit' not in tool:
        limit = 10
    else:
        raw_limit = tool['limit']
        if not isinstance(raw_limit, int) or isinstance(raw_limit, bool):
            return None
        limit = raw_limit
    if not 1 <= limit <= 50:
        return None
    existing = next(
        (
            record
            for record in reversed(repository.list_retrieval_records(claim_id, customer_id))
            if isinstance(record, ClaimHistoryRetrievalRecord)
            and record.facts.history_reference == history_reference
        ),
        None,
    )
    if existing is not None:
        return (
            existing,
            {
                'tool': 'claim_history',
                'status': (
                    RetrievalStatus.AMBIGUOUS.value
                    if existing.uncertainty
                    else RetrievalStatus.EVIDENCE_FOUND.value
                ),
                'source_refs': [existing.retrieval_id],
                'limitations': [],
            },
        )
    result = search_claim_history(
        repository,
        adapter,
        ClaimHistorySearchRequest(
            claim_id=claim_id,
            history_reference=history_reference,
            purpose='relevant_history_review',
            limit=limit,
        ),
    )
    record = next(
        (
            record
            for record in repository.list_retrieval_records(claim_id, customer_id)
            if isinstance(record, ClaimHistoryRetrievalRecord)
            and record.retrieval_id == result.result_id
        ),
        None,
    )
    return (
        record,
        {
            'tool': 'claim_history',
            'status': result.status.value,
            'source_refs': [record.retrieval_id] if record is not None else [],
            'limitations': list(result.limitations),
        },
    )


def _execute_evidence_history_search(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    proposal: AgentProposal,
) -> tuple[None, dict[str, object]] | None:
    tool = next(
        (
            item
            for item in proposal.required_tools
            if item.get('tool') == 'evidence.history' and item.get('operation') == 'list'
        ),
        None,
    )
    if tool is None:
        return None
    limit = tool.get('limit', 25)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
        return None
    cursor = tool.get('cursor')
    if cursor is not None and (not isinstance(cursor, str) or not cursor.strip()):
        return None
    try:
        result = read_evidence_history_for_runtime(
            repository,
            claim,
            {'limit': limit, **({'cursor': cursor} if cursor is not None else {})},
        )
    except (TypeError, ValueError):
        return None
    return None, result


def _professional_review_requested(proposal: AgentProposal) -> bool:
    return any(
        tool.get('tool') == 'professional_review'
        and tool.get('operation') == 'create_policy_review'
        for tool in proposal.required_tools
    )


def _pending_evidence_for_proposal(
    claim_id: str,
    proposal: object,
    claimant_message: MessageRecord,
    timestamp: datetime,
) -> EvidenceRecord | None:
    required_tools = getattr(proposal, 'required_tools', [])
    pending = next(
        (
            tool
            for tool in required_tools
            if tool.get('tool') == 'evidence_registry'
            and tool.get('operation') == 'record_pending_generation'
        ),
        None,
    )
    if pending is None:
        return None
    return EvidenceRecord(
        evidence_id=new_id('evd'),
        claim_id=claim_id,
        kind=str(pending.get('kind') or 'document'),
        status=EvidenceStatus.PENDING,
        file_status=EvidenceFileStatus.NOT_AVAILABLE,
        source=EvidenceSource.CLAIMANT,
        related_fields=['authorities.police_report_reference'],
        needed_for=['later_action'],
        provenance={'reported_in_message_id': claimant_message.message_id},
        claimant_note=str(claimant_message.content.get('text') or ''),
        wait_type='claimant',
        responsible_party='claimant',
        context_summary='The document is expected later and is needed for a later action.',
        created_at=timestamp,
        updated_at=timestamp,
    )


def _submit_namespaced_runtime_turn(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    session_id: str,
    claim: WorkingClaim,
    session: SessionRecord,
    claimant_message: MessageRecord,
    proposal: AgentProposal,
    authority: object,
    runtime_policy: object,
    branch_evaluator: BranchRuleEvaluator,
    previous_evaluation: BranchEvaluationRecord | None,
    message_text: str,
    route: str,
    key: str,
    fingerprint: str,
    expected_revision: int,
) -> MessageTurnResponse:
    """Persist the first namespaced, read-only Runtime turn.

    The target Runtime path deliberately does not create an ``AgentDecisionRecord`` or
    advance Claim revision. It records the conversation and Runtime trace while only
    updating Session activity, so ``claim.read`` remains observational.
    """

    runtime_trace: RuntimeTraceRecord | None = proposal.runtime_trace
    if runtime_trace is None or runtime_trace.status != 'succeeded':
        raise ApiError(
            status_code=503,
            code='AGENT_RUNTIME_UNAVAILABLE',
            message='The namespaced Agent Runtime did not produce a persistable result.',
            retryable=True,
        )
    timestamp = now_utc()
    updated_session = session.model_copy(
        update={'last_active_at': timestamp, 'context_revision': claim.revision}
    )
    agent_message = MessageRecord(
        message_id=new_id('msg'),
        claim_id=claim_id,
        session_id=session_id,
        actor=ActorType.AGENT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': proposal.customer_response},
        in_reply_to=claimant_message.message_id,
        created_at=timestamp,
    )
    response = _namespaced_turn_response(
        repository,
        principal,
        claim_id,
        claim.revision,
        claimant_message,
        agent_message,
    )
    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=session_id,
        message_id=claimant_message.message_id,
        agent_message_id=agent_message.message_id,
        runtime_trace_id=runtime_trace.trace_id,
        response_payload=response.model_dump(mode='json'),
    )
    try:
        repository.save_runtime_turn(
            claim,
            expected_revision,
            updated_session,
            claimant_message,
            agent_message,
            runtime_trace,
            idempotency,
        )
    except RevisionConflict as conflict:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=conflict.current_revision,
        ) from conflict
    except IdempotencyConflict as conflict:
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The message turn was already accepted with different retry data.',
        ) from conflict
    return response


def _live_mutation_command(
    *,
    claim: WorkingClaim,
    claimant_message: MessageRecord,
    idempotency_key: str,
    form_changes: dict[str, StructuredFormField],
    contents_item_changes: list[ContentsItem],
    handoff: HandoffRecord | None,
    pending_evidence: EvidenceRecord | None,
    runtime_policy: RuntimeAgentPolicySnapshot | None,
) -> ClaimContextCommand | None:
    action_code: str | None = None
    payload: dict[str, object]
    if handoff is not None:
        action_code = 'human.create_handoff'
        payload = {
            'claim_id': claim.claim_id,
            'reason_codes': list(handoff.reason_codes),
            'handoff_packet': handoff.model_dump(mode='json'),
            'expected_revision': claim.revision,
        }
    elif pending_evidence is not None:
        action_code = 'claim.register_evidence'
        payload = {
            'claim_id': claim.claim_id,
            'evidence': pending_evidence.model_dump(mode='json'),
            'expected_revision': claim.revision,
        }
    elif form_changes or contents_item_changes:
        action_code = 'claim.apply_fact_patch'
        payload = {
            'claim_id': claim.claim_id,
            'fact_patches': [
                *(
                    {
                        'field_code': field_code,
                        'field': field.model_dump(mode='json'),
                    }
                    for field_code, field in sorted(form_changes.items())
                ),
                *(
                    {
                        'field_code': 'contents.items',
                        'item': item.model_dump(mode='json'),
                    }
                    for item in contents_item_changes
                ),
            ],
            'expected_revision': claim.revision,
        }
    else:
        return None

    contract = action_contract(action_code)
    tool_policy = runtime_policy.tool_policy if runtime_policy is not None else None
    allowed_action_codes = tool_policy.allowed_action_codes if tool_policy is not None else None
    allowed_tool_names = tool_policy.allowed_tool_names if tool_policy is not None else None
    authority_reference = f'claimant-message:{claimant_message.message_id}'
    if handoff is not None and 'EXPLICIT_SAFETY_SIGNAL' in handoff.reason_codes:
        authority_reference = 'published-rule:BR-SAFETY-001'
    return build_claim_context_command(
        action_code,
        payload,
        proposer_role=ActionActorRole.RUNTIME,
        approved_authority=contract.authority_requirement,
        authority_reference=authority_reference,
        workflow_state=claim.claim_state.workflow_state,
        expected_revision=claim.revision,
        idempotency_key=idempotency_key,
        allowed_action_codes=allowed_action_codes,
        allowed_tools=allowed_tool_names,
    )


_Params = ParamSpec('_Params')
_Result = TypeVar('_Result')


def _settle_accepted_error(function: Callable[_Params, _Result]) -> Callable[_Params, _Result]:
    """Record the terminal API outcome of an accepted attempt, then re-raise it.

    This never retries or turns an invalid proposal into a successful response.
    In-flight HTTP replay is excluded so another request cannot finish its owner.
    """
    signature = inspect.signature(function)

    @wraps(function)
    def call(*args: _Params.args, **kwargs: _Params.kwargs) -> _Result:
        try:
            return function(*args, **kwargs)
        except ApiError as error:
            if error.code == 'TURN_IN_PROGRESS':
                raise
            arguments = signature.bind(*args, **kwargs).arguments
            repository = arguments['repository']
            principal = arguments['principal']
            claim_id, session_id = arguments['claim_id'], arguments['session_id']
            key = arguments.get('idempotency_key')
            route = f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'
            saved = repository.find_idempotency(principal.subject, route, key) if key else None
            if (
                saved is not None
                and saved.response_payload is None
                and saved.decision_id is None
                and saved.request_fingerprint
                == request_fingerprint(arguments['payload'].model_dump(mode='json'))
                and saved.message_id is not None
            ):
                message = repository.get_message(
                    claim_id, session_id, saved.message_id, principal.subject
                )
                if message is not None:
                    repository.save_message_recovery(
                        message,
                        replace(
                            saved,
                            response_status=error.status_code,
                            response_payload={
                                'code': error.code,
                                'message': error.message,
                                'details': [item.model_dump() for item in error.details]
                                if error.details
                                else None,
                                'retryable': error.retryable,
                                'current_revision': error.current_revision,
                            },
                        ),
                    )
            raise

    return call


@_settle_accepted_error
def submit_message(
    repository: PersistenceRepository,
    agent: AgentTurnProvider,
    policy_history_adapter: PolicyHistoryAdapter,
    principal: Principal,
    claim_id: str,
    session_id: str,
    payload: CreateMessageRequest,
    idempotency_key: str | None,
    if_match: str | None,
    runtime_agent_policy_resolver: RuntimeAgentPolicyResolver | None = None,
    action_dispatcher: ClaimantRuntimeActionDispatcher | None = None,
    evidence_storage: EvidenceStorage | None = None,
    assessor_adapter: AssessorServiceAdapter | None = None,
    assessor_entry: ExternalServiceEntryDecision | None = None,
    external_capability_dispatcher: ExternalCapabilityDispatcher | None = None,
    progress_reporter: AgentTurnProgressReporter | None = None,
) -> MessageTurnResponse:
    live_dispatcher = action_dispatcher or ClaimantRuntimeActionDispatcher()
    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    existing_idempotency = repository.find_idempotency(principal.subject, route, key)
    if existing_idempotency is not None:
        if existing_idempotency.request_fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused with a different request.',
            )
        if existing_idempotency.response_payload is not None:
            if (
                existing_idempotency.response_status is not None
                and existing_idempotency.response_status >= 400
            ):
                stored_error = dict(existing_idempotency.response_payload)
                stored_error['details'] = (
                    [ErrorDetail.model_validate(item) for item in stored_error['details']]
                    if stored_error.get('details')
                    else None
                )
                raise ApiError(status_code=existing_idempotency.response_status, **stored_error)
            return MessageTurnResponse.model_validate(existing_idempotency.response_payload)
        if existing_idempotency.message_id is None or existing_idempotency.decision_id is None:
            raise ApiError(
                status_code=409,
                code='TURN_IN_PROGRESS',
                message=(
                    'This message is already accepted and its response is still being prepared.'
                ),
                retryable=True,
            )
        claimant_message = repository.get_message(
            claim_id,
            session_id,
            existing_idempotency.message_id,
            principal.subject,
        )
        decision = repository.get_agent_decision(
            claim_id,
            existing_idempotency.decision_id,
            principal.subject,
        )
        if claimant_message is None or decision is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The idempotent message turn could not be restored.',
                retryable=True,
            )
        return _freeze_message_turn_response(
            repository,
            existing_idempotency,
            _message_turn_response(repository, principal, claim_id, claimant_message, decision),
        )

    existing_client_message = repository.find_message_by_client_id(
        claim_id,
        payload.client_message_id,
        principal.subject,
    )
    failed_checkpoint = (
        repository.find_message_checkpoint(
            claim_id, existing_client_message.message_id, principal.subject
        )
        if existing_client_message is not None
        else None
    )
    retrying_saved_message = (
        existing_client_message is not None
        and (
            existing_client_message.recovery_rule_id is not None
            or (failed_checkpoint is not None and (failed_checkpoint.response_status or 0) >= 400)
        )
        and repository.find_agent_decision_for_trigger(
            claim_id, existing_client_message.message_id, principal.subject
        )
        is None
    )
    if existing_client_message is not None and not retrying_saved_message:
        if existing_client_message.session_id != session_id:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The client_message_id belongs to a different session.',
            )
        expected_content = (
            payload.content.model_dump(mode='json')
            if payload.content is not None
            else {'type': 'evidence_reference'}
        )
        if (
            existing_client_message.content == expected_content
            and existing_client_message.evidence_refs == payload.evidence_refs
        ):
            decision = repository.find_agent_decision_for_trigger(
                claim_id,
                existing_client_message.message_id,
                principal.subject,
            )
            if decision is None:
                runtime_trace = repository.find_runtime_trace_for_trigger(
                    claim_id,
                    existing_client_message.message_id,
                    principal.subject,
                )
                if runtime_trace is not None:
                    agent_message = next(
                        (
                            message
                            for message in repository.list_messages(
                                claim_id,
                                session_id,
                                principal.subject,
                            )
                            if message.actor is ActorType.AGENT
                            and message.recovery_rule_id is None
                            and message.in_reply_to == existing_client_message.message_id
                        ),
                        None,
                    )
                    if agent_message is None:
                        raise ApiError(
                            status_code=500,
                            code='INTERNAL_ERROR',
                            message='The Runtime message turn could not be restored.',
                            retryable=True,
                        )
                    claim = repository.get_claim(claim_id, principal.subject)
                    if claim is None:
                        raise _session_not_found()
                    return _namespaced_turn_response(
                        repository,
                        principal,
                        claim_id,
                        claim.revision,
                        existing_client_message,
                        agent_message,
                    )
                claim = repository.get_claim(claim_id, principal.subject)
                if claim is not None:
                    return _message_only_response(
                        repository,
                        principal,
                        claim_id,
                        session_id,
                        claim.revision,
                        existing_client_message,
                    )
                raise _session_not_found()
            return _message_turn_response(
                repository,
                principal,
                claim_id,
                existing_client_message,
                decision,
            )
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The client_message_id has already been used for this claim.',
        )

    claim = repository.get_claim(claim_id, principal.subject)
    session = repository.get_session(claim_id, session_id, principal.subject)
    if claim is None or session is None:
        raise _session_not_found()
    pending_confirmation_item = max(
        (
            item
            for item in repository.list_runtime_work_items(claim_id, principal.subject)
            if item.kind == 'confirmation'
            and item.status == 'open'
            and item.confirmation_request is not None
        ),
        key=lambda item: item.confirmation_request.claim_revision
        if item.confirmation_request
        else 0,
        default=None,
    )
    confirmation_revision_before_message = claim.revision
    original_checkpoint = (
        repository.find_message_checkpoint(
            claim_id, existing_client_message.message_id, principal.subject
        )
        if retrying_saved_message and existing_client_message is not None
        else None
    )
    if retrying_saved_message:
        expected_content = (
            payload.content.model_dump(mode='json')
            if payload.content is not None
            else {'type': 'evidence_reference'}
        )
        if (
            existing_client_message is None
            or original_checkpoint is None
            or existing_client_message.session_id != session_id
            or existing_client_message.content != expected_content
            or existing_client_message.evidence_refs != payload.evidence_refs
        ):
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='Retry must refer to the saved message and its original content.',
            )
        confirmation_revision_before_message = cast(
            int, original_checkpoint.revision_before_message
        )
        pending_confirmation_item = (
            RuntimeWorkItemRecord.model_validate(original_checkpoint.confirmation_checkpoint)
            if original_checkpoint.confirmation_checkpoint
            else None
        )
        if claim.revision != (original_checkpoint.revision_before_message or 0) + 1:
            # A retry reuses the original observation, but it cannot revive a
            # displayed confirmation after another request changed the Claim.
            pending_confirmation_item = None
    if session.status.value != 'active':
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='Messages can only be submitted to an active session.',
        )
    if (
        payload.model_profile_id is not None
        and payload.model_profile_id != session.model_profile_id
    ):
        # The API boundary has already validated this profile against the published
        # catalog. The selected profile is part of this turn's durable provenance;
        # save_agent_turn persists it with the Claim mutation below.
        session = session.model_copy(update={'model_profile_id': payload.model_profile_id})
    if claim.active_session_id != session_id:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='Messages can only be submitted to the claim active session.',
        )
    active_handoff = next(
        (
            item
            for item in reversed(repository.list_handoffs(claim_id, principal.subject))
            if item.status.value not in {'resolved', 'cancelled'}
        ),
        None,
    )
    handoff_open = active_handoff is not None
    # Handoff ownership changes responsibility, but it does not make the
    # conversation silent.  The turn below must still reach the Agent path so
    # later claimant messages can be recorded and answered.
    message_text = payload.content.text if payload.content is not None else ''
    if claim.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )
    selected_evidence: list[EvidenceRecord] = []
    invalid_evidence_refs: list[ErrorDetail] = []
    seen_evidence_refs: set[str] = set()
    for evidence_id in payload.evidence_refs:
        if evidence_id in seen_evidence_refs:
            invalid_evidence_refs.append(
                ErrorDetail(field='evidence_refs', reason=f'Duplicate evidence: {evidence_id}.')
            )
            continue
        seen_evidence_refs.add(evidence_id)
        evidence = repository.get_evidence(claim_id, evidence_id, principal.subject)
        if evidence is None:
            invalid_evidence_refs.append(
                ErrorDetail(field='evidence_refs', reason=f'Unknown evidence: {evidence_id}.')
            )
            continue
        if (
            evidence.file_status not in _MODEL_EVIDENCE_FILE_STATES
            or evidence.media_type not in _MODEL_EVIDENCE_MEDIA_TYPES
            or default_evidence_visibility(evidence.source) is MessageVisibility.INTERNAL_ONLY
            or evidence.status
            in {
                EvidenceStatus.INVALID,
                EvidenceStatus.EXPIRED,
                EvidenceStatus.SUPERSEDED,
                EvidenceStatus.UNAVAILABLE,
                EvidenceStatus.MISSING,
            }
        ):
            invalid_evidence_refs.append(
                ErrorDetail(
                    field='evidence_refs',
                    reason=f'Evidence is not available for model processing: {evidence_id}.',
                )
            )
            continue
        selected_evidence.append(evidence)
    if invalid_evidence_refs:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='One or more evidence references are invalid.',
            details=invalid_evidence_refs,
        )

    turn_evidence = tuple(
        AgentEvidenceReference(
            evidence_id=evidence.evidence_id,
            media_type=evidence.media_type or '',
        )
        for evidence in selected_evidence
    )
    evidence_resolver = (
        _TurnEvidenceResolver(
            repository=repository,
            storage=evidence_storage,
            claim_id=claim_id,
            customer_id=principal.subject,
            allowed_media_types={item.evidence_id: item.media_type for item in turn_evidence},
        )
        if turn_evidence and evidence_storage is not None
        else None
    )

    timestamp = now_utc()
    claimant_message = MessageRecord(
        message_id=new_id('msg'),
        claim_id=claim_id,
        session_id=session_id,
        client_message_id=payload.client_message_id,
        actor=ActorType.CLAIMANT,
        visibility=MessageVisibility.SHARED if handoff_open else MessageVisibility.CLAIMANT_VISIBLE,
        content=(
            payload.content.model_dump(mode='json')
            if payload.content is not None
            else {'type': 'evidence_reference'}
        ),
        evidence_refs=payload.evidence_refs,
        created_at=timestamp,
    )
    checkpoint_idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=session_id,
        message_id=(
            existing_client_message.message_id
            if retrying_saved_message and existing_client_message
            else claimant_message.message_id
        ),
        revision_before_message=confirmation_revision_before_message,
        confirmation_checkpoint=(
            pending_confirmation_item.model_dump(mode='json') if pending_confirmation_item else None
        ),
        inbound_checkpoint=not retrying_saved_message,
    )
    if retrying_saved_message and existing_client_message is not None:
        claimant_message = existing_client_message
        repository.save_idempotency(checkpoint_idempotency)
    else:
        claim = claim.model_copy(
            update={'revision': expected_revision + 1, 'updated_at': timestamp}
        )
        session = session.model_copy(
            update={'context_revision': claim.revision, 'last_active_at': timestamp}
        )
        try:
            repository.save_message_mutation(
                claim, expected_revision, session, claimant_message, checkpoint_idempotency
            )
        except RevisionConflict as conflict:
            raise ApiError(
                status_code=409,
                code='REVISION_CONFLICT',
                message='The claim changed after this page was loaded.',
                retryable=True,
                current_revision=conflict.current_revision,
            ) from conflict
        except IdempotencyConflict as conflict:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The message was already accepted.',
            ) from conflict
    # Result persistence is a second CAS boundary. It must reject a mutation
    # performed by another request while the provider was producing its reply.
    expected_revision = claim.revision
    safety_interrupt = detect_safety_interrupt(
        AgentTurnContext(
            claim=claim,
            session_id=session_id,
            trigger_message_id=claimant_message.message_id,
            message_text=message_text,
            evidence_refs=payload.evidence_refs,
            model_profile_id=session.model_profile_id,
        )
    )
    preprovider_handoff = None
    if safety_interrupt is not None:
        claim, preprovider_handoff = commit_detected_handoff(
            repository, principal, claim, claimant_message, safety_interrupt
        )
        expected_revision = claim.revision
        session = session.model_copy(update={'context_revision': claim.revision})
        handoff_open = True
    if progress_reporter is not None:
        progress_reporter.accepted()
        progress_reporter.emit(AgentTurnProgressStage.CONTEXT_LOADING, 'claim.context')
    try:
        runtime_policy = (
            runtime_agent_policy_resolver.resolve_for_turn()
            if runtime_agent_policy_resolver is not None
            else None
        )
    except RuntimeConfigurationResolutionError as error:
        raise ApiError(
            status_code=503,
            code='AGENT_RUNTIME_CONFIGURATION_UNAVAILABLE',
            message='The active Agent runtime configuration cannot be loaded safely.',
            retryable=False,
        ) from error
    branch_evaluator = (
        runtime_policy.branch_evaluator() if runtime_policy else BranchRuleEvaluator()
    )
    previous_evaluation = latest_applied_branch_evaluation(repository, claim)
    branch_evaluation = branch_evaluator.evaluate(
        claim,
        latest_message=(payload.content.text if payload.content is not None else None),
        trigger_source_refs=[claimant_message.message_id],
        current_action=claim.claim_state.next_action,
        recomputation_reason='claimant_message',
        previous_evaluation=previous_evaluation,
    )
    turn_family_resolution = resolve_turn_family(
        claim,
        branch_evaluation,
        payload.content.text if payload.content is not None else None,
    )
    conversation_messages = tuple(
        message
        for message in sorted(
            repository.list_recent_messages(claim_id, session_id, principal.subject, 14),
            key=lambda item: (item.created_at, item.message_id),
        )
        if message.visibility is not MessageVisibility.INTERNAL_ONLY
        and message.message_id != claimant_message.message_id
    )
    trigger_message_id = claimant_message.message_id

    def load_older_messages(limit: int) -> tuple[MessageRecord, ...]:
        visible = [
            message
            for message in repository.list_messages(
                claim_id,
                session_id,
                principal.subject,
            )
            if message.visibility is not MessageVisibility.INTERNAL_ONLY
            and message.message_id != trigger_message_id
        ]
        return tuple(visible[:-4][-limit:])

    rolling_summary = repository.get_latest_conversation_summary(
        claim_id,
        session_id,
        principal.subject,
    )
    persisted_review_signals = repository.list_review_signals(claim_id, principal.subject)
    try:
        external_services = build_agent_external_lifecycle_context(
            repository,
            claim_id,
            claim.assessor_routing,
            turn_family_resolution.product_family,
        )
    except ExternalLifecycleContextError as error:
        external_services = ()
        logger.warning(
            'external_lifecycle_context_unavailable',
            extra={
                'claim_id': claim_id,
                'retryable': error.retryable,
                'component': 'external_service_eligibility',
            },
        )
    available_external_ids = eligible_service_ids(
        repository,
        claim,
        turn_family_resolution.product_family,
        tuple(
            item
            for item in repository.list_messages(claim_id, session_id, principal.subject)
            if item.message_id != claimant_message.message_id
        ),
        current_text=message_text,
        lifecycle=external_services,
    )
    selected_external_service_intents = (
        []
        if handoff_open
        or (
            runtime_policy is not None
            and runtime_policy.instruction.prompt_version == 'northwind-fnol-claimant-v8'
        )
        else select_registered_service_intents(
            payload.content.text if payload.content is not None else None,
            product_family=turn_family_resolution.product_family,
            available_service_ids=set(available_external_ids),
        )
    )
    agent_context = AgentTurnContext(
        claim=claim,
        session_id=session_id,
        model_profile_id=session.model_profile_id,
        trigger_message_id=claimant_message.message_id,
        message_text=payload.content.text if payload.content is not None else None,
        evidence_refs=payload.evidence_refs,
        evidence=turn_evidence,
        evidence_resolver=evidence_resolver,
        professional_review_required=any(
            signal.code == 'POLICY_RETRIEVAL_UNCERTAINTY' for signal in persisted_review_signals
        ),
        branch_evaluation=branch_evaluation,
        turn_family_resolution=turn_family_resolution,
        selected_external_service_ids=tuple(
            item['service_identity'] for item in selected_external_service_intents
        ),
        runtime_configuration_snapshot=(
            runtime_policy.runtime_snapshot if runtime_policy is not None else None
        ),
        runtime_policy=runtime_policy,
        provenance_messages=tuple(
            provenance_messages_for_fields(
                repository,
                claim_id=claim_id,
                customer_id=principal.subject,
                fields=claim.form.values(),
            )
        ),
        conversation_messages=conversation_messages,
        older_message_loader=load_older_messages,
        policy_context_loader=lambda max_tokens: _policy_context_for_turn(
            repository,
            policy_history_adapter,
            claim,
            principal.subject,
            payload.content.text if payload.content is not None else '',
            max_tokens,
        ),
        claim_history_context_loader=lambda max_tokens: _claim_history_context_for_turn(
            repository,
            claim,
            principal.subject,
            max_tokens,
        ),
        evidence_history_context_loader=lambda max_tokens: read_evidence_history_for_runtime(
            repository,
            claim,
            {'limit': max(1, min(25, max_tokens // 40))},
        ),
        progress_reporter=(progress_reporter.emit if progress_reporter is not None else None),
        rolling_summary=rolling_summary,
        external_services=() if handoff_open else external_services,
        eligible_service_ids=frozenset() if handoff_open else frozenset(available_external_ids),
        open_handoffs=tuple(
            item
            for item in repository.list_handoffs(claim_id, principal.subject)
            if item.status.value not in {'resolved', 'cancelled'}
        ),
    )
    agent_context = replace(agent_context, safety_interrupt=safety_interrupt)
    turn_route = route_turn(agent_context)

    def recover_model_failure(model_error: ModelGatewayError) -> MessageTurnResponse:
        nonlocal claimant_message
        # Preserve the claimant's accepted input and revision when the provider
        # fails before any Claim mutation.  The existing message entrypoint is
        # the recovery boundary; no retry endpoint or duplicate inbound record
        # is introduced here.
        recovery_claim = repository.get_claim(claim_id, principal.subject) or claim
        recovery_rule = classify_recovery(
            RecoveryTrigger(source='model', outcome_code=model_error.code.value)
        )
        claimant_message = cast(MessageRecord, claimant_message).model_copy(
            update={'recovery_rule_id': recovery_rule.rule_id}
        )
        recovery_response = _message_only_response(
            repository,
            principal,
            claim_id,
            session_id,
            recovery_claim.revision,
            claimant_message,
            claim=recovery_claim,
        )
        recovery_response = recovery_response.model_copy(
            update={
                'recovery': ClaimantTurnRecovery(
                    rule_id=recovery_rule.rule_id,
                    continuation=recovery_rule.continuation,
                    claimant_projection=recovery_rule.claimant_projection,
                    resume_triggers=sorted(recovery_rule.resume_triggers),
                    resume_entrypoint=recovery_rule.resume_entrypoint,
                )
            }
        )
        recovery_agent_message = None
        if safety_interrupt is not None and preprovider_handoff is not None:
            notice = compose_reply(
                safety_interrupt,
                (),
                'Northwind support has been notified and your report has been saved.',
                None,
            )
            recovery_agent_message = MessageRecord(
                message_id=new_id('msg'),
                claim_id=claim_id,
                session_id=session_id,
                actor=ActorType.AGENT,
                visibility=MessageVisibility.SHARED,
                content={'type': 'text', 'text': notice},
                in_reply_to=claimant_message.message_id,
                recovery_rule_id=recovery_rule.rule_id,
                created_at=now_utc(),
            )
            recovery_response = recovery_response.model_copy(
                update={
                    'agent_message': _claimant_message(recovery_agent_message),
                    'handoff': claimant_handoff(preprovider_handoff),
                    'recovery': recovery_response.recovery.model_copy(
                        update={'claimant_projection': notice}
                    )
                    if recovery_response.recovery
                    else None,
                }
            )
        recovery_idempotency = IdempotencyRecord(
            actor_id=principal.subject,
            route=route,
            key=key,
            request_fingerprint=fingerprint,
            claim_id=claim_id,
            session_id=session_id,
            message_id=claimant_message.message_id,
            agent_message_id=recovery_agent_message.message_id if recovery_agent_message else None,
            response_payload=recovery_response.model_dump(mode='json'),
            revision_before_message=confirmation_revision_before_message,
            confirmation_checkpoint=checkpoint_idempotency.confirmation_checkpoint,
            inbound_checkpoint=checkpoint_idempotency.inbound_checkpoint,
        )
        repository.save_message_recovery(
            claimant_message, recovery_idempotency, agent_message=recovery_agent_message
        )
        repository.append_audit_event(
            AuditEventEnvelope(
                event_id=new_id('aud'),
                event_type=recovery_rule.audit_event_type,
                outcome='failed',
                subject={'subject_type': 'claim', 'subject_id': claim_id, 'claim_id': claim_id},
                actor={
                    'actor_type': 'claimant',
                    'actor_id': principal.subject,
                    'auth_source': principal.auth_source,
                },
                reason=(
                    'The accepted claimant message was preserved after a model dependency failure.'
                ),
                source_refs=[
                    claimant_message.message_id,
                    recovery_rule.rule_id,
                    model_error.code.value,
                ],
                visibility='audit_only',
                idempotency_key=key,
                claim_revision=recovery_claim.revision,
                created_at=now_utc(),
            )
        )
        logger.warning(
            'AGENT_TURN_RECOVERY',
            extra={
                'claim_id': claim_id,
                'source_refs': [
                    claimant_message.message_id,
                    recovery_rule.rule_id,
                    model_error.code.value,
                ],
                'recovery_rule_id': recovery_rule.rule_id,
                'provider_outcome': model_error.code.value,
            },
        )
        return recovery_response

    try:
        proposal = agent.propose_turn(agent_context)
    except ModelGatewayError as model_error:
        return recover_model_failure(model_error)
    if runtime_policy is not None:
        enforce_agent_proposal(runtime_policy, proposal)
    preliminary_authority = validate_proposal(proposal)
    if preliminary_authority.outcome is AuthorityOutcome.AUTHORISED:
        _validate_tool_requests(proposal, branch_evaluation)

    context_tool_results = list(proposal.tool_results)
    requested_context_tools = {
        str(request.get('tool'))
        for request in proposal.required_tools
        if preliminary_authority.outcome is AuthorityOutcome.AUTHORISED
        and request.get('tool') in _CONTEXT_TOOL_OPERATIONS
    }
    if requested_context_tools:
        if any(
            result.get('tool')
            in {'knowledge_search', 'policy_history', 'claim_history', 'evidence.history'}
            for result in context_tool_results
        ):
            raise ApiError(
                status_code=503,
                code='AGENT_TOOL_NOT_PERMITTED',
                message='The Agent attempted a second context-tool round.',
            )
        policy_outcome = _execute_policy_search(
            repository,
            policy_history_adapter,
            claim_id,
            principal.subject,
            proposal,
        )
        history_outcome = _execute_claim_history_search(
            repository,
            policy_history_adapter,
            claim_id,
            principal.subject,
            proposal,
        )
        evidence_history_outcome = _execute_evidence_history_search(
            repository,
            claim,
            proposal,
        )
        for tool, context_outcome in (
            ('policy_history', policy_outcome),
            ('claim_history', history_outcome),
            ('evidence.history', evidence_history_outcome),
        ):
            if tool not in requested_context_tools:
                continue
            if context_outcome is None:
                raise ApiError(
                    status_code=503,
                    code='AGENT_TOOL_NOT_PERMITTED',
                    message='The Agent supplied an incomplete context-tool request.',
                )
            _record, tool_result = context_outcome
            context_tool_results.append(tool_result)
        if proposal.proposal_source is AgentProposalSource.MODEL_GATEWAY:
            try:
                proposal = agent.propose_turn(
                    replace(agent_context, tool_results=tuple(context_tool_results))
                )
            except ModelGatewayError as model_error:
                return recover_model_failure(model_error)
            if runtime_policy is not None:
                enforce_agent_proposal(runtime_policy, proposal)
            replanned_authority = validate_proposal(proposal)
            if replanned_authority.outcome is AuthorityOutcome.AUTHORISED:
                _validate_tool_requests(proposal, branch_evaluation)
            if replanned_authority.outcome is AuthorityOutcome.AUTHORISED and any(
                request.get('tool') in _CONTEXT_TOOL_OPERATIONS
                for request in proposal.required_tools
            ):
                raise ApiError(
                    status_code=503,
                    code='AGENT_TOOL_NOT_PERMITTED',
                    message='The Agent attempted a second context-tool round.',
                )
            proposal = replace(
                proposal,
                tool_results=[*context_tool_results, *proposal.tool_results],
            )
        else:
            proposal = replace(proposal, tool_results=context_tool_results)
    proposal = _validate_evidence_history_action(repository, claim, proposal)
    _validate_failed_retrieval_changes(proposal, message_text)
    authority = validate_proposal(proposal)
    runtime_trace = proposal.runtime_trace
    prepared_action_code: str | None = None
    if (
        runtime_trace is not None
        and runtime_trace.action_code == 'claim.prepare_creation'
        and authority.outcome is AuthorityOutcome.AUTHORISED
    ):
        tool_policy = runtime_policy.tool_policy if runtime_policy is not None else None
        preparation = build_claim_context_command(
            'claim.prepare_creation',
            {'claim_id': claim_id, 'expected_revision': expected_revision},
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority=ExecutionAuthority.RUNTIME_VALIDATION,
            authority_reference=f'runtime-turn:{claimant_message.message_id}',
            workflow_state=claim.claim_state.workflow_state,
            expected_revision=expected_revision,
            allowed_action_codes=(
                tool_policy.allowed_action_codes if tool_policy is not None else None
            ),
            allowed_tools=(tool_policy.allowed_tool_names if tool_policy is not None else None),
        )

        def prepare_creation(_command: ClaimContextCommand) -> ClaimContextHandlerOutcome:
            if not branch_evaluation.requirements.ready:
                raise ApiError(
                    status_code=409,
                    code='INVALID_STATE_TRANSITION',
                    message='The current Claim is not ready for formal creation.',
                )
            return ClaimContextHandlerOutcome(
                claim_id=claim_id,
                resulting_revision=claim.revision,
            )

        preparation_result = live_dispatcher.execute(
            repository,
            preparation,
            prepare_creation,
        )
        preparation_error = map_claim_context_execution_to_api(preparation_result)
        if preparation_error is not None:
            raise preparation_error
        prepared_action_code = preparation.action_code
    if proposal.action_code is not None:
        # The namespaced model contract is now executed by the same validated,
        # revision-checked mutation path as controlled turns. The action code is
        # retained in RuntimeTraceRecord; clearing it here only selects the shared
        # compatibility decision serializer and never grants the model authority.
        if runtime_trace is None:
            raise ApiError(
                status_code=503,
                code='AGENT_RUNTIME_UNAVAILABLE',
                message='The namespaced Agent Runtime did not produce an auditable trace.',
                retryable=True,
            )
        proposal = replace(proposal, action_code=None)
    if proposal.proposal_source is AgentProposalSource.MODEL_GATEWAY and runtime_trace is None:
        raise ApiError(
            status_code=422,
            code='LEGACY_AGENT_ACTION_DEPRECATED',
            message='Model responses using the deprecated legacy action contract are rejected.',
            retryable=False,
        )
    outcome = reduce_turn(
        claim,
        proposal.validated_turn,
        branch_evaluator=branch_evaluator,
        safety_interrupt=agent_context.safety_interrupt,
        open_handoffs=agent_context.open_handoffs,
        session=session,
        claimant_message=claimant_message,
        eligible_service_ids=frozenset(available_external_ids),
        timestamp=max(now_utc(), claimant_message.created_at + timedelta(microseconds=1)),
        revision_before_message=confirmation_revision_before_message,
        confirmation_before_message=(
            pending_confirmation_item.confirmation_request if pending_confirmation_item else None
        ),
        proposal=proposal,
        authority=authority,
        repository=repository,
        principal=principal,
        branch_evaluation=branch_evaluation,
        previous_evaluation=previous_evaluation,
        turn_evidence=turn_evidence,
        message_text=message_text,
        runtime_trace=runtime_trace,
        runtime_policy=runtime_policy,
        prepared_action_code=prepared_action_code,
        key=key,
        fingerprint=fingerprint,
        request_checkpoint=checkpoint_idempotency,
        turn_route=turn_route,
        agent_context=agent_context,
        selected_external_service_intents=selected_external_service_intents,
        turn_family_resolution=turn_family_resolution,
        external_capability_dispatcher=external_capability_dispatcher,
    )
    updated_claim = outcome.claim
    pending_evidence = outcome.records.pending_evidence
    handoff = outcome.handoff
    updated_session = outcome.session
    agent_message = outcome.records.agent_message
    decision = outcome.records.decision
    idempotency = outcome.records.idempotency
    evaluation_record = outcome.records.evaluation_record
    runtime_records = outcome.records.runtime_records
    live_mutation_command = outcome.records.live_mutation_command

    def persist_agent_turn(_command: ClaimContextCommand) -> ClaimContextHandlerOutcome:
        repository.save_agent_turn(
            updated_claim,
            expected_revision,
            updated_session,
            claimant_message,
            agent_message,
            decision,
            idempotency,
            handoff,
            pending_evidence,
            evaluation_record,
            runtime_trace,
            runtime_records,
            checkpointed=True,
        )
        return ClaimContextHandlerOutcome(
            claim_id=claim_id,
            resulting_revision=updated_claim.revision,
        )

    if progress_reporter is not None:
        progress_reporter.emit(AgentTurnProgressStage.TURN_COMMITTING, 'turn.commit')
    if live_mutation_command is not None:
        live_result = live_dispatcher.execute(
            repository,
            live_mutation_command,
            persist_agent_turn,
        )
        live_error = map_claim_context_execution_to_api(live_result)
        if live_error is not None:
            raise live_error
    else:
        try:
            repository.save_agent_turn(
                updated_claim,
                expected_revision,
                updated_session,
                claimant_message,
                agent_message,
                decision,
                idempotency,
                handoff,
                pending_evidence,
                evaluation_record,
                runtime_trace,
                runtime_records,
                checkpointed=True,
            )
        except RevisionConflict as conflict:
            raise ApiError(
                status_code=409,
                code='REVISION_CONFLICT',
                message='The claim changed after this page was loaded.',
                retryable=True,
                current_revision=conflict.current_revision,
            ) from conflict
        except IdempotencyConflict as conflict:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The message turn was already accepted with different retry data.',
            ) from conflict
    current_claim = repository.get_claim(claim_id, principal.subject)
    if current_claim is not None:
        try:
            continue_granted_service_offers(
                repository,
                principal,
                current_claim,
                assessor_adapter=assessor_adapter,
                assessor_entry=assessor_entry,
                capability_dispatcher=external_capability_dispatcher,
            )
        except Exception:
            logger.exception(
                'post_commit_external_dispatch_failed',
                extra={
                    'claim_id': claim_id,
                    'session_id': session_id,
                    'trigger_message_id': claimant_message.message_id,
                    'model_profile_id': session.model_profile_id,
                    'component': 'external_dispatch',
                    'internal_error_code': 'EXTERNAL_DISPATCH_PERSISTENCE_FAILED',
                    'retryable': False,
                    'resulting_revision': updated_claim.revision,
                },
            )
    return _freeze_message_turn_response(
        repository,
        idempotency,
        _message_turn_response(repository, principal, claim_id, claimant_message, decision),
    )

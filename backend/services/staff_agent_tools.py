"""Server-side dispatch for bounded, read-only Staff Agent tools."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.agent_tool_registry import (
    STAFF_TOOL_REGISTRY,
    StaffToolResult,
    StaffToolResultStatus,
)
from backend.domain.knowledge import KnowledgeRetriever, KnowledgeSearchRequest
from backend.domain.retrieval import RetrievalKind
from backend.domain.staff_agent_tools import (
    STAFF_TOOL_INPUT_MODELS,
    STAFF_TOOL_OUTPUT_MODELS,
    StaffClaimCollectionInput,
    StaffClaimReadInput,
    StaffClaimSearchInput,
    StaffCustomerUpdateReadInput,
    StaffEvidenceListInput,
    StaffEvidenceReadInput,
    StaffExternalTaskStatusInput,
    StaffHandoffReadInput,
    StaffKnowledgeSearchInput,
    StaffPolicyHistoryInput,
    StaffReviewSignalReadInput,
    StaffSessionReadInput,
    StaffSessionSearchInput,
    StaffWorkItemListInput,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.knowledge_search import search_knowledge
from backend.services.workbench import (
    get_workbench_claim_detail,
    list_workbench_customer_updates,
    list_workbench_evidence,
    list_workbench_handoffs,
    list_workbench_runtime_work_items,
    list_workbench_signals,
    list_workbench_work_items,
)

_Handler = Callable[[BaseModel], tuple[list[dict[str, Any]], list[str], list[str], list[str]]]


def _dump(value: BaseModel) -> dict[str, Any]:
    return value.model_dump(mode='json')


def _field_text(claim: Any, field_code: str) -> str | None:
    field = claim.form.get(field_code)
    if field is None or field.value is None:
        return None
    return str(field.value).strip()


def _date_matches(value: str | None, expected: date | None) -> bool:
    if expected is None:
        return True
    return value is not None and value[:10] == expected.isoformat()


def _evidence_projection(record: Any) -> dict[str, Any]:
    """Allow-list metadata and deliberately omit provenance/storage-owned values."""

    return {
        'evidence_id': record.evidence_id,
        'claim_id': record.claim_id,
        'kind': record.kind,
        'status': record.status.value,
        'file_status': record.file_status.value,
        'original_filename': record.original_filename,
        'media_type': record.media_type,
        'size_bytes': record.size_bytes,
        'source': record.source.value,
        'references': [item.model_dump(mode='json') for item in record.references],
        'related_fields': list(record.related_fields),
        'needed_for': list(record.needed_for),
        'wait_type': record.wait_type.value if record.wait_type else None,
        'responsible_party': (record.responsible_party.value if record.responsible_party else None),
        'context_summary': record.context_summary,
        'created_at': record.created_at.isoformat(),
        'updated_at': record.updated_at.isoformat(),
    }


class StaffToolDispatcher:
    """Validate and execute Staff Agent reads under one verified staff identity."""

    def __init__(
        self,
        repository: PersistenceRepository,
        principal: Principal,
        *,
        knowledge_retriever: KnowledgeRetriever | None = None,
    ) -> None:
        self._repository = repository
        self._principal = principal
        self._knowledge_retriever = knowledge_retriever
        self._used_call_ids: set[str] = set()
        self._handlers: dict[str, _Handler] = {
            'staff.claim.search': self._claim_search,
            'staff.claim.read': self._claim_read,
            'staff.session.search': self._session_search,
            'staff.session.read': self._session_read,
            'staff.evidence.list': self._evidence_list,
            'staff.evidence.read': self._evidence_read,
            'staff.knowledge.search': self._knowledge_search,
            'staff.policy.history': self._policy_history,
            'staff.handoff.read': self._handoff_read,
            'staff.review_signal.read': self._review_signal_read,
            'staff.work_item.list': self._work_item_list,
            'staff.external_task.status': self._external_task_status,
            'staff.customer_update.read': self._customer_update_read,
        }

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        call_id: str,
        correlation_id: str,
        registry_version: str,
        purpose: str,
    ) -> StaffToolResult:
        now = datetime.now(UTC)
        if self._principal.actor_type != 'staff' or 'workbench:read' not in self._principal.scopes:
            return StaffToolResult(
                tool_name=(
                    tool_name
                    if tool_name.startswith('staff.') and tool_name.count('.') == 2
                    else 'staff.runtime.unknown'
                ),
                registry_version='v1.0',
                call_id=call_id,
                correlation_id=correlation_id,
                status=StaffToolResultStatus.DENIED,
                query_scope='none',
                effective_filters={},
                limitations=['The authenticated identity is not authorised for Staff Agent reads.'],
                failure_code='ACCESS_DENIED',
                created_at=now,
            )
        contract = STAFF_TOOL_REGISTRY.get(tool_name)
        if contract is None:
            return StaffToolResult(
                tool_name=(
                    tool_name
                    if tool_name.startswith('staff.') and tool_name.count('.') == 2
                    else 'staff.runtime.unknown'
                ),
                registry_version='v1.0',
                call_id=call_id,
                correlation_id=correlation_id,
                status=StaffToolResultStatus.FAILED,
                query_scope='none',
                effective_filters={'requested_tool': tool_name},
                limitations=['The requested tool is not registered.'],
                failure_code='UNKNOWN_TOOL',
                created_at=now,
            )
        if not contract.required_scopes.issubset(self._principal.scopes):
            return self._failure(
                tool_name,
                call_id,
                correlation_id,
                StaffToolResultStatus.DENIED,
                'ACCESS_DENIED',
                'The authenticated staff identity lacks the required read scope.',
            )
        if not self._principal.roles.intersection(contract.allowed_staff_roles):
            return self._failure(
                tool_name,
                call_id,
                correlation_id,
                StaffToolResultStatus.DENIED,
                'ACCESS_DENIED',
                'The authenticated staff identity lacks an allowed role for this tool.',
            )
        if registry_version != contract.registry_version:
            return self._failure(
                tool_name,
                call_id,
                correlation_id,
                StaffToolResultStatus.FAILED,
                'REGISTRY_VERSION_MISMATCH',
                'The requested Staff Agent tool registry version is not active.',
            )
        if purpose != contract.purpose:
            return self._failure(
                tool_name,
                call_id,
                correlation_id,
                StaffToolResultStatus.DENIED,
                'PURPOSE_DENIED',
                'The requested business purpose is not authorised for this tool.',
            )
        if call_id in self._used_call_ids:
            return self._failure(
                tool_name,
                call_id,
                correlation_id,
                StaffToolResultStatus.FAILED,
                'DUPLICATE_CALL_ID',
                'The tool call identity has already been used in this dispatch scope.',
            )
        self._used_call_ids.add(call_id)
        input_model = STAFF_TOOL_INPUT_MODELS[tool_name]
        try:
            payload = input_model.model_validate(arguments)
        except ValidationError:
            return self._failure(
                tool_name,
                call_id,
                correlation_id,
                StaffToolResultStatus.FAILED,
                'INVALID_TOOL_ARGUMENTS',
                'The tool arguments do not match the registered input schema.',
            )
        try:
            items, source_refs, record_ids, limitations = self._handlers[tool_name](payload)
        except ApiError as error:
            status = (
                StaffToolResultStatus.DENIED
                if error.status_code == 403
                else StaffToolResultStatus.NO_RESULT
                if error.status_code == 404
                else StaffToolResultStatus.FAILED
            )
            return self._failure(
                tool_name,
                call_id,
                correlation_id,
                status,
                error.code,
                error.message,
                effective_filters=payload.model_dump(mode='json', exclude_none=True),
            )
        except RuntimeError:
            return self._failure(
                tool_name,
                call_id,
                correlation_id,
                StaffToolResultStatus.UNAVAILABLE,
                'SOURCE_UNAVAILABLE',
                'The registered source is temporarily unavailable.',
                retryable=True,
                effective_filters=payload.model_dump(mode='json', exclude_none=True),
            )
        output_model = STAFF_TOOL_OUTPUT_MODELS[tool_name]
        try:
            output = output_model.model_validate({'items': items})
        except ValidationError:
            return self._failure(
                tool_name,
                call_id,
                correlation_id,
                StaffToolResultStatus.FAILED,
                'INVALID_TOOL_OUTPUT',
                'The handler output does not match the registered disclosure schema.',
                effective_filters=payload.model_dump(mode='json', exclude_none=True),
            )
        status = StaffToolResultStatus.SUCCEEDED if items else StaffToolResultStatus.NO_RESULT
        return StaffToolResult(
            tool_name=tool_name,
            registry_version=contract.registry_version,
            call_id=call_id,
            correlation_id=correlation_id,
            status=status,
            output=output,
            source_refs=source_refs,
            record_ids=record_ids,
            query_scope=contract.claim_scope,
            effective_filters=payload.model_dump(mode='json', exclude_none=True),
            limitations=limitations,
            created_at=now,
        )

    def _failure(
        self,
        tool_name: str,
        call_id: str,
        correlation_id: str,
        status: StaffToolResultStatus,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        effective_filters: dict[str, Any] | None = None,
    ) -> StaffToolResult:
        contract = STAFF_TOOL_REGISTRY[tool_name]
        return StaffToolResult(
            tool_name=tool_name,
            registry_version=contract.registry_version,
            call_id=call_id,
            correlation_id=correlation_id,
            status=status,
            query_scope=contract.claim_scope,
            effective_filters=effective_filters or {},
            limitations=[message],
            failure_code=code,
            retryable=retryable,
            next_action='Retry only after the stated scope or source problem is resolved.',
            created_at=datetime.now(UTC),
        )

    def _claim(self, claim_id: str) -> Any:
        return get_workbench_claim_detail(self._repository, self._principal, claim_id)

    def _claim_search(
        self, raw: BaseModel
    ) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
        payload = cast(StaffClaimSearchInput, raw)
        filters = payload.model_dump(mode='json', exclude_none=True, exclude={'limit'})
        candidates = self._repository.search_claims_internal(filters, payload.limit)
        matches: list[dict[str, Any]] = []
        for candidate in candidates:
            claim = candidate.claim
            external_reference = (
                claim.external_claim.claim_number if claim.external_claim is not None else None
            )
            matches.append(
                {
                    'claim_id': claim.claim_id,
                    'display_reference': external_reference or claim.claim_id,
                    'matched_fields': [
                        key
                        for key, value in payload.model_dump(exclude_none=True).items()
                        if key != 'limit' and value is not None
                    ],
                    'incident_date': _field_text(claim, 'incident.occurred_at'),
                    'product_family': _field_text(claim, 'claim.product_family'),
                    'lifecycle_state': candidate.lifecycle_state.value,
                    'revision': claim.revision,
                    'created_at': claim.created_at.isoformat(),
                    'updated_at': claim.updated_at.isoformat(),
                }
            )
        matches.sort(key=lambda item: (item['created_at'], item['claim_id']), reverse=True)
        matches = matches[: payload.limit]
        ids = [str(item['claim_id']) for item in matches]
        return matches, ids, ids, []

    def _claim_read(
        self, raw: BaseModel
    ) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
        payload = cast(StaffClaimReadInput, raw)
        claim = self._claim(payload.claim_id)
        item = {
            'claim_id': claim.claim_id,
            'display_reference': claim.display_reference,
            'revision': claim.revision,
            'incident': claim.incident.model_dump(mode='json'),
            'lifecycle_state': claim.lifecycle_state.value,
            'workflow_state': claim.workflow_state.value,
            'ownership': claim.ownership.model_dump(mode='json'),
            'work_summary': claim.work_summary.model_dump(mode='json'),
            'integration_summary': claim.integration_summary.model_dump(mode='json'),
            'customer_next_step': claim.customer_next_step.model_dump(mode='json'),
            'created_at': claim.created_at.isoformat(),
            'updated_at': claim.updated_at.isoformat(),
        }
        return [item], [claim.claim_id], [claim.claim_id], []

    def _session_search(
        self, raw: BaseModel
    ) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
        payload = cast(StaffSessionSearchInput, raw)
        claim = self._claim(payload.claim_id)
        stored_claim = self._repository.get_claim_internal(claim.claim_id)
        assert stored_claim is not None
        items: list[dict[str, Any]] = []
        for session in self._repository.list_sessions_for_claim(
            claim.claim_id, stored_claim.customer_id
        ):
            if payload.session_id and session.session_id != payload.session_id:
                continue
            if payload.started_date and session.started_at.date() != payload.started_date:
                continue
            if payload.status and session.status.value != payload.status:
                continue
            messages = self._repository.list_messages(
                claim.claim_id, session.session_id, stored_claim.customer_id
            )
            if payload.actor and not any(
                message.actor.value == payload.actor for message in messages
            ):
                continue
            if payload.message_contains and not any(
                payload.message_contains.casefold() in str(message.content).casefold()
                for message in messages
            ):
                continue
            items.append(
                {
                    'session_id': session.session_id,
                    'claim_id': session.claim_id,
                    'status': session.status.value,
                    'summary': session.summary,
                    'message_count': len(messages),
                    'started_at': session.started_at.isoformat(),
                    'last_active_at': session.last_active_at.isoformat(),
                }
            )
        items.sort(key=lambda item: (item['started_at'], item['session_id']), reverse=True)
        items = items[: payload.limit]
        ids = [str(item['session_id']) for item in items]
        return items, [claim.claim_id, *ids], ids, []

    def _session_read(
        self, raw: BaseModel
    ) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
        payload = cast(StaffSessionReadInput, raw)
        claim = self._repository.get_claim_internal(payload.claim_id)
        self._claim(payload.claim_id)
        assert claim is not None
        session = self._repository.get_session(
            payload.claim_id, payload.session_id, claim.customer_id
        )
        if session is None:
            raise ApiError(
                status_code=404,
                code='RESOURCE_NOT_FOUND',
                message='The session was not found in this Claim.',
            )
        messages = self._repository.list_messages(
            payload.claim_id, payload.session_id, claim.customer_id
        )[-payload.message_limit :]
        item = {
            'session': _dump(session),
            'messages': [
                {
                    'message_id': message.message_id,
                    'actor': message.actor.value,
                    'visibility': message.visibility.value,
                    'content': message.content,
                    'evidence_refs': message.evidence_refs,
                    'created_at': message.created_at.isoformat(),
                }
                for message in messages
            ],
        }
        ids = [session.session_id, *[message.message_id for message in messages]]
        return [item], [claim.claim_id, *ids], ids, []

    def _evidence_list(
        self, raw: BaseModel
    ) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
        payload = cast(StaffEvidenceListInput, raw)
        page = list_workbench_evidence(
            self._repository, self._principal, payload.claim_id, payload.limit, None
        )
        records = [
            item
            for item in page.items
            if (payload.status is None or item.status.value == payload.status)
            and (payload.kind is None or item.kind == payload.kind)
        ]
        items = [_evidence_projection(item) for item in records]
        ids = [item.evidence_id for item in records]
        return items, [payload.claim_id, *ids], ids, []

    def _evidence_read(
        self, raw: BaseModel
    ) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
        payload = cast(StaffEvidenceReadInput, raw)
        claim = self._repository.get_claim_internal(payload.claim_id)
        self._claim(payload.claim_id)
        assert claim is not None
        record = self._repository.get_evidence(
            payload.claim_id, payload.evidence_id, claim.customer_id
        )
        if record is None:
            raise ApiError(
                status_code=404,
                code='RESOURCE_NOT_FOUND',
                message='The Evidence was not found in this Claim.',
            )
        return (
            [_evidence_projection(record)],
            [payload.claim_id, record.evidence_id],
            [record.evidence_id],
            ['Raw bytes and storage-owned provenance were not read or disclosed.'],
        )

    def _knowledge_search(
        self, raw: BaseModel
    ) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
        payload = cast(StaffKnowledgeSearchInput, raw)
        if self._knowledge_retriever is None:
            raise RuntimeError('Knowledge retriever is unavailable.')
        response = search_knowledge(
            self._knowledge_retriever,
            KnowledgeSearchRequest(**payload.model_dump()),
        )
        if response.status in {'timeout', 'unavailable'}:
            raise RuntimeError('Knowledge retriever is unavailable.')
        items = [item.model_dump(mode='json') for item in response.results]
        ids = [item.chunk_id for item in response.results]
        refs = [
            f'knowledge:{item.document_id}:{item.chunk_id}:{item.version}'
            for item in response.results
        ]
        return items, refs, ids, list(response.limitations)

    def _policy_history(
        self, raw: BaseModel
    ) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
        payload = cast(StaffPolicyHistoryInput, raw)
        claim = self._repository.get_claim_internal(payload.claim_id)
        self._claim(payload.claim_id)
        assert claim is not None
        records = []
        for record in self._repository.list_retrieval_records(payload.claim_id, claim.customer_id):
            if record.kind is not RetrievalKind.POLICY:
                continue
            if payload.product and record.facts.product != payload.product:
                continue
            if payload.effective_at and not (
                (
                    record.facts.effective_from is None
                    or record.facts.effective_from <= payload.effective_at
                )
                and (
                    record.facts.effective_to is None
                    or payload.effective_at <= record.facts.effective_to
                )
            ):
                continue
            records.append(record)
        records.sort(key=lambda item: (item.source.retrieved_at, item.retrieval_id), reverse=True)
        records = records[: payload.limit]
        ids = [item.retrieval_id for item in records]
        return [_dump(item) for item in records], [payload.claim_id, *ids], ids, []

    def _claim_collection(
        self,
        payload: StaffClaimCollectionInput,
        loader: Callable[[PersistenceRepository, Principal, str, int, str | None], Any],
        id_attribute: str,
        requested_id: str | None,
    ) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
        page = loader(self._repository, self._principal, payload.claim_id, payload.limit, None)
        records = [
            item
            for item in page.items
            if requested_id is None or getattr(item, id_attribute) == requested_id
        ]
        ids = [str(getattr(item, id_attribute)) for item in records]
        return [_dump(item) for item in records], [payload.claim_id, *ids], ids, []

    def _handoff_read(
        self, raw: BaseModel
    ) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
        payload = cast(StaffHandoffReadInput, raw)
        return self._claim_collection(
            payload, list_workbench_handoffs, 'handoff_id', payload.handoff_id
        )

    def _review_signal_read(
        self, raw: BaseModel
    ) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
        payload = cast(StaffReviewSignalReadInput, raw)
        return self._claim_collection(
            payload, list_workbench_signals, 'signal_id', payload.signal_id
        )

    def _work_item_list(
        self, raw: BaseModel
    ) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
        payload = cast(StaffWorkItemListInput, raw)
        staff_items = self._claim_collection(
            payload, list_workbench_work_items, 'action_id', payload.work_item_id
        )
        runtime_items = self._claim_collection(
            payload, list_workbench_runtime_work_items, 'work_item_id', payload.work_item_id
        )
        items = [*staff_items[0], *runtime_items[0]]
        ids = [*staff_items[2], *runtime_items[2]][: payload.limit]
        return items[: payload.limit], [payload.claim_id, *ids], ids, []

    def _external_task_status(
        self, raw: BaseModel
    ) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
        payload = cast(StaffExternalTaskStatusInput, raw)
        self._claim(payload.claim_id)
        raise RuntimeError('The canonical external-task registry dependency is not active.')

    def _customer_update_read(
        self, raw: BaseModel
    ) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
        payload = cast(StaffCustomerUpdateReadInput, raw)
        return self._claim_collection(
            payload, list_workbench_customer_updates, 'update_id', payload.update_id
        )


__all__ = ['StaffToolDispatcher']

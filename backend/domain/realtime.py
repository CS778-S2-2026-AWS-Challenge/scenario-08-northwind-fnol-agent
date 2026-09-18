"""Provider-neutral durable realtime invalidation contract."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from enum import Enum

from pydantic import Field, model_validator

from backend.domain.ids import new_id
from backend.domain.models import ContractModel


class RealtimeAudience(str, Enum):
    CLAIMANT = 'claimant'
    STAFF = 'staff'


class AgentTurnProgressStage(str, Enum):
    TURN_ACCEPTED = 'turn.accepted'
    CONTEXT_LOADING = 'context.loading'
    KNOWLEDGE_QUERYING = 'knowledge.querying'
    TOOL_RUNNING = 'tool.running'
    MODEL_WAITING = 'model.waiting'
    OFFER_PREPARING = 'offer.preparing'
    TURN_VALIDATING = 'turn.validating'
    TURN_COMMITTING = 'turn.committing'
    TURN_COMPLETED = 'turn.completed'
    TURN_FAILED = 'turn.failed'


class AgentTurnProgress(ContractModel):
    turn_id: str = Field(min_length=1, max_length=200)
    session_id: str = Field(min_length=1, max_length=120)
    stage: AgentTurnProgressStage
    state: str = Field(pattern=r'^(running|completed|failed)$')
    ordinal: int = Field(ge=1)
    safe_activity_code: str | None = Field(default=None, max_length=120)
    retryable: bool | None = None


class RealtimeResource(str, Enum):
    """Stable client refresh boundaries backed by documented public read APIs."""

    CLAIM = 'claim'
    MESSAGES = 'messages'
    EVIDENCE = 'evidence'
    HANDOFFS = 'handoffs'
    WORK_ITEMS = 'work_items'
    EXTERNAL_TASKS = 'external_tasks'
    ASSET_SNAPSHOTS = 'asset_snapshots'
    COLLABORATION_REQUESTS = 'collaboration_requests'
    CUSTOMER_UPDATES = 'customer_updates'
    SIGNALS = 'signals'
    QUEUE = 'queue'


REALTIME_RESOURCE_READ_APIS: dict[RealtimeResource, dict[RealtimeAudience, tuple[str, ...]]] = {
    RealtimeResource.CLAIM: {
        RealtimeAudience.CLAIMANT: ('/api/v1/claims/{claim_id}',),
        RealtimeAudience.STAFF: (
            '/api/v1/workbench/claims/{claim_id}',
            '/api/v1/workbench/claims/{claim_id}/fields',
            '/api/v1/workbench/claims/{claim_id}/sessions',
        ),
    },
    RealtimeResource.MESSAGES: {
        RealtimeAudience.CLAIMANT: ('/api/v1/claims/{claim_id}/sessions/{session_id}/messages',),
        RealtimeAudience.STAFF: (
            '/api/v1/workbench/claims/{claim_id}/sessions/{session_id}/messages',
        ),
    },
    RealtimeResource.EVIDENCE: {
        RealtimeAudience.CLAIMANT: ('/api/v1/claims/{claim_id}/evidence',),
        RealtimeAudience.STAFF: ('/api/v1/workbench/claims/{claim_id}/evidence',),
    },
    RealtimeResource.HANDOFFS: {
        RealtimeAudience.CLAIMANT: ('/api/v1/claims/{claim_id}',),
        RealtimeAudience.STAFF: ('/api/v1/workbench/claims/{claim_id}/handoffs',),
    },
    RealtimeResource.WORK_ITEMS: {
        RealtimeAudience.STAFF: (
            '/api/v1/workbench/claims/{claim_id}/work-items',
            '/api/v1/workbench/claims/{claim_id}/runtime-work-items',
        ),
    },
    RealtimeResource.EXTERNAL_TASKS: {
        RealtimeAudience.CLAIMANT: ('/api/v1/claims/{claim_id}',),
        RealtimeAudience.STAFF: ('/api/v1/workbench/claims/{claim_id}/external-requests',),
    },
    RealtimeResource.ASSET_SNAPSHOTS: {
        RealtimeAudience.CLAIMANT: ('/api/v1/claims/{claim_id}/asset-snapshots',),
        RealtimeAudience.STAFF: ('/api/v1/workbench/claims/{claim_id}/asset-snapshots',),
    },
    RealtimeResource.COLLABORATION_REQUESTS: {
        RealtimeAudience.STAFF: ('/api/v1/workbench/claims/{claim_id}/collaboration-requests',),
    },
    RealtimeResource.CUSTOMER_UPDATES: {
        RealtimeAudience.STAFF: ('/api/v1/workbench/claims/{claim_id}/customer-updates',),
    },
    RealtimeResource.SIGNALS: {
        RealtimeAudience.STAFF: ('/api/v1/workbench/claims/{claim_id}/signals',),
    },
    RealtimeResource.QUEUE: {
        RealtimeAudience.STAFF: ('/api/v1/workbench/claims',),
    },
}


def realtime_read_apis_for(
    audience: RealtimeAudience,
    resources: tuple[RealtimeResource, ...],
) -> tuple[str, ...]:
    """Resolve role-authorised refresh routes while preserving order and removing duplicates."""

    routes: list[str] = []
    for resource in resources:
        for route in REALTIME_RESOURCE_READ_APIS[resource].get(audience, ()):
            if route not in routes:
                routes.append(route)
    return tuple(routes)


class RealtimeMutation(str, Enum):
    CLAIM_CREATED = 'claim_created'
    CLAIM_CHANGED = 'claim_changed'
    CLAIM_OWNER_CHANGED = 'claim_owner_changed'
    SESSION_CHANGED = 'session_changed'
    SESSION_PAUSED = 'session_paused'
    MESSAGE_CHANGED = 'message_changed'
    MESSAGE_MUTATION_COMMITTED = 'message_mutation_committed'
    AGENT_TURN_COMMITTED = 'agent_turn_committed'
    RUNTIME_TURN_COMMITTED = 'runtime_turn_committed'
    EVIDENCE_CHANGED = 'evidence_changed'
    EVIDENCE_CLAIM_CHANGED = 'evidence_claim_changed'
    EXTERNAL_TASK_CHANGED = 'external_task_changed'
    EXTERNAL_REQUEST_CHANGED = 'external_request_changed'
    EXTERNAL_EVIDENCE_LINKED = 'external_evidence_linked'
    EXTERNAL_RESULT_CHANGED = 'external_result_changed'
    OWNERSHIP_CHANGED = 'ownership_changed'
    STAFF_MUTATION_COMMITTED = 'staff_mutation_committed'
    HANDOFF_CHANGED = 'handoff_changed'
    HANDOFF_MUTATION_COMMITTED = 'handoff_mutation_committed'
    ASSESSOR_RECONCILED = 'assessor_reconciled'


class MutationOutcome(str, Enum):
    CHANGED = 'changed'
    EXACT_NOOP = 'exact_noop'
    CONFLICT = 'conflict'


CLAIMANT_REALTIME_RESOURCES = frozenset(
    {
        RealtimeResource.CLAIM,
        RealtimeResource.MESSAGES,
        RealtimeResource.EVIDENCE,
        RealtimeResource.HANDOFFS,
        RealtimeResource.EXTERNAL_TASKS,
        RealtimeResource.ASSET_SNAPSHOTS,
    }
)


REALTIME_MUTATION_RESOURCES: dict[RealtimeMutation, tuple[RealtimeResource, ...]] = {
    RealtimeMutation.CLAIM_CREATED: (RealtimeResource.CLAIM, RealtimeResource.QUEUE),
    RealtimeMutation.CLAIM_CHANGED: (
        RealtimeResource.CLAIM,
        RealtimeResource.ASSET_SNAPSHOTS,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.CLAIM_OWNER_CHANGED: (RealtimeResource.CLAIM,),
    RealtimeMutation.SESSION_CHANGED: (RealtimeResource.CLAIM, RealtimeResource.QUEUE),
    RealtimeMutation.SESSION_PAUSED: (
        RealtimeResource.CLAIM,
        RealtimeResource.WORK_ITEMS,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.MESSAGE_CHANGED: (RealtimeResource.MESSAGES,),
    RealtimeMutation.MESSAGE_MUTATION_COMMITTED: (
        RealtimeResource.CLAIM,
        RealtimeResource.MESSAGES,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.AGENT_TURN_COMMITTED: (
        RealtimeResource.CLAIM,
        RealtimeResource.MESSAGES,
        RealtimeResource.EVIDENCE,
        RealtimeResource.HANDOFFS,
        RealtimeResource.WORK_ITEMS,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.RUNTIME_TURN_COMMITTED: (
        RealtimeResource.MESSAGES,
        RealtimeResource.WORK_ITEMS,
    ),
    RealtimeMutation.EVIDENCE_CHANGED: (RealtimeResource.EVIDENCE,),
    RealtimeMutation.EVIDENCE_CLAIM_CHANGED: (
        RealtimeResource.CLAIM,
        RealtimeResource.EVIDENCE,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.EXTERNAL_TASK_CHANGED: (
        RealtimeResource.EXTERNAL_TASKS,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.EXTERNAL_REQUEST_CHANGED: (RealtimeResource.EXTERNAL_TASKS,),
    RealtimeMutation.EXTERNAL_EVIDENCE_LINKED: (
        RealtimeResource.EVIDENCE,
        RealtimeResource.EXTERNAL_TASKS,
    ),
    RealtimeMutation.EXTERNAL_RESULT_CHANGED: (
        RealtimeResource.EXTERNAL_TASKS,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.OWNERSHIP_CHANGED: (
        RealtimeResource.CLAIM,
        RealtimeResource.COLLABORATION_REQUESTS,
        RealtimeResource.HANDOFFS,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.STAFF_MUTATION_COMMITTED: (
        RealtimeResource.CLAIM,
        RealtimeResource.MESSAGES,
        RealtimeResource.HANDOFFS,
        RealtimeResource.WORK_ITEMS,
        RealtimeResource.CUSTOMER_UPDATES,
        RealtimeResource.SIGNALS,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.HANDOFF_CHANGED: (
        RealtimeResource.HANDOFFS,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.HANDOFF_MUTATION_COMMITTED: (
        RealtimeResource.CLAIM,
        RealtimeResource.HANDOFFS,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.ASSESSOR_RECONCILED: (
        RealtimeResource.CLAIM,
        RealtimeResource.EXTERNAL_TASKS,
        RealtimeResource.EVIDENCE,
        RealtimeResource.WORK_ITEMS,
        RealtimeResource.QUEUE,
    ),
}


# Required resources are the projections changed by every variant of a mutation.
# Optional resources are admitted only when the concrete transaction writes the
# corresponding record from AUTHORITATIVE_RECORD_PROJECTION_IMPACTS.
REALTIME_MUTATION_REQUIRED_RESOURCES: dict[RealtimeMutation, tuple[RealtimeResource, ...]] = {
    **REALTIME_MUTATION_RESOURCES,
    RealtimeMutation.CLAIM_CHANGED: (RealtimeResource.CLAIM, RealtimeResource.QUEUE),
    RealtimeMutation.MESSAGE_MUTATION_COMMITTED: (
        RealtimeResource.CLAIM,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.AGENT_TURN_COMMITTED: (
        RealtimeResource.CLAIM,
        RealtimeResource.MESSAGES,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.RUNTIME_TURN_COMMITTED: (RealtimeResource.MESSAGES,),
    RealtimeMutation.EVIDENCE_CLAIM_CHANGED: (
        RealtimeResource.CLAIM,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.OWNERSHIP_CHANGED: (
        RealtimeResource.CLAIM,
        RealtimeResource.COLLABORATION_REQUESTS,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.STAFF_MUTATION_COMMITTED: (
        RealtimeResource.CLAIM,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.HANDOFF_MUTATION_COMMITTED: (
        RealtimeResource.CLAIM,
        RealtimeResource.QUEUE,
    ),
    RealtimeMutation.ASSESSOR_RECONCILED: (
        RealtimeResource.CLAIM,
        RealtimeResource.EXTERNAL_TASKS,
        RealtimeResource.EVIDENCE,
        RealtimeResource.QUEUE,
    ),
}


AUTHORITATIVE_RECORD_PROJECTION_IMPACTS: dict[str, tuple[RealtimeResource, ...]] = {
    'claim_asset_snapshot': (RealtimeResource.ASSET_SNAPSHOTS,),
    'motor_other_driver': (RealtimeResource.CLAIM,),
    'contents_item_evidence_association': (RealtimeResource.CLAIM,),
    'branch_evaluation': (),
    'collaboration_request': (RealtimeResource.COLLABORATION_REQUESTS,),
    'claim_coworker': (
        RealtimeResource.CLAIM,
        RealtimeResource.COLLABORATION_REQUESTS,
        RealtimeResource.QUEUE,
    ),
    'customer_update': (RealtimeResource.CUSTOMER_UPDATES,),
    'signal_decision': (RealtimeResource.SIGNALS,),
    'staff_agent_execution': (),
    'agent_decision': (),
    'runtime_trace': (),
    'turn_plan': (),
    'agent_proposal': (),
    'execution_plan': (),
    'action_envelope': (),
    'tool_result': (),
    'turn_result': (),
    'message': (RealtimeResource.MESSAGES,),
    'evidence': (RealtimeResource.EVIDENCE,),
    'evidence_claim_link': (RealtimeResource.EVIDENCE,),
    'external_task_evidence_link': (
        RealtimeResource.EVIDENCE,
        RealtimeResource.EXTERNAL_TASKS,
    ),
    'handoff': (RealtimeResource.HANDOFFS,),
    'runtime_work_item': (RealtimeResource.WORK_ITEMS,),
    'staff_action': (RealtimeResource.WORK_ITEMS,),
    'external_task': (RealtimeResource.EXTERNAL_TASKS,),
    'external_task_request': (RealtimeResource.EXTERNAL_TASKS,),
    'external_task_result': (RealtimeResource.EXTERNAL_TASKS,),
}


class RealtimePublication(ContractModel):
    """Provider-neutral intent emitted only for a changed authoritative mutation."""

    mutation: RealtimeMutation
    claim_id: str
    customer_id: str
    claim_revision: int | None = Field(default=None, ge=1)
    operation_correlation: str | None = Field(default=None, max_length=200)
    resources: tuple[RealtimeResource, ...] = Field(min_length=1, max_length=11)
    claimant_resources: tuple[RealtimeResource, ...] = Field(default=(), max_length=11)
    audiences: tuple[RealtimeAudience, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode='after')
    def validate_sets(self) -> RealtimePublication:
        _validate_visibility_sets(
            self.resources,
            self.claimant_resources,
            self.audiences,
        )
        allowed = REALTIME_MUTATION_RESOURCES[self.mutation]
        required = REALTIME_MUTATION_REQUIRED_RESOURCES[self.mutation]
        if not set(required).issubset(self.resources):
            raise ValueError('Realtime resources omit a required mutation projection.')
        if not set(self.resources).issubset(allowed):
            raise ValueError('Realtime resources exceed the mutation contract.')
        if self.resources != tuple(resource for resource in allowed if resource in self.resources):
            raise ValueError('Realtime resources do not use canonical registry order.')
        return self


class AgentTurnProgressPublication(ContractModel):
    claim_id: str = Field(min_length=1, max_length=120)
    customer_id: str = Field(min_length=1, max_length=120)
    progress: AgentTurnProgress
    audiences: tuple[RealtimeAudience, ...] = (RealtimeAudience.CLAIMANT,)

    @model_validator(mode='after')
    def claimant_only(self) -> AgentTurnProgressPublication:
        if self.audiences != (RealtimeAudience.CLAIMANT,):
            raise ValueError('Agent turn progress is claimant-only.')
        return self


class RealtimeEvent(ContractModel):
    """Durable invalidation metadata; authoritative state remains in normal APIs."""

    event_id: str = Field(pattern=r'^rte_[0-9a-f]{20}$')
    occurred_at: datetime
    claim_id: str
    customer_id: str
    claim_revision: int | None = Field(default=None, ge=1)
    sequence: int | None = Field(default=None, ge=1)
    operation_correlation: str | None = Field(default=None, max_length=200)
    resources: tuple[RealtimeResource, ...] = Field(default=(), max_length=11)
    claimant_resources: tuple[RealtimeResource, ...] = Field(default=(), max_length=11)
    audiences: tuple[RealtimeAudience, ...] = Field(min_length=1, max_length=2)
    event_type: str = Field(
        default='resources.changed',
        pattern=r'^(resources\.changed|agent\.turn\.progress)$',
    )
    progress: AgentTurnProgress | None = None

    @model_validator(mode='after')
    def validate_sets(self) -> RealtimeEvent:
        if self.event_type == 'agent.turn.progress':
            if self.progress is None or self.audiences != (RealtimeAudience.CLAIMANT,):
                raise ValueError('Agent turn progress requires one claimant-only payload.')
            if self.resources or self.claimant_resources:
                raise ValueError('Agent turn progress cannot carry projection resources.')
            return self
        if self.progress is not None:
            raise ValueError('Resource events cannot carry Agent turn progress.')
        if not self.resources:
            raise ValueError('Resource events require at least one projection resource.')
        _validate_visibility_sets(
            self.resources,
            self.claimant_resources,
            self.audiences,
        )
        return self


def _validate_visibility_sets(
    resources: tuple[RealtimeResource, ...],
    claimant_resources: tuple[RealtimeResource, ...],
    audiences: tuple[RealtimeAudience, ...],
) -> None:
    if len(set(resources)) != len(resources):
        raise ValueError('Realtime resources must be unique.')
    if len(set(audiences)) != len(audiences):
        raise ValueError('Realtime audiences must be unique.')
    if not set(claimant_resources).issubset(resources):
        raise ValueError('Claimant resources must be a subset of event resources.')
    if not set(claimant_resources).issubset(CLAIMANT_REALTIME_RESOURCES):
        raise ValueError('Claimant resources contain staff-only resource hints.')
    if bool(claimant_resources) != (RealtimeAudience.CLAIMANT in audiences):
        raise ValueError('Claimant audience and resources must be declared together.')


class RealtimeCursor(ContractModel):
    occurred_at: datetime
    event_id: str = Field(pattern=r'^rte_[0-9a-f]{20}$')
    sequence: int | None = Field(default=None, ge=1)

    def encode(self) -> str:
        raw = json.dumps(
            {
                'occurred_at': self.occurred_at.isoformat(),
                'event_id': self.event_id,
                'sequence': self.sequence,
            },
            separators=(',', ':'),
        ).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip('=')

    @property
    def ordering_key(self) -> tuple[int, object, str]:
        if self.sequence is not None:
            return (0, self.sequence, self.event_id)
        return (1, self.occurred_at, self.event_id)

    @classmethod
    def decode(cls, value: str) -> RealtimeCursor:
        try:
            padded = value + '=' * (-len(value) % 4)
            return cls.model_validate_json(base64.urlsafe_b64decode(padded).decode())
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError('The realtime cursor is invalid.') from error


class RealtimeDelivery(ContractModel):
    event: str
    cursor: str | None = None
    data: dict[str, object] = Field(default_factory=dict)


def cursor_for(event: RealtimeEvent) -> str:
    return RealtimeCursor(
        occurred_at=event.occurred_at,
        event_id=event.event_id,
        sequence=event.sequence,
    ).encode()


def cursor_is_after(candidate: str, previous: str | None) -> bool:
    """Return whether a delivery cursor is strictly newer than the accepted cursor."""

    if previous is None:
        return True
    candidate_cursor = RealtimeCursor.decode(candidate)
    previous_cursor = RealtimeCursor.decode(previous)
    if candidate_cursor.sequence is not None and previous_cursor.sequence is None:
        return True
    if candidate_cursor.sequence is None and previous_cursor.sequence is not None:
        return False
    return candidate_cursor.ordering_key > previous_cursor.ordering_key


def realtime_publication_for(
    *,
    mutation: RealtimeMutation,
    claim_id: str,
    customer_id: str,
    claim_revision: int | None = None,
    operation_correlation: str | None = None,
    claimant_visible: bool = True,
    resources: tuple[RealtimeResource, ...] | None = None,
    claimant_resources: tuple[RealtimeResource, ...] | None = None,
) -> RealtimePublication:
    changed_resources = (
        resources if resources is not None else REALTIME_MUTATION_RESOURCES[mutation]
    )
    safe_resources = claimant_resources_for(mutation, resources=changed_resources)
    visible_resources = (
        tuple(
            resource
            for resource in dict.fromkeys(claimant_resources)
            if resource in CLAIMANT_REALTIME_RESOURCES
        )
        if claimant_resources is not None
        else (safe_resources if claimant_visible else ())
    )
    audiences = (
        (RealtimeAudience.CLAIMANT, RealtimeAudience.STAFF)
        if visible_resources
        else (RealtimeAudience.STAFF,)
    )
    return RealtimePublication(
        mutation=mutation,
        claim_id=claim_id,
        customer_id=customer_id,
        claim_revision=claim_revision,
        operation_correlation=operation_correlation,
        resources=changed_resources,
        claimant_resources=visible_resources,
        audiences=audiences,
    )


def claimant_resources_for(
    mutation: RealtimeMutation,
    *,
    resources: tuple[RealtimeResource, ...] | None = None,
    excluded: frozenset[RealtimeResource] = frozenset(),
) -> tuple[RealtimeResource, ...]:
    """Project one registered mutation to claimant-safe resource hints."""

    return tuple(
        resource
        for resource in (
            resources if resources is not None else REALTIME_MUTATION_RESOURCES[mutation]
        )
        if resource in CLAIMANT_REALTIME_RESOURCES and resource not in excluded
    )


def realtime_resources_for_records(
    mutation: RealtimeMutation,
    record_kinds: tuple[str, ...],
) -> tuple[RealtimeResource, ...]:
    """Return the validated projection set changed by one concrete transaction."""

    changed = set(REALTIME_MUTATION_REQUIRED_RESOURCES[mutation])
    for kind in record_kinds:
        if kind not in AUTHORITATIVE_RECORD_PROJECTION_IMPACTS:
            raise ValueError(f'Record kind {kind} is missing from the projection-impact matrix.')
        changed.update(AUTHORITATIVE_RECORD_PROJECTION_IMPACTS[kind])
    allowed = REALTIME_MUTATION_RESOURCES[mutation]
    unexpected = changed.difference(allowed)
    if unexpected:
        names = ', '.join(sorted(resource.value for resource in unexpected))
        raise ValueError(f'Record changes exceed the {mutation.value} contract: {names}.')
    return tuple(resource for resource in allowed if resource in changed)


def realtime_event_from_publication(
    publication: RealtimePublication | AgentTurnProgressPublication,
    *,
    occurred_at: datetime,
    sequence: int,
) -> RealtimeEvent:
    if isinstance(publication, AgentTurnProgressPublication):
        return RealtimeEvent(
            event_id=new_id('rte'),
            occurred_at=occurred_at,
            claim_id=publication.claim_id,
            customer_id=publication.customer_id,
            sequence=sequence,
            resources=(),
            claimant_resources=(),
            audiences=publication.audiences,
            event_type='agent.turn.progress',
            progress=publication.progress,
        )
    return RealtimeEvent(
        event_id=new_id('rte'),
        occurred_at=occurred_at,
        claim_id=publication.claim_id,
        customer_id=publication.customer_id,
        claim_revision=publication.claim_revision,
        sequence=sequence,
        operation_correlation=publication.operation_correlation,
        resources=publication.resources,
        claimant_resources=publication.claimant_resources,
        audiences=publication.audiences,
        event_type='resources.changed',
    )

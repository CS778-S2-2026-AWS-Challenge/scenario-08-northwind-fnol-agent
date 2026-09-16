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


class RealtimeResource(str, Enum):
    CLAIM = 'claim'
    MESSAGES = 'messages'
    EVIDENCE = 'evidence'
    HANDOFFS = 'handoffs'
    WORK_ITEMS = 'work_items'
    EXTERNAL_TASKS = 'external_tasks'
    QUEUE = 'queue'


CLAIMANT_REALTIME_RESOURCES = frozenset(
    {
        RealtimeResource.CLAIM,
        RealtimeResource.MESSAGES,
        RealtimeResource.EVIDENCE,
        RealtimeResource.HANDOFFS,
        RealtimeResource.EXTERNAL_TASKS,
    }
)


class RealtimeEvent(ContractModel):
    """Durable invalidation metadata; authoritative state remains in normal APIs."""

    event_id: str = Field(pattern=r'^rte_[0-9a-f]{20}$')
    occurred_at: datetime
    claim_id: str
    customer_id: str
    claim_revision: int | None = Field(default=None, ge=1)
    sequence: int | None = Field(default=None, ge=1)
    operation_correlation: str | None = Field(default=None, max_length=200)
    resources: tuple[RealtimeResource, ...] = Field(min_length=1, max_length=7)
    claimant_resources: tuple[RealtimeResource, ...] = Field(default=(), max_length=7)
    audiences: tuple[RealtimeAudience, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode='after')
    def validate_sets(self) -> RealtimeEvent:
        if len(set(self.resources)) != len(self.resources):
            raise ValueError('Realtime resources must be unique.')
        if len(set(self.audiences)) != len(self.audiences):
            raise ValueError('Realtime audiences must be unique.')
        if not set(self.claimant_resources).issubset(self.resources):
            raise ValueError('Claimant resources must be a subset of event resources.')
        if not set(self.claimant_resources).issubset(CLAIMANT_REALTIME_RESOURCES):
            raise ValueError('Claimant resources contain staff-only resource hints.')
        if bool(self.claimant_resources) != (RealtimeAudience.CLAIMANT in self.audiences):
            raise ValueError('Claimant audience and resources must be declared together.')
        return self


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


def new_realtime_event(
    *,
    claim_id: str,
    customer_id: str,
    occurred_at: datetime,
    resources: tuple[RealtimeResource, ...],
    claim_revision: int | None = None,
    sequence: int | None = None,
    operation_correlation: str | None = None,
    claimant_visible: bool = True,
    claimant_resources: tuple[RealtimeResource, ...] | None = None,
) -> RealtimeEvent:
    safe_resources = tuple(
        resource for resource in resources if resource in CLAIMANT_REALTIME_RESOURCES
    )
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
    return RealtimeEvent(
        event_id=new_id('rte'),
        occurred_at=occurred_at,
        claim_id=claim_id,
        customer_id=customer_id,
        claim_revision=claim_revision,
        sequence=sequence,
        operation_correlation=operation_correlation,
        resources=resources,
        claimant_resources=visible_resources,
        audiences=audiences,
    )

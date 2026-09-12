from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from backend.domain.models import ContractModel


class StaffAgentMessageRole(StrEnum):
    STAFF = 'staff'
    ASSISTANT = 'assistant'


class StaffAgentDraftKind(StrEnum):
    CLAIMANT_MESSAGE = 'claimant_message'
    INTERNAL_NOTE = 'internal_note'
    EXTERNAL_REQUEST = 'external_request'


class StaffAgentDraftExecutionOutcome(StrEnum):
    EXECUTED = 'executed'


class StaffAgentDraft(ContractModel):
    draft_id: str | None = Field(default=None, min_length=1, max_length=120)
    kind: StaffAgentDraftKind
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=5000)
    claim_id: str | None = None
    action_code: str | None = Field(
        default=None,
        pattern=r'^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$',
    )
    target_ref: str | None = Field(default=None, min_length=1, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)


class StaffAgentSession(ContractModel):
    session_id: str
    staff_id: str
    title: str = Field(min_length=1, max_length=200)
    model_profile_id: str = Field(default='qwen-local', min_length=1, max_length=100)
    created_at: datetime
    updated_at: datetime


class StaffAgentMessage(ContractModel):
    message_id: str
    session_id: str
    staff_id: str
    role: StaffAgentMessageRole
    content: str = Field(min_length=1, max_length=10000)
    claim_ids: list[str] = Field(default_factory=list, max_length=5)
    drafts: list[StaffAgentDraft] = Field(default_factory=list, max_length=5)
    source_refs: list[str] = Field(default_factory=list, max_length=100)
    in_reply_to: str | None = None
    client_message_id: str | None = Field(default=None, min_length=1, max_length=200)
    provider_model: str | None = Field(default=None, max_length=300)
    provider_request_id: str | None = Field(default=None, max_length=500)
    created_at: datetime


class StaffAgentExecutionRecord(ContractModel):
    """Immutable evidence that one confirmed draft used a registered handler."""

    execution_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=120)
    message_id: str = Field(min_length=1, max_length=120)
    draft_id: str = Field(min_length=1, max_length=120)
    staff_id: str = Field(min_length=1, max_length=120)
    claim_id: str = Field(min_length=1, max_length=120)
    action_code: str = Field(pattern=r'^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$')
    target_ref: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=1)
    resulting_revision: int = Field(ge=1)
    confirmation: str = Field(default='staff_confirmed', pattern='^staff_confirmed$')
    outcome: StaffAgentDraftExecutionOutcome
    result: dict[str, Any]
    source_refs: list[str] = Field(min_length=3, max_length=10)
    created_at: datetime


class CreateStaffAgentSessionRequest(ContractModel):
    title: str = Field(default='New Staff Agent session', min_length=1, max_length=200)
    model_profile_id: str | None = Field(default=None, min_length=1, max_length=100)


class CreateStaffAgentMessageRequest(ContractModel):
    client_message_id: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=5000)
    claim_ids: list[str] = Field(max_length=5)


class ExecuteStaffAgentDraftRequest(ContractModel):
    """Explicit staff confirmation and optional edits for one Agent draft."""

    confirmed: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)


class StaffAgentTurnResponse(ContractModel):
    session: StaffAgentSession
    staff_message: StaffAgentMessage
    assistant_message: StaffAgentMessage


class StaffAgentDraftExecutionResponse(ContractModel):
    session_id: str
    message_id: str
    draft_id: str
    claim_id: str
    action_code: str
    target_ref: str
    outcome: StaffAgentDraftExecutionOutcome
    result: dict[str, Any]
    runtime_execution: StaffAgentExecutionRecord


class StaffAgentSessionsResponse(ContractModel):
    items: list[StaffAgentSession]


class StaffAgentMessagesResponse(ContractModel):
    items: list[StaffAgentMessage]


class StaffAgentModelOutput(ContractModel):
    answer: str = Field(min_length=1, max_length=10000)
    drafts: list[StaffAgentDraft] = Field(default_factory=list, max_length=5)

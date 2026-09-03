from datetime import datetime
from enum import StrEnum

from pydantic import Field

from backend.domain.models import ContractModel


class StaffAgentMessageRole(StrEnum):
    STAFF = 'staff'
    ASSISTANT = 'assistant'


class StaffAgentDraftKind(StrEnum):
    CLAIMANT_MESSAGE = 'claimant_message'
    INTERNAL_NOTE = 'internal_note'
    EXTERNAL_REQUEST = 'external_request'


class StaffAgentDraft(ContractModel):
    kind: StaffAgentDraftKind
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=5000)
    claim_id: str | None = None


class StaffAgentSession(ContractModel):
    session_id: str
    staff_id: str
    title: str = Field(min_length=1, max_length=200)
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


class CreateStaffAgentSessionRequest(ContractModel):
    title: str = Field(default='New Staff Agent session', min_length=1, max_length=200)


class CreateStaffAgentMessageRequest(ContractModel):
    client_message_id: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=5000)
    claim_ids: list[str] = Field(max_length=5)


class StaffAgentTurnResponse(ContractModel):
    session: StaffAgentSession
    staff_message: StaffAgentMessage
    assistant_message: StaffAgentMessage


class StaffAgentSessionsResponse(ContractModel):
    items: list[StaffAgentSession]


class StaffAgentMessagesResponse(ContractModel):
    items: list[StaffAgentMessage]


class StaffAgentModelOutput(ContractModel):
    answer: str = Field(min_length=1, max_length=10000)
    drafts: list[StaffAgentDraft] = Field(default_factory=list, max_length=5)

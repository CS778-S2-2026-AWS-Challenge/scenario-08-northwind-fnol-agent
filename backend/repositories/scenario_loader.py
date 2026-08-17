import json
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from backend.domain.field_registry import REGISTERED_FIELD_CODES
from backend.domain.models import (
    ContractModel,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceState,
    EvidenceStatus,
    HandoffRecord,
    MessageRecord,
    SessionRecord,
    SessionStatus,
    WorkingClaim,
)
from backend.repositories.protocols import PersistenceRepository


class ScenarioFixture(ContractModel):
    scenario_id: str = Field(pattern=r'^AT-\d{2}-[a-z0-9-]+$')
    description: str = Field(min_length=1, max_length=500)
    claim: WorkingClaim
    sessions: list[SessionRecord] = Field(min_length=1)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    messages: list[MessageRecord] = Field(default_factory=list)
    handoffs: list[HandoffRecord] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_record_links(self) -> 'ScenarioFixture':
        session_ids = {session.session_id for session in self.sessions}
        if len(session_ids) != len(self.sessions):
            raise ValueError('Scenario session identifiers must be unique.')
        if self.claim.active_session_id not in session_ids:
            raise ValueError('The active session must be included in the scenario sessions.')
        if any(
            session.claim_id != self.claim.claim_id or session.customer_id != self.claim.customer_id
            for session in self.sessions
        ):
            raise ValueError('Every session must belong to the scenario claim and customer.')

        active_sessions = [
            session for session in self.sessions if session.status is SessionStatus.ACTIVE
        ]
        if len(active_sessions) != 1:
            raise ValueError('A scenario claim must contain exactly one active session.')
        if active_sessions[0].session_id != self.claim.active_session_id:
            raise ValueError('The claim active_session_id must identify the active session.')
        if any(session.context_revision > self.claim.revision for session in self.sessions):
            raise ValueError('Session context_revision cannot exceed the claim revision.')

        if any(record.claim_id != self.claim.claim_id for record in self.evidence):
            raise ValueError('Every evidence item must belong to the scenario claim.')
        if any(
            message.claim_id != self.claim.claim_id or message.session_id not in session_ids
            for message in self.messages
        ):
            raise ValueError('Every message must belong to a scenario session.')

        unregistered_form_fields = set(self.claim.form) - REGISTERED_FIELD_CODES
        if unregistered_form_fields:
            raise ValueError(
                'Unregistered form field codes on the scenario claim: '
                f'{sorted(unregistered_form_fields)}. Add them to backend/domain/field_registry.py.'
            )

        message_ids = {message.message_id for message in self.messages}
        handoff_ids = {handoff.handoff_id for handoff in self.handoffs}
        if len(handoff_ids) != len(self.handoffs):
            raise ValueError('Scenario handoff identifiers must be unique.')
        if any(handoff.claim_id != self.claim.claim_id for handoff in self.handoffs):
            raise ValueError('Every handoff must belong to the scenario claim.')
        if any(
            handoff.source_message_id is not None and handoff.source_message_id not in message_ids
            for handoff in self.handoffs
        ):
            raise ValueError('A handoff source_message_id must reference a scenario message.')

        unregistered_packet_fields = {
            field_code
            for handoff in self.handoffs
            for field_code in handoff.packet.form_snapshot
            if field_code not in REGISTERED_FIELD_CODES
        }
        if unregistered_packet_fields:
            raise ValueError(
                'Unregistered form field codes in a handoff packet snapshot: '
                f'{sorted(unregistered_packet_fields)}. '
                'Add them to backend/domain/field_registry.py.'
            )
        return self


class EvidenceLifecycleStage(str, Enum):
    PENDING = 'pending'
    UNOFFICIAL = 'unofficial'
    INCOMPLETE = 'incomplete'
    NOT_YET_GENERATED = 'not_yet_generated'
    RECEIVED = 'received'


class FixtureVisibility(str, Enum):
    CLAIMANT_VISIBLE = 'claimant_visible'
    SHARED = 'shared'
    INTERNAL_ONLY = 'internal_only'


class ExpectedEvidenceStateChange(ContractModel):
    trigger: str = Field(min_length=1, max_length=100)
    evidence_status: EvidenceStatus
    file_status: EvidenceFileStatus
    claim_evidence_state: EvidenceState


class EvidenceLifecycleCase(ContractModel):
    fixture_id: str = Field(pattern=r'^EV-\d{2}-[a-z0-9-]+$')
    lifecycle_stage: EvidenceLifecycleStage
    visibility: FixtureVisibility
    next_requirement: str = Field(min_length=1, max_length=500)
    evidence: EvidenceRecord
    expected_state_change: ExpectedEvidenceStateChange

    @model_validator(mode='after')
    def validate_lifecycle_stage(self) -> 'EvidenceLifecycleCase':
        pending_file_states = {
            EvidenceFileStatus.AWAITING_UPLOAD,
            EvidenceFileStatus.UPLOADING,
            EvidenceFileStatus.UPLOADED,
            EvidenceFileStatus.PROCESSING,
        }
        valid_start = {
            EvidenceLifecycleStage.UNOFFICIAL: self.evidence.status is EvidenceStatus.UNOFFICIAL,
            EvidenceLifecycleStage.NOT_YET_GENERATED: (
                self.evidence.status is EvidenceStatus.PENDING_GENERATION
                and self.evidence.file_status is EvidenceFileStatus.NOT_AVAILABLE
            ),
            EvidenceLifecycleStage.RECEIVED: (
                self.evidence.status is EvidenceStatus.RECEIVED
                and self.evidence.file_status is EvidenceFileStatus.READY
            ),
            EvidenceLifecycleStage.PENDING: (
                self.evidence.status is EvidenceStatus.INCOMPLETE
                and self.evidence.file_status in pending_file_states
            ),
            EvidenceLifecycleStage.INCOMPLETE: (
                self.evidence.status is EvidenceStatus.INCOMPLETE
                and self.evidence.file_status not in pending_file_states
            ),
        }
        if not valid_start[self.lifecycle_stage]:
            raise ValueError(
                f'{self.lifecycle_stage.value} fixture does not match its contract state.'
            )
        return self


class EvidenceLifecycleFixtureSet(ContractModel):
    fixture_set_id: str = Field(pattern=r'^evidence-lifecycle-v\d+$')
    description: str = Field(min_length=1, max_length=500)
    fixtures: list[EvidenceLifecycleCase] = Field(min_length=5, max_length=5)

    @model_validator(mode='after')
    def validate_fixture_set(self) -> 'EvidenceLifecycleFixtureSet':
        stages = {fixture.lifecycle_stage for fixture in self.fixtures}
        if stages != set(EvidenceLifecycleStage):
            raise ValueError('The fixture set must contain every evidence lifecycle stage once.')
        fixture_ids = {fixture.fixture_id for fixture in self.fixtures}
        if len(fixture_ids) != len(self.fixtures):
            raise ValueError('Evidence lifecycle fixture identifiers must be unique.')
        evidence_ids = {fixture.evidence.evidence_id for fixture in self.fixtures}
        if len(evidence_ids) != len(self.fixtures):
            raise ValueError('Evidence lifecycle evidence identifiers must be unique.')
        return self


def load_scenario(path: Path) -> ScenarioFixture:
    payload = json.loads(path.read_text(encoding='utf-8'))
    return ScenarioFixture.model_validate(payload)


def load_scenarios(directory: Path) -> list[ScenarioFixture]:
    return [load_scenario(path) for path in sorted(directory.glob('AT-*.json'))]


def load_evidence_lifecycle_fixtures(path: Path) -> EvidenceLifecycleFixtureSet:
    payload = json.loads(path.read_text(encoding='utf-8'))
    return EvidenceLifecycleFixtureSet.model_validate(payload)


def seed_scenario(
    repository: PersistenceRepository,
    scenario: ScenarioFixture,
) -> None:
    active_session = next(
        session
        for session in scenario.sessions
        if session.session_id == scenario.claim.active_session_id
    )
    repository.create_claim(scenario.claim, active_session)
    for session in scenario.sessions:
        if session.session_id != active_session.session_id:
            repository.save_session(session)
    for evidence in scenario.evidence:
        repository.save_evidence(evidence, scenario.claim.customer_id)
    for message in scenario.messages:
        repository.save_message(message, scenario.claim.customer_id)
    for handoff in scenario.handoffs:
        repository.save_handoff(handoff, scenario.claim.customer_id)

import json
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from backend.domain.evidence import (
    EvidenceLifecycleStage,
    evidence_state_for,
    evidence_summary_for,
    lifecycle_stage_for,
)
from backend.domain.field_registry import REGISTERED_FIELD_CODES
from backend.domain.models import (
    AgentAction,
    ClaimantEvidence,
    ClaimState,
    ContractModel,
    CustomerNextStep,
    CustomerUpdateRecord,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceState,
    EvidenceStatus,
    EvidenceSummary,
    HandoffPriority,
    HandoffRecord,
    HandoffStatus,
    HandoffTrigger,
    HandoffType,
    MessageRecord,
    ResponsibleParty,
    SessionRecord,
    SessionStatus,
    StaffActionRecord,
    StaffActionStatus,
    WorkflowState,
    WorkingClaim,
)
from backend.domain.retrieval import PolicyRetrievalRecord, RetrievalKind, RetrievalRecord
from backend.repositories.protocols import IdempotencyRecord, PersistenceRepository
from backend.services.retrieval_review import persist_retrieval_record

CANONICAL_SCENARIO_DIRECTORY = Path(__file__).resolve().parents[1] / 'demo_data' / 'scenarios'
SCENARIO_DERIVED_ENTRY_FIELDS = frozenset(
    {'claim_id', 'claim_state', 'customer_next_step', 'evidence_summary', 'handoffs'}
)


class LinkedMvpRecordBaseline(ContractModel):
    """Stable identifiers for one complete, API-served synthetic record graph."""

    customer_id: str = Field(min_length=1, max_length=100)
    claim_id: str = Field(min_length=1, max_length=100)
    policy_retrieval_id: str = Field(min_length=1, max_length=100)
    claim_history_retrieval_id: str = Field(min_length=1, max_length=100)
    evidence_ids: list[str] = Field(min_length=1)
    handoff_id: str = Field(min_length=1, max_length=100)
    message_ids: list[str] = Field(min_length=1)

    @model_validator(mode='after')
    def validate_unique_record_identifiers(self) -> 'LinkedMvpRecordBaseline':
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError('Linked MVP evidence identifiers must be unique.')
        if len(self.message_ids) != len(set(self.message_ids)):
            raise ValueError('Linked MVP message identifiers must be unique.')
        return self


class ScenarioFixture(ContractModel):
    scenario_id: str = Field(pattern=r'^AT-\d{2}-[a-z0-9-]+$')
    description: str = Field(min_length=1, max_length=500)
    claim: WorkingClaim
    sessions: list[SessionRecord] = Field(min_length=1)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    retrievals: list[RetrievalRecord] = Field(default_factory=list)
    messages: list[MessageRecord] = Field(default_factory=list)
    handoffs: list[HandoffRecord] = Field(default_factory=list)
    staff_actions: list[StaffActionRecord] = Field(default_factory=list)
    customer_updates: list[CustomerUpdateRecord] = Field(default_factory=list)
    linked_records: LinkedMvpRecordBaseline | None = None
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

        evidence_ids = {record.evidence_id for record in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError('Scenario evidence identifiers must be unique.')
        if any(record.claim_id != self.claim.claim_id for record in self.evidence):
            raise ValueError('Every evidence item must belong to the scenario claim.')
        if self.claim.claim_state.evidence is not evidence_state_for(self.evidence):
            raise ValueError(
                f'{self.scenario_id}: claim_state.evidence must derive from the '
                'scenario evidence records.'
            )
        if self.claim.evidence_summary != evidence_summary_for(self.evidence):
            raise ValueError(
                f'{self.scenario_id}: evidence_summary must derive from the '
                'scenario evidence records.'
            )
        retrieval_ids = {record.retrieval_id for record in self.retrievals}
        if len(retrieval_ids) != len(self.retrievals):
            raise ValueError('Scenario retrieval identifiers must be unique.')
        if any(record.claim_id != self.claim.claim_id for record in self.retrievals):
            raise ValueError('Every retrieval record must belong to the scenario claim.')
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
        if len(message_ids) != len(self.messages):
            raise ValueError('Scenario message identifiers must be unique.')
        if any(not set(message.evidence_refs).issubset(evidence_ids) for message in self.messages):
            raise ValueError('Every message evidence_ref must reference scenario evidence.')
        if any(
            message.in_reply_to is not None and message.in_reply_to not in message_ids
            for message in self.messages
        ):
            raise ValueError('Every message in_reply_to must reference a scenario message.')
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
        if any(
            not set(handoff.packet.evidence_refs).issubset(evidence_ids)
            for handoff in self.handoffs
        ):
            raise ValueError('Every handoff evidence_ref must reference scenario evidence.')

        policy_retrieval_ids = {
            record.retrieval_id for record in self.retrievals if record.kind is RetrievalKind.POLICY
        }
        history_retrieval_ids = {
            record.retrieval_id
            for record in self.retrievals
            if record.kind is RetrievalKind.CLAIM_HISTORY
        }
        if any(
            not set(handoff.packet.history_evidence_refs).issubset(history_retrieval_ids)
            for handoff in self.handoffs
        ):
            raise ValueError(
                'Every handoff history_evidence_ref must reference a scenario history retrieval.'
            )

        action_ids = {action.action_id for action in self.staff_actions}
        if len(action_ids) != len(self.staff_actions):
            raise ValueError('Scenario staff action identifiers must be unique.')
        if any(action.claim_id != self.claim.claim_id for action in self.staff_actions):
            raise ValueError('Every staff action must belong to the scenario claim.')
        if any(
            action.status is StaffActionStatus.COMPLETED
            and (
                action.result is None or action.completed_by is None or action.completed_at is None
            )
            for action in self.staff_actions
        ):
            raise ValueError(
                'Completed staff actions require an actor, result, and completion time.'
            )

        update_ids = {update.update_id for update in self.customer_updates}
        if len(update_ids) != len(self.customer_updates):
            raise ValueError('Scenario customer update identifiers must be unique.')
        if any(update.claim_id != self.claim.claim_id for update in self.customer_updates):
            raise ValueError('Every customer update must belong to the scenario claim.')
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

        linked = self.linked_records
        if linked is not None:
            expected_retrieval_ids = {
                linked.policy_retrieval_id,
                linked.claim_history_retrieval_id,
            }
            if (
                linked.customer_id != self.claim.customer_id
                or linked.claim_id != self.claim.claim_id
            ):
                raise ValueError(
                    'Linked MVP customer and claim identifiers must match Claim State.'
                )
            if expected_retrieval_ids != retrieval_ids:
                raise ValueError('Linked MVP policy and history identifiers must be complete.')
            if linked.policy_retrieval_id not in policy_retrieval_ids:
                raise ValueError('Linked MVP policy identifier must reference a policy retrieval.')
            if linked.claim_history_retrieval_id not in history_retrieval_ids:
                raise ValueError(
                    'Linked MVP history identifier must reference a claim-history retrieval.'
                )
            if set(linked.evidence_ids) != evidence_ids:
                raise ValueError('Linked MVP evidence identifiers must be complete.')
            if {linked.handoff_id} != handoff_ids:
                raise ValueError('Linked MVP handoff identifier must select the scenario handoff.')
            if set(linked.message_ids) != message_ids:
                raise ValueError('Linked MVP message identifiers must be complete.')

            linked_handoff = next(
                handoff for handoff in self.handoffs if handoff.handoff_id == linked.handoff_id
            )
            if linked.policy_retrieval_id not in linked_handoff.packet.source_refs:
                raise ValueError('Linked MVP handoff sources must reference the policy retrieval.')
            if linked.claim_history_retrieval_id not in linked_handoff.packet.history_evidence_refs:
                raise ValueError(
                    'Linked MVP handoff history must reference the claim-history retrieval.'
                )

            policy_record = next(
                record
                for record in self.retrievals
                if isinstance(record, PolicyRetrievalRecord)
                and record.retrieval_id == linked.policy_retrieval_id
            )
            policy_field = self.claim.form.get('policy.policy_number')
            if (
                policy_field is None
                or policy_field.value != policy_record.facts.policy_reference
                or policy_field.source.value != 'policy'
            ):
                raise ValueError(
                    'Linked MVP policy fact must reference the structured policy retrieval.'
                )
            if not any(
                policy_record.facts.policy_reference in citation
                for citation in linked_handoff.packet.policy_citation_refs
            ):
                raise ValueError('Linked MVP policy citation must identify the structured policy.')
        return self


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
        # The stage is resolved by the shared domain rule rather than a table
        # kept here, so a fixture cannot declare a stage the runtime would not
        # give the same record.
        if lifecycle_stage_for(self.evidence) is not self.lifecycle_stage:
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


class EvidenceBusinessPath(str, Enum):
    CLEAR = 'clear'
    PENDING = 'pending'
    URGENT = 'urgent'
    PROFESSIONAL_REVIEW = 'professional_review'
    HANDOFF = 'handoff'


class ExpectedPathHandoff(ContractModel):
    type: HandoffType
    status: HandoffStatus
    priority: HandoffPriority
    queue: str = Field(min_length=1, max_length=100)
    trigger: HandoffTrigger


class ScenarioEntryBaseline(ContractModel):
    workflow_state: WorkflowState
    next_action: AgentAction
    evidence_state: EvidenceState
    customer_next_step_status: str = Field(min_length=1, max_length=100)
    responsible_party: ResponsibleParty
    handoff: ExpectedPathHandoff | None = None


class VisibilityEvidenceFixture(ContractModel):
    fixture_id: str = Field(pattern=r'^EV-VIS-\d{2}-[a-z0-9-]+$')
    visibility: FixtureVisibility
    evidence: EvidenceRecord


class EvidencePathEntry(ContractModel):
    """A path entry whose evidence list is the complete effective evidence set."""

    scenario_id: str = Field(pattern=r'^AT-\d{2}-[a-z0-9-]+$')
    business_path: EvidenceBusinessPath
    description: str = Field(min_length=1, max_length=500)
    claim_id: str = Field(min_length=1, max_length=100)
    claim_state: ClaimState
    evidence_summary: EvidenceSummary
    customer_next_step: CustomerNextStep
    handoffs: list[HandoffRecord]
    entry_baseline: ScenarioEntryBaseline
    evidence: list[VisibilityEvidenceFixture] = Field(min_length=1)

    @model_validator(mode='after')
    def validate_entry_state(self) -> 'EvidencePathEntry':
        expected_action = {
            EvidenceBusinessPath.CLEAR: AgentAction.CREATE_CLAIM,
            EvidenceBusinessPath.PENDING: AgentAction.PROCEED,
            EvidenceBusinessPath.URGENT: AgentAction.URGENT_HANDOFF,
            EvidenceBusinessPath.PROFESSIONAL_REVIEW: AgentAction.HANDOFF,
            EvidenceBusinessPath.HANDOFF: AgentAction.HANDOFF,
        }
        required_action = expected_action[self.business_path]
        if self.entry_baseline.next_action is not required_action:
            raise ValueError(
                f'{self.business_path.value} baseline must use {required_action.value}.'
            )
        if self.claim_state.next_action is not self.entry_baseline.next_action:
            raise ValueError(
                f'{self.business_path.value} entry does not match its next-action baseline.'
            )
        if self.claim_state.workflow_state is not self.entry_baseline.workflow_state:
            raise ValueError(
                f'{self.business_path.value} entry does not match its workflow baseline.'
            )
        if self.claim_state.evidence is not self.entry_baseline.evidence_state:
            raise ValueError(
                f'{self.business_path.value} entry does not match its evidence-state baseline.'
            )
        if self.customer_next_step.status != self.entry_baseline.customer_next_step_status:
            raise ValueError(
                f'{self.business_path.value} entry does not match its customer-status baseline.'
            )
        if self.customer_next_step.responsible_party is not self.entry_baseline.responsible_party:
            raise ValueError(
                f'{self.business_path.value} entry does not match its responsibility baseline.'
            )

        expected_handoff = self.entry_baseline.handoff
        if expected_handoff is None:
            if self.handoffs:
                raise ValueError(f'{self.business_path.value} entry must not contain a handoff.')
        else:
            if len(self.handoffs) != 1:
                raise ValueError(
                    f'{self.business_path.value} entry must contain exactly one handoff.'
                )
            handoff = self.handoffs[0]
            actual_handoff = ExpectedPathHandoff(
                type=handoff.type,
                status=handoff.status,
                priority=handoff.priority,
                queue=handoff.queue,
                trigger=handoff.trigger,
            )
            if actual_handoff != expected_handoff:
                raise ValueError(
                    f'{self.business_path.value} entry does not match its handoff baseline.'
                )
        fixture_ids = {fixture.fixture_id for fixture in self.evidence}
        if len(fixture_ids) != len(self.evidence):
            raise ValueError('Path evidence fixture identifiers must be unique.')
        evidence_ids = {fixture.evidence.evidence_id for fixture in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError('Path evidence identifiers must be unique.')
        if any(fixture.evidence.claim_id != self.claim_id for fixture in self.evidence):
            raise ValueError('Every path evidence item must belong to the entry claim.')
        records = [fixture.evidence for fixture in self.evidence]
        if self.claim_state.evidence is not evidence_state_for(records):
            raise ValueError('Path evidence state must derive from the complete evidence set.')
        if self.evidence_summary != evidence_summary_for(records):
            raise ValueError('Path evidence summary must derive from the complete evidence set.')
        return self


class EvidencePathFixtureSet(ContractModel):
    fixture_set_id: str = Field(pattern=r'^evidence-path-visibility-v\d+$')
    description: str = Field(min_length=1, max_length=500)
    entries: list[EvidencePathEntry] = Field(min_length=5, max_length=5)

    @model_validator(mode='after')
    def validate_fixture_set(self) -> 'EvidencePathFixtureSet':
        paths = {entry.business_path for entry in self.entries}
        if paths != set(EvidenceBusinessPath):
            raise ValueError('The fixture set must contain every evidence business path once.')
        scenario_ids = {entry.scenario_id for entry in self.entries}
        if len(scenario_ids) != len(self.entries):
            raise ValueError('Evidence path scenario identifiers must be unique.')
        visibility_classes = {
            fixture.visibility for entry in self.entries for fixture in entry.evidence
        }
        if visibility_classes != set(FixtureVisibility):
            raise ValueError('The fixture set must contain every evidence visibility class.')
        return self


def load_scenario(path: Path) -> ScenarioFixture:
    payload = json.loads(path.read_text(encoding='utf-8'))
    return ScenarioFixture.model_validate(payload)


def load_scenarios(directory: Path) -> list[ScenarioFixture]:
    return [load_scenario(path) for path in sorted(directory.glob('AT-*.json'))]


def load_evidence_lifecycle_fixtures(path: Path) -> EvidenceLifecycleFixtureSet:
    payload = json.loads(path.read_text(encoding='utf-8'))
    return EvidenceLifecycleFixtureSet.model_validate(payload)


def load_evidence_path_fixtures(
    path: Path,
    scenario_directory: Path = CANONICAL_SCENARIO_DIRECTORY,
) -> EvidencePathFixtureSet:
    payload = json.loads(path.read_text(encoding='utf-8'))
    canonical_scenarios = {
        scenario.scenario_id: scenario for scenario in load_scenarios(scenario_directory)
    }
    for entry in payload.get('entries', []):
        duplicate_fields = SCENARIO_DERIVED_ENTRY_FIELDS.intersection(entry)
        if duplicate_fields:
            names = ', '.join(sorted(duplicate_fields))
            raise ValueError(
                f'Evidence path entries must derive canonical scenario fields: {names}.'
            )

        scenario_id = entry.get('scenario_id')
        scenario = canonical_scenarios.get(scenario_id)
        if scenario is None:
            raise ValueError(f'Unknown canonical scenario: {scenario_id}.')

        canonical_evidence = {record.evidence_id: record for record in scenario.evidence}
        raw_fixtures = entry.get('evidence', [])
        referenced_ids: list[str] = []
        for fixture in raw_fixtures:
            if 'evidence' in fixture:
                raise ValueError(
                    'Path evidence payloads must derive from the canonical scenario; '
                    'store only evidence_id and visibility in the path fixture.'
                )
            evidence_id = fixture.pop('evidence_id', None)
            if not isinstance(evidence_id, str) or not evidence_id:
                raise ValueError('Path evidence entries require a canonical evidence_id.')
            record = canonical_evidence.get(evidence_id)
            if record is None:
                raise ValueError(
                    f'{scenario_id}: path evidence_id {evidence_id} is not present '
                    'in the canonical scenario.'
                )
            referenced_ids.append(evidence_id)
            fixture['evidence'] = record.model_dump(mode='json')

        if len(referenced_ids) != len(set(referenced_ids)):
            raise ValueError(f'{scenario_id}: path evidence_id values must be unique.')
        if set(referenced_ids) != set(canonical_evidence):
            missing = sorted(set(canonical_evidence) - set(referenced_ids))
            extra = sorted(set(referenced_ids) - set(canonical_evidence))
            raise ValueError(
                f'{scenario_id}: path visibility must classify the complete canonical '
                f'evidence set; missing={missing or "none"}, extra={extra or "none"}.'
            )

        entry['claim_id'] = scenario.claim.claim_id
        entry['claim_state'] = scenario.claim.claim_state.model_dump(mode='json')
        entry['evidence_summary'] = scenario.claim.evidence_summary.model_dump(mode='json')
        entry['customer_next_step'] = scenario.claim.customer_next_step.model_dump(mode='json')
        entry['handoffs'] = [handoff.model_dump(mode='json') for handoff in scenario.handoffs]
    return EvidencePathFixtureSet.model_validate(payload)


def claimant_evidence_for(entry: EvidencePathEntry) -> list[ClaimantEvidence]:
    staff_only_fields = {
        'provenance',
        'wait_type',
        'responsible_party',
        'expected_by',
        'expected_timing',
        'context_summary',
    }
    return [
        ClaimantEvidence.model_validate(
            fixture.evidence.model_dump(exclude=staff_only_fields, mode='json')
        )
        for fixture in entry.evidence
        if fixture.visibility is not FixtureVisibility.INTERNAL_ONLY
    ]


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
    for retrieval in scenario.retrievals:
        persist_retrieval_record(repository, retrieval, scenario.claim.customer_id)
    for message in scenario.messages:
        repository.save_message(message, scenario.claim.customer_id)
    for handoff in scenario.handoffs:
        repository.save_handoff(handoff, scenario.claim.customer_id)
    # Scenario records represent already-audited staff history.  They are seeded
    # without changing the fixture claim revision, while retaining ordinary
    # repository ownership and idempotency checks.
    for action in scenario.staff_actions:
        repository.save_staff_mutation(
            scenario.claim,
            scenario.claim.revision,
            IdempotencyRecord(
                actor_id=action.completed_by or action.assigned_to,
                route='fixture://staff-actions',
                key=action.action_id,
                request_fingerprint=f'fixture-staff-action:{action.action_id}',
                claim_id=scenario.claim.claim_id,
                session_id=scenario.claim.active_session_id or '',
            ),
            staff_action=action,
        )
    for update in scenario.customer_updates:
        repository.save_staff_mutation(
            scenario.claim,
            scenario.claim.revision,
            IdempotencyRecord(
                actor_id=update.created_by,
                route='fixture://customer-updates',
                key=update.update_id,
                request_fingerprint=f'fixture-customer-update:{update.update_id}',
                claim_id=scenario.claim.claim_id,
                session_id=scenario.claim.active_session_id or '',
            ),
            customer_update=update,
        )

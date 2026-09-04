"""Versioned definitions for staff Workbench actions."""

from dataclasses import dataclass
from enum import StrEnum

from backend.domain.models import HandoffRecord, HandoffType, StaffActionRecord
from backend.domain.workbench import (
    ConfirmationLevel,
    WorkbenchActionInputControl,
)

WORKBENCH_ACTION_REGISTRY_VERSION = '2026-09-04.1'


class WorkbenchActionTargetType(StrEnum):
    CLAIM = 'claim'
    HANDOFF = 'handoff'
    SIGNAL = 'signal'
    WORK_ITEM = 'work_item'
    SESSION = 'session'
    COLLABORATION_REQUEST = 'collaboration_request'


class WorkbenchActionPermission(StrEnum):
    ANY_STAFF = 'any_staff'
    CLAIM_COLLABORATOR = 'claim_collaborator'
    PRIMARY_OWNER = 'primary_owner'
    ASSIGNED_WORKER = 'assigned_worker'
    REQUEST_DECIDER = 'request_decider'


@dataclass(frozen=True)
class RegisteredActionInput:
    field_code: str
    label: str
    control: WorkbenchActionInputControl
    required: bool = True
    choices: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RegisteredWorkbenchAction:
    action_code: str
    target_type: WorkbenchActionTargetType
    label: str
    purpose: str
    permission: WorkbenchActionPermission
    confirmation_level: ConfirmationLevel
    confirmation_message: str | None
    expected_effects: tuple[str, ...]
    inputs: tuple[RegisteredActionInput, ...] = ()
    claimant_visible_effects: tuple[str, ...] = ()
    failure_codes: tuple[str, ...] = (
        'ACCESS_DENIED',
        'REVISION_CONFLICT',
        'VALIDATION_ERROR',
    )
    audit_requirements: tuple[str, ...] = (
        'action_code',
        'target_ref',
        'actor_id',
        'resulting_revision',
    )


SIGNAL_DECISION_REASON_CHOICES = (
    ('CONFLICT_REQUIRES_REVIEW', 'Conflict requires review'),
    ('CLAIM_LEVEL_SIGNAL_CONFIRMED', 'Claim-level signal confirmed'),
    ('POLICY_SECTION_CONFIRMED', 'Policy section confirmed'),
    ('SOURCE_RECORD_NOT_COMPARABLE', 'Source record not comparable'),
    ('STAFF_CONFIRMED_INTERPRETATION_REQUIRED', 'Interpretation still required'),
    ('STAFF_CONFIRMED_REVIEW_REQUIREMENT', 'Review requirement confirmed'),
    ('STAFF_REVIEWED_SOURCE', 'Source reviewed'),
)


@dataclass(frozen=True)
class RegisteredWorkItemType:
    action_type: str
    label: str
    requested_outcome: str
    completion_outcome: str
    completion_reason_codes: tuple[str, ...]
    state_changes: tuple[tuple[str, str], ...]
    claimant_update_responsibility: str | None = None


WORK_ITEM_TYPE_REGISTRY = {
    item.action_type: item
    for item in (
        RegisteredWorkItemType(
            'claimant_support',
            'Claimant support',
            'Continue claimant support for this Claim.',
            'staff_work_completed',
            ('SUPPORT_NEED_MET',),
            (),
        ),
        RegisteredWorkItemType(
            'coverage_review',
            'Coverage review',
            'Review the applicable policy wording for this Claim.',
            'professional_review_completed',
            ('POLICY_SECTION_CONFIRMED',),
            (
                ('claim_state.coverage', 'clear'),
                ('claim_state.workflow_state', 'ready_for_next'),
            ),
            'claimant',
        ),
        RegisteredWorkItemType(
            'handoff_support',
            'Handoff support',
            'Complete the requested staff handoff support.',
            'staff_work_completed',
            ('SUPPORT_NEED_MET',),
            (),
        ),
        RegisteredWorkItemType(
            'professional_review',
            'Professional review',
            'Complete the requested professional review.',
            'professional_review_completed',
            ('POLICY_SECTION_CONFIRMED',),
            (
                ('claim_state.coverage', 'clear'),
                ('claim_state.workflow_state', 'ready_for_next'),
            ),
            'claimant',
        ),
    )
}


def _input(
    field_code: str,
    label: str,
    control: WorkbenchActionInputControl,
    *,
    required: bool = True,
    choices: tuple[tuple[str, str], ...] = (),
) -> RegisteredActionInput:
    return RegisteredActionInput(field_code, label, control, required, choices)


WORKBENCH_ACTION_REGISTRY = {
    item.action_code: item
    for item in (
        RegisteredWorkbenchAction(
            'human.accept_handoff',
            WorkbenchActionTargetType.HANDOFF,
            'Accept Claim',
            'Take responsibility for the requested staff work.',
            WorkbenchActionPermission.ANY_STAFF,
            ConfirmationLevel.EXPLICIT,
            'Accepting this Claim makes you responsible for the current handoff.',
            ('handoff.accept', 'ownership.assign'),
            claimant_visible_effects=('customer_next_step.update',),
        ),
        RegisteredWorkbenchAction(
            'conversation.send_claimant_message',
            WorkbenchActionTargetType.SESSION,
            'Reply to claimant',
            'Continue the accepted claimant conversation.',
            WorkbenchActionPermission.CLAIM_COLLABORATOR,
            ConfirmationLevel.EXPLICIT,
            'This message will be visible to the claimant.',
            ('message.append', 'handoff.mark_in_progress'),
            (
                _input(
                    'content.text', 'Claimant-visible message', WorkbenchActionInputControl.TEXTAREA
                ),
            ),
            ('message.append',),
        ),
        RegisteredWorkbenchAction(
            'human.resolve_handoff',
            WorkbenchActionTargetType.HANDOFF,
            'Resolve handoff',
            'Record the outcome and the claimant-safe next step.',
            WorkbenchActionPermission.PRIMARY_OWNER,
            ConfirmationLevel.EXPLICIT,
            'The recorded outcome will update the shared Claim context.',
            ('handoff.resolve', 'work_item.complete', 'claim.update', 'customer_update.append'),
            (
                _input(
                    'result.summary',
                    'Internal result summary',
                    WorkbenchActionInputControl.TEXTAREA,
                ),
                _input(
                    'customer_update.summary',
                    'Claimant update',
                    WorkbenchActionInputControl.TEXTAREA,
                ),
            ),
            ('customer_next_step.update', 'customer_update.append'),
        ),
        RegisteredWorkbenchAction(
            'signal.record_decision',
            WorkbenchActionTargetType.SIGNAL,
            'Record signal decision',
            'Record a source-linked decision for this exact review signal.',
            WorkbenchActionPermission.PRIMARY_OWNER,
            ConfirmationLevel.EXPLICIT,
            'This internal decision is audited and may change review work.',
            ('signal.decision.append', 'claim.revision.advance'),
            (
                _input(
                    'decision',
                    'Decision',
                    WorkbenchActionInputControl.SELECT,
                    choices=(
                        ('confirmed', 'Confirm for review'),
                        ('dismissed', 'Dismiss signal'),
                        ('overridden', 'Override signal'),
                        ('resolved', 'Resolve signal'),
                    ),
                ),
                _input(
                    'reason_codes.0',
                    'Reason',
                    WorkbenchActionInputControl.SELECT,
                    choices=SIGNAL_DECISION_REASON_CHOICES,
                ),
                _input('summary', 'Decision summary', WorkbenchActionInputControl.TEXTAREA),
            ),
        ),
        RegisteredWorkbenchAction(
            'work_item.create',
            WorkbenchActionTargetType.CLAIM,
            'Create registered work item',
            'Create a legacy-compatible WorkItem from a registered type.',
            WorkbenchActionPermission.CLAIM_COLLABORATOR,
            ConfirmationLevel.EXPLICIT,
            'The registered WorkItem will be assigned and audited.',
            ('work_item.create', 'claim.revision.advance'),
            (
                _input(
                    'action_type',
                    'Work type',
                    WorkbenchActionInputControl.SELECT,
                    choices=tuple(
                        (item.action_type, item.label) for item in WORK_ITEM_TYPE_REGISTRY.values()
                    ),
                ),
            ),
        ),
        RegisteredWorkbenchAction(
            'work_item.update',
            WorkbenchActionTargetType.WORK_ITEM,
            'Update assigned work',
            'Progress or complete this exact assigned WorkItem.',
            WorkbenchActionPermission.ASSIGNED_WORKER,
            ConfirmationLevel.EXPLICIT,
            'The selected status and any completion result will be audited.',
            ('work_item.update', 'claim.revision.advance'),
            (
                _input(
                    'status',
                    'Status',
                    WorkbenchActionInputControl.SELECT,
                    choices=(
                        ('in_progress', 'In progress'),
                        ('completed', 'Completed'),
                        ('cancelled', 'Cancelled'),
                    ),
                ),
                _input(
                    'result.summary',
                    'Result summary',
                    WorkbenchActionInputControl.TEXTAREA,
                    required=False,
                ),
            ),
            ('customer_next_step.update', 'customer_update.append'),
        ),
        RegisteredWorkbenchAction(
            'ownership.request_cowork',
            WorkbenchActionTargetType.CLAIM,
            'Request cowork access',
            'Ask the primary owner to collaborate on this Claim.',
            WorkbenchActionPermission.ANY_STAFF,
            ConfirmationLevel.EXPLICIT,
            'The current primary owner will receive this request.',
            ('collaboration_request.create',),
        ),
        RegisteredWorkbenchAction(
            'ownership.invite_cowork',
            WorkbenchActionTargetType.CLAIM,
            'Invite coworker',
            'Grant another staff member access after they accept the invitation.',
            WorkbenchActionPermission.PRIMARY_OWNER,
            ConfirmationLevel.EXPLICIT,
            'The invited staff member must accept before access changes.',
            ('collaboration_request.create',),
        ),
        RegisteredWorkbenchAction(
            'ownership.request_transfer',
            WorkbenchActionTargetType.CLAIM,
            'Request transfer',
            'Ask another staff member to become the primary owner.',
            WorkbenchActionPermission.PRIMARY_OWNER,
            ConfirmationLevel.EXPLICIT,
            'Ownership changes only after the target staff member accepts.',
            ('collaboration_request.create',),
        ),
        RegisteredWorkbenchAction(
            'ownership.requeue',
            WorkbenchActionTargetType.CLAIM,
            'Return to queue',
            'Release primary ownership when no protected work is active.',
            WorkbenchActionPermission.PRIMARY_OWNER,
            ConfirmationLevel.EXPLICIT,
            'This Claim will become available for another staff member.',
            ('ownership.release', 'queue.recompute'),
        ),
        RegisteredWorkbenchAction(
            'ownership.decide_cowork',
            WorkbenchActionTargetType.COLLABORATION_REQUEST,
            'Review cowork request',
            'Decide whether the requested staff member may collaborate on this Claim.',
            WorkbenchActionPermission.REQUEST_DECIDER,
            ConfirmationLevel.EXPLICIT,
            'Accepting this request changes Claim access and is audited.',
            ('ownership.cowork_grant',),
        ),
        RegisteredWorkbenchAction(
            'ownership.decide_transfer',
            WorkbenchActionTargetType.COLLABORATION_REQUEST,
            'Review transfer request',
            'Decide whether ownership should transfer to the requested staff member.',
            WorkbenchActionPermission.REQUEST_DECIDER,
            ConfirmationLevel.EXPLICIT,
            'Accepting this request changes Claim access and is audited.',
            ('ownership.transfer',),
        ),
    )
}


def get_workbench_action_definition(action_code: str) -> RegisteredWorkbenchAction:
    """Return the registered definition for an action code.

    Args:
        action_code: Stable Workbench action code.

    Returns:
        The immutable registered action definition.

    Raises:
        KeyError: The action code is not registered.
    """
    return WORKBENCH_ACTION_REGISTRY[action_code]


def handoff_resolution_defaults(handoff: HandoffRecord) -> dict[str, object]:
    """Build immutable fields for a registered handoff resolution.

    Args:
        handoff: Handoff targeted by the projected action.

    Returns:
        Fixed result, state-change, and claimant-update fields.
    """
    professional_review = handoff.type is HandoffType.PROFESSIONAL_REVIEW
    return {
        'result': {
            'outcome': (
                'professional_review_completed' if professional_review else 'support_completed'
            ),
            'reason_codes': [
                'POLICY_SECTION_CONFIRMED' if professional_review else 'SUPPORT_NEED_MET'
            ],
            'source_refs': handoff.packet.source_refs,
        },
        'state_changes': (
            [
                {'path': 'claim_state.coverage', 'to': 'clear'},
                {'path': 'claim_state.workflow_state', 'to': 'ready_for_next'},
            ]
            if professional_review
            else []
        ),
        'customer_update': {
            'responsible_party': 'claims_professional',
            'related_refs': [handoff.handoff_id],
        },
    }


def work_item_defaults(action: StaffActionRecord) -> dict[str, object]:
    """Build immutable fields for a registered WorkItem update.

    Args:
        action: WorkItem targeted by the projected action.

    Returns:
        Fixed result, state-change, and optional claimant-update fields.

    Raises:
        KeyError: The persisted WorkItem type is not registered.
    """
    definition = WORK_ITEM_TYPE_REGISTRY[action.action_type]
    customer_update = None
    if definition.claimant_update_responsibility is not None:
        customer_update = {
            'responsible_party': definition.claimant_update_responsibility,
            'related_refs': [action.action_id],
        }
    return {
        'result': {
            'outcome': definition.completion_outcome,
            'reason_codes': list(definition.completion_reason_codes),
            'source_refs': action.source_refs,
        },
        'state_changes': [{'path': path, 'to': value} for path, value in definition.state_changes],
        'customer_update': customer_update,
    }


__all__ = [
    'SIGNAL_DECISION_REASON_CHOICES',
    'WORKBENCH_ACTION_REGISTRY',
    'WORKBENCH_ACTION_REGISTRY_VERSION',
    'WORK_ITEM_TYPE_REGISTRY',
    'RegisteredActionInput',
    'RegisteredWorkItemType',
    'RegisteredWorkbenchAction',
    'WorkbenchActionPermission',
    'WorkbenchActionTargetType',
    'get_workbench_action_definition',
    'handoff_resolution_defaults',
    'work_item_defaults',
]

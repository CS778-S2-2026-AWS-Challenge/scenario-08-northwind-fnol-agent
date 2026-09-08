"""Build Control Plane action availability from persisted resource state."""

from collections.abc import Sequence

from backend.domain.admin_actions import AdminActionAvailability, AdminActionProjection
from backend.domain.admin_identity import AdminAccountSessionProjection, AdminSessionState
from backend.domain.configuration import (
    AdminConfigurationProjection,
    ApprovalDecision,
    ConfigurationApprovalRecord,
    ConfigurationRecord,
    ConfigurationState,
)
from backend.domain.identity import AdminCustomerAccountProjection
from backend.domain.integration_registry import IntegrationStatusProjection
from backend.domain.knowledge_admin import (
    AdminKnowledgeSourceProjection,
    KnowledgeSourceRecord,
    KnowledgeVersionState,
)
from backend.domain.release import AdminReleaseSetProjection, ReleaseSetRecord, ReleaseSetState
from backend.domain.staff_identity import AdminStaffAccountProjection


def _action(
    action_code: str,
    availability: AdminActionAvailability,
    revision: int | None = None,
    reason: str | None = None,
) -> AdminActionProjection:
    return AdminActionProjection(
        action_code=action_code,
        availability=availability,
        expected_revision=revision,
        reason=reason,
    )


def _state_action(
    action_code: str,
    allowed: bool,
    revision: int | None,
    *,
    confirmation: bool = False,
    blocked_reason: str,
) -> AdminActionProjection:
    if not allowed:
        return _action(action_code, AdminActionAvailability.BLOCKED, revision, blocked_reason)
    availability = (
        AdminActionAvailability.CONFIRMATION_REQUIRED
        if confirmation
        else AdminActionAvailability.AVAILABLE
    )
    return _action(action_code, availability, revision)


def configuration_projection(
    record: ConfigurationRecord,
    actor: str,
    approvals: Sequence[ConfigurationApprovalRecord],
) -> AdminConfigurationProjection:
    """Project valid configuration transitions for one authenticated administrator."""

    state = record.state
    awaiting = state is ConfigurationState.AWAITING_APPROVAL
    independent_approval = any(
        item.decision is ApprovalDecision.APPROVED and item.reviewer != record.author
        for item in approvals
    )
    actor_decided = any(item.reviewer == actor for item in approvals)
    actions = [
        _state_action(
            'admin.configuration.patch',
            state is ConfigurationState.DRAFT,
            record.revision,
            blocked_reason='Only a draft configuration can be edited.',
        ),
        _state_action(
            'admin.configuration.validate',
            state is ConfigurationState.DRAFT,
            record.revision,
            blocked_reason='Only a draft configuration can be validated.',
        ),
        _state_action(
            'admin.configuration.approve',
            awaiting and record.author != actor and not actor_decided,
            record.revision,
            confirmation=True,
            blocked_reason=(
                'The author cannot provide the independent review.'
                if awaiting and record.author == actor
                else 'This revision is not awaiting an independent decision.'
                if not awaiting
                else 'This administrator already recorded a decision for this revision.'
            ),
        ),
        _state_action(
            'admin.configuration.publish',
            awaiting and record.author != actor and independent_approval,
            record.revision,
            confirmation=True,
            blocked_reason=(
                'The author cannot publish this high-impact revision.'
                if awaiting and record.author == actor
                else 'A recorded independent approval is required.'
                if awaiting and not independent_approval
                else 'Only an approved awaiting-approval revision can be published.'
            ),
        ),
        _state_action(
            'admin.configuration.withdraw',
            state
            in {
                ConfigurationState.DRAFT,
                ConfigurationState.AWAITING_APPROVAL,
                ConfigurationState.PUBLISHED,
            },
            record.revision,
            confirmation=True,
            blocked_reason='This configuration cannot be withdrawn from its current state.',
        ),
        _state_action(
            'admin.configuration.rollback',
            state is ConfigurationState.PUBLISHED,
            record.revision,
            confirmation=True,
            blocked_reason='Only the active published configuration can be rolled back.',
        ),
    ]
    return AdminConfigurationProjection.model_validate(
        {**record.model_dump(mode='python'), 'allowed_actions': actions}
    )


def release_set_projection(record: ReleaseSetRecord) -> AdminReleaseSetProjection:
    """Project Release Set transitions from its persisted lifecycle state."""

    actions = [
        _state_action(
            'admin.release_set.validate',
            record.state is ReleaseSetState.DRAFT,
            record.revision,
            blocked_reason='Only a draft Release Set can be validated.',
        ),
        _state_action(
            'admin.release_set.publish',
            record.state is ReleaseSetState.VALIDATION,
            record.revision,
            confirmation=True,
            blocked_reason='Only a validated Release Set can be published.',
        ),
        _state_action(
            'admin.release_set.rollback',
            record.state is ReleaseSetState.PUBLISHED,
            record.revision,
            confirmation=True,
            blocked_reason='Only the active published Release Set can be rolled back.',
        ),
    ]
    return AdminReleaseSetProjection.model_validate(
        {**record.model_dump(mode='python'), 'allowed_actions': actions}
    )


def knowledge_projection(
    record: KnowledgeSourceRecord,
    actor: str,
) -> AdminKnowledgeSourceProjection:
    """Project knowledge lifecycle actions without exposing stored content."""

    state = record.state
    publishable = (
        state in {KnowledgeVersionState.INDEXED, KnowledgeVersionState.AWAITING_APPROVAL}
        and record.validation_evidence is not None
    )
    actions = [
        _state_action(
            'admin.knowledge.ingest',
            state in {KnowledgeVersionState.DRAFT, KnowledgeVersionState.FAILED},
            revision=None,
            blocked_reason='Only a draft or failed knowledge version can be ingested.',
        ),
        _state_action(
            'admin.knowledge.validate',
            state
            in {
                KnowledgeVersionState.DRAFT,
                KnowledgeVersionState.FAILED,
                KnowledgeVersionState.INDEXED,
            },
            revision=None,
            blocked_reason='This knowledge version cannot be validated from its current state.',
        ),
        _action(
            'admin.knowledge.retrieval_check',
            AdminActionAvailability.AVAILABLE,
        ),
        _state_action(
            'admin.knowledge.publish',
            publishable and record.author != actor,
            revision=None,
            confirmation=True,
            blocked_reason=(
                'The source author cannot publish this knowledge version.'
                if publishable and record.author == actor
                else 'The knowledge version must be indexed and validated before publication.'
            ),
        ),
        _state_action(
            'admin.knowledge.withdraw',
            state not in {KnowledgeVersionState.WITHDRAWN, KnowledgeVersionState.SUPERSEDED},
            revision=None,
            confirmation=True,
            blocked_reason='This knowledge version cannot be withdrawn from its current state.',
        ),
    ]
    return AdminKnowledgeSourceProjection.model_validate(
        {**record.model_dump(mode='python'), 'allowed_actions': actions}
    )


def customer_account_projection(
    record: AdminCustomerAccountProjection,
) -> AdminCustomerAccountProjection:
    return record.model_copy(
        update={
            'allowed_actions': [
                _action(
                    'admin.customer_account.update',
                    AdminActionAvailability.AVAILABLE,
                    record.revision,
                )
            ]
        }
    )


def staff_account_projection(
    record: AdminStaffAccountProjection,
) -> AdminStaffAccountProjection:
    return record.model_copy(
        update={
            'allowed_actions': [
                _action(
                    'admin.staff_account.update',
                    AdminActionAvailability.AVAILABLE,
                    record.revision,
                )
            ]
        }
    )


def integration_projection(record: IntegrationStatusProjection) -> IntegrationStatusProjection:
    return record.model_copy(
        update={
            'allowed_actions': [
                _action('admin.integration.health_check', AdminActionAvailability.AVAILABLE)
            ]
        }
    )


def account_session_projection(
    record: AdminAccountSessionProjection,
) -> AdminAccountSessionProjection:
    active = record.state is AdminSessionState.ACTIVE
    return record.model_copy(
        update={
            'allowed_actions': [
                _state_action(
                    'admin.account_session.revoke',
                    active,
                    record.revision,
                    confirmation=True,
                    blocked_reason='Only an active identity session can be revoked.',
                )
            ]
        }
    )

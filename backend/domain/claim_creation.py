import json
from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from hashlib import sha256

from pydantic import BaseModel, Field, model_validator

from backend.domain.models import EvidenceRecord, ExternalClaimResult, IntegrationSource


class ClaimCreationOperationStatus(str, Enum):
    PREPARED = 'prepared'
    SETTLEMENT_PENDING = 'settlement_pending'
    ACCEPTED = 'accepted'
    RETRYABLE_FAILURE = 'retryable_failure'
    TERMINAL_FAILURE = 'terminal_failure'
    UNKNOWN_OUTCOME = 'unknown_outcome'


class ClaimCreationFailureCode(str, Enum):
    TIMEOUT = 'timeout'
    UNAVAILABLE = 'unavailable'
    ACCESS_DENIED = 'access_denied'
    MALFORMED = 'malformed'
    CONFLICTING = 'conflicting'
    PARTIAL = 'partial'


class ClaimCreationDelivery(str, Enum):
    NOT_SUBMITTED = 'not_submitted'
    SUBMITTED = 'submitted'


class ClaimCreationRecovery(str, Enum):
    RETRY_SAME_OPERATION = 'retry_same_operation'
    RECONCILE_BEFORE_RETRY = 'reconcile_before_retry'
    SETTLE_RECORDED_RESULT = 'settle_recorded_result'
    REVIEW_REQUIRED = 'review_required'


_FAILURE_MATRIX: dict[
    tuple[ClaimCreationFailureCode, ClaimCreationDelivery],
    tuple[ClaimCreationOperationStatus, ClaimCreationRecovery],
] = {
    (ClaimCreationFailureCode.TIMEOUT, ClaimCreationDelivery.NOT_SUBMITTED): (
        ClaimCreationOperationStatus.RETRYABLE_FAILURE,
        ClaimCreationRecovery.RETRY_SAME_OPERATION,
    ),
    (ClaimCreationFailureCode.TIMEOUT, ClaimCreationDelivery.SUBMITTED): (
        ClaimCreationOperationStatus.UNKNOWN_OUTCOME,
        ClaimCreationRecovery.RECONCILE_BEFORE_RETRY,
    ),
    (ClaimCreationFailureCode.UNAVAILABLE, ClaimCreationDelivery.NOT_SUBMITTED): (
        ClaimCreationOperationStatus.RETRYABLE_FAILURE,
        ClaimCreationRecovery.RETRY_SAME_OPERATION,
    ),
    (ClaimCreationFailureCode.UNAVAILABLE, ClaimCreationDelivery.SUBMITTED): (
        ClaimCreationOperationStatus.UNKNOWN_OUTCOME,
        ClaimCreationRecovery.RECONCILE_BEFORE_RETRY,
    ),
    (ClaimCreationFailureCode.PARTIAL, ClaimCreationDelivery.NOT_SUBMITTED): (
        ClaimCreationOperationStatus.UNKNOWN_OUTCOME,
        ClaimCreationRecovery.RECONCILE_BEFORE_RETRY,
    ),
    (ClaimCreationFailureCode.PARTIAL, ClaimCreationDelivery.SUBMITTED): (
        ClaimCreationOperationStatus.UNKNOWN_OUTCOME,
        ClaimCreationRecovery.RECONCILE_BEFORE_RETRY,
    ),
    **{
        (code, delivery): (
            ClaimCreationOperationStatus.TERMINAL_FAILURE,
            ClaimCreationRecovery.REVIEW_REQUIRED,
        )
        for code in (
            ClaimCreationFailureCode.ACCESS_DENIED,
            ClaimCreationFailureCode.MALFORMED,
            ClaimCreationFailureCode.CONFLICTING,
        )
        for delivery in ClaimCreationDelivery
    },
}


def classify_claim_creation_failure(
    code: ClaimCreationFailureCode,
    delivery: ClaimCreationDelivery,
) -> tuple[ClaimCreationOperationStatus, ClaimCreationRecovery]:
    """Return the one authoritative no-duplicate failure classification."""

    return _FAILURE_MATRIX[(code, delivery)]


class ClaimCreationOperationRecord(BaseModel):
    operation_id: str = Field(min_length=1, max_length=100)
    claim_id: str = Field(min_length=1, max_length=100)
    customer_id: str = Field(min_length=1, max_length=100)
    authorised_decision_id: str = Field(min_length=1, max_length=100)
    authorised_revision: int = Field(ge=1)
    request_fingerprint: str = Field(min_length=64, max_length=64)
    evidence_snapshot_fingerprint: str = Field(min_length=64, max_length=64)
    route: str = Field(min_length=1, max_length=100)
    integration_source: IntegrationSource
    status: ClaimCreationOperationStatus
    delivery: ClaimCreationDelivery = ClaimCreationDelivery.NOT_SUBMITTED
    failure_code: ClaimCreationFailureCode | None = None
    recovery: ClaimCreationRecovery | None = None
    result: ExternalClaimResult | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode='after')
    def validate_state(self) -> 'ClaimCreationOperationRecord':
        if self.updated_at < self.created_at:
            raise ValueError('Claim creation operation time cannot move backwards.')
        if self.status is ClaimCreationOperationStatus.PREPARED:
            if (
                self.result is not None
                or self.failure_code is not None
                or self.recovery is not None
            ):
                raise ValueError('A prepared Claim creation operation has no outcome.')
            return self
        if self.status in {
            ClaimCreationOperationStatus.SETTLEMENT_PENDING,
            ClaimCreationOperationStatus.ACCEPTED,
        }:
            expected_recovery = (
                ClaimCreationRecovery.SETTLE_RECORDED_RESULT
                if self.status is ClaimCreationOperationStatus.SETTLEMENT_PENDING
                else None
            )
            if (
                self.result is None
                or self.failure_code is not None
                or self.recovery is not expected_recovery
                or self.delivery is not ClaimCreationDelivery.SUBMITTED
                or self.result.source is not self.integration_source
                or self.result.route != self.route
            ):
                raise ValueError(
                    'A recorded Claim creation result needs matching delivery and recovery.'
                )
            return self
        if self.result is not None or self.failure_code is None or self.recovery is None:
            raise ValueError('A failed Claim creation operation needs a classified failure.')
        expected_status, expected_recovery = classify_claim_creation_failure(
            self.failure_code,
            self.delivery,
        )
        if self.status is not expected_status or self.recovery is not expected_recovery:
            raise ValueError(
                'Claim creation failure code, delivery, status, and recovery conflict.'
            )
        return self


def claim_creation_operation_id(claim_id: str, decision_id: str) -> str:
    digest = sha256(f'{claim_id}:{decision_id}'.encode()).hexdigest()[:24]
    return f'cco_{digest}'


def evidence_snapshot_fingerprint(evidence: Sequence[EvidenceRecord]) -> str:
    payload = [
        item.model_dump(mode='json')
        for item in sorted(evidence, key=lambda record: record.evidence_id)
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return sha256(canonical.encode()).hexdigest()


def assert_claim_creation_operation_transition(
    current: ClaimCreationOperationRecord,
    updated: ClaimCreationOperationRecord,
) -> None:
    ClaimCreationOperationRecord.model_validate(updated.model_dump())
    immutable_fields = (
        'operation_id',
        'claim_id',
        'customer_id',
        'authorised_decision_id',
        'authorised_revision',
        'request_fingerprint',
        'evidence_snapshot_fingerprint',
        'route',
        'integration_source',
        'created_at',
    )
    if any(getattr(current, name) != getattr(updated, name) for name in immutable_fields):
        raise ValueError('Claim creation operation identity is immutable.')
    if updated.updated_at < current.updated_at:
        raise ValueError('Claim creation operation time cannot move backwards.')
    if current == updated:
        return
    allowed = {
        ClaimCreationOperationStatus.PREPARED: {
            ClaimCreationOperationStatus.SETTLEMENT_PENDING,
            ClaimCreationOperationStatus.RETRYABLE_FAILURE,
            ClaimCreationOperationStatus.TERMINAL_FAILURE,
            ClaimCreationOperationStatus.UNKNOWN_OUTCOME,
        },
        ClaimCreationOperationStatus.RETRYABLE_FAILURE: {
            ClaimCreationOperationStatus.PREPARED,
        },
        ClaimCreationOperationStatus.UNKNOWN_OUTCOME: {
            ClaimCreationOperationStatus.SETTLEMENT_PENDING,
            ClaimCreationOperationStatus.UNKNOWN_OUTCOME,
        },
        ClaimCreationOperationStatus.SETTLEMENT_PENDING: {
            ClaimCreationOperationStatus.ACCEPTED,
        },
        ClaimCreationOperationStatus.ACCEPTED: set(),
        ClaimCreationOperationStatus.TERMINAL_FAILURE: set(),
    }
    if updated.status not in allowed[current.status]:
        raise ValueError('Claim creation operation transition is not permitted.')

"""Logical storage key templates kept private to persistence adapters."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LogicalKey:
    partition: str
    sort: str


def claim_key(claim_id: str) -> LogicalKey:
    return LogicalKey(partition=f'CLAIM#{claim_id}', sort='CLAIM')


def session_key(claim_id: str, session_id: str) -> LogicalKey:
    return LogicalKey(partition=f'CLAIM#{claim_id}', sort=f'SESSION#{session_id}')


def message_key(claim_id: str, created_at: str, message_id: str) -> LogicalKey:
    return LogicalKey(
        partition=f'CLAIM#{claim_id}',
        sort=f'MESSAGE#{created_at}#{message_id}',
    )


def evidence_key(claim_id: str, evidence_id: str) -> LogicalKey:
    return LogicalKey(partition=f'CLAIM#{claim_id}', sort=f'EVIDENCE#{evidence_id}')


def customer_claim_index_key(customer_id: str, created_at: str, claim_id: str) -> LogicalKey:
    return LogicalKey(
        partition=f'CUSTOMER#{customer_id}',
        sort=f'CLAIM#{created_at}#{claim_id}',
    )

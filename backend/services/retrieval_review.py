from backend.domain.retrieval import (
    RetrievalKind,
    RetrievalRecord,
    ReviewSignalRecord,
)
from backend.repositories.protocols import PersistenceRepository


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def review_signal_for_retrieval(record: RetrievalRecord) -> ReviewSignalRecord | None:
    """Map explicit retrieval uncertainty to a staff-only professional-review signal."""

    if not record.uncertainty:
        return None

    if record.kind is RetrievalKind.POLICY:
        code = 'POLICY_RETRIEVAL_UNCERTAINTY'
        subject = 'Policy retrieval'
    else:
        code = 'CLAIM_HISTORY_RETRIEVAL_UNCERTAINTY'
        subject = 'Claim-history retrieval'

    reason_codes = _dedupe([item.code for item in record.uncertainty])
    detail = '; '.join(item.detail for item in record.uncertainty)
    summary = f'{subject} requires professional review because: {detail}'[:1000]
    return ReviewSignalRecord(
        signal_id=f'sig_{record.retrieval_id}',
        claim_id=record.claim_id,
        code=code,
        source_refs=_dedupe([record.retrieval_id, record.source.reference]),
        reason_codes=reason_codes,
        summary=summary,
        created_at=record.source.retrieved_at,
    )


def persist_retrieval_record(
    repository: PersistenceRepository,
    record: RetrievalRecord,
    customer_id: str,
) -> list[ReviewSignalRecord]:
    """Persist one provider-neutral retrieval and any review-only signals atomically."""

    signal = review_signal_for_retrieval(record)
    signals = [signal] if signal is not None else []
    repository.save_retrieval_bundle(record, signals, customer_id)
    return signals

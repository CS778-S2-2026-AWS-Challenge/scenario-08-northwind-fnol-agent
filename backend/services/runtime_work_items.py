"""Reconcile immutable Runtime WorkItem evidence into a current projection."""

from collections.abc import Iterable

from backend.domain.models import FormStatus, WorkingClaim
from backend.domain.runtime import RuntimeWorkItemRecord
from backend.repositories.protocols import PersistenceRepository


def _subject_is_recorded(claim: WorkingClaim, subject_ref: str) -> bool:
    field = claim.form.get(subject_ref)
    if field is not None:
        if field.status in {
            FormStatus.CONFIRMED,
            FormStatus.DISPUTED,
            FormStatus.SUPERSEDED,
            FormStatus.UNAVAILABLE,
        }:
            return True
        if field.value not in (None, '', [], {}):
            return True
        if any(assertion.reported_text for assertion in field.assertions):
            return True
    return any(item.item_id == subject_ref for item in claim.contents_items)


def _latest_by_subject(items: Iterable[RuntimeWorkItemRecord]) -> list[RuntimeWorkItemRecord]:
    latest: dict[str, RuntimeWorkItemRecord] = {}
    for item in items:
        current = latest.get(item.subject_ref)
        if current is None or (item.updated_at, item.work_item_id) >= (
            current.updated_at,
            current.work_item_id,
        ):
            latest[item.subject_ref] = item
    return sorted(latest.values(), key=lambda item: (item.updated_at, item.work_item_id))


def current_runtime_work_items(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> list[RuntimeWorkItemRecord]:
    """Return one reconciled item per subject without creating a second Claim state.

    Runtime WorkItems are immutable turn evidence. The current projection is derived
    from the latest subject record and the authoritative Claim form, so answering a
    question closes the corresponding item without a synthetic frontend mutation.
    """

    items: list[RuntimeWorkItemRecord] = []
    for item in _latest_by_subject(
        repository.list_runtime_work_items(claim.claim_id, claim.customer_id)
    ):
        if item.status in {'cancelled', 'unavailable'}:
            items.append(item)
            continue
        if item.status == 'completed' or _subject_is_recorded(claim, item.subject_ref):
            items.append(
                item.model_copy(
                    update={
                        'status': 'completed',
                        'completed_at': item.completed_at or item.updated_at,
                    }
                )
            )
            continue
        items.append(item)
    return items

from backend.domain.external_services import ExternalTaskRecord, ExternalTaskRequest
from backend.domain.models import ContractModel, PageInfo


class ExternalTaskItem(ContractModel):
    """Operational task state with its request and material-origin links."""

    task: ExternalTaskRecord
    request: ExternalTaskRequest | None = None
    evidence_ids: list[str]


class ExternalTaskListResponse(ContractModel):
    """Internal projection of external tasks and their material links."""

    claim_id: str
    items: list[ExternalTaskItem]
    page: PageInfo

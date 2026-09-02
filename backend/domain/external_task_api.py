from backend.domain.external_services import ExternalTaskEvidenceView
from backend.domain.models import ContractModel, PageInfo


class ExternalTaskListResponse(ContractModel):
    """Internal projection of external tasks and their material links."""

    claim_id: str
    items: list[ExternalTaskEvidenceView]
    page: PageInfo

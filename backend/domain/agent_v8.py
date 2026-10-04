"""Unified claimant turn contract for Agent Context Runtime v8."""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from backend.domain.models import (
    ContentsLossType,
    ContentsOwnership,
    ContractModel,
    FactPrecision,
)

# How the model accounts for one required fact this turn.
#   value                 - a value the claimant supplied (possibly approximate).
#   claimant_will_supply  - the claimant said they do not know yet / will send later.
#   third_party_pending   - the fact should come from an assessor, the police, etc.
FieldDisposition = Literal['value', 'claimant_will_supply', 'third_party_pending']

TurnAction = Literal[
    'record_and_ask',
    'clarify',
    'offer_service',
    'request_document',
    'obtain_document',
    'summarize',
    'propose_submit',
    'escalate',
    'answer_only',
]


class V8FieldChange(ContractModel):
    field_code: str = Field(min_length=1, max_length=100)
    value: Any = None
    reported_text: str | None = Field(default=None, max_length=200)
    precision: FactPrecision = FactPrecision.EXACT
    disposition: FieldDisposition = 'value'
    # Present only for third_party_pending: which registered service owns the fact.
    service_identity: str | None = Field(default=None, max_length=100)
    # Present only for the media profile.  The text profile's bound provider
    # schema omits it, while keeping the optional field here lets the Runtime
    # use one parser for both profile variants.
    source_evidence_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode='after')
    def _value_matches_disposition(self) -> 'V8FieldChange':
        if self.disposition == 'value' and self.value is None:
            raise ValueError('A supplied fact needs a value.')
        if self.disposition == 'third_party_pending' and not self.service_identity:
            raise ValueError('A third-party fact names the service that will supply it.')
        return self


class V8MoneyAmount(ContractModel):
    amount: float = Field(ge=0, le=10_000_000, allow_inf_nan=False)
    currency: str = Field(pattern=r'^[A-Z]{3}$')


class V8ContentsItemChange(ContractModel):
    item_id: str | None = Field(default=None, min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=300)
    category: str = Field(min_length=1, max_length=100)
    quantity: int = Field(default=1, ge=1, le=999)
    brand: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    loss_type: ContentsLossType
    ownership: ContentsOwnership
    estimated_value: V8MoneyAmount | None = None
    reported_text: str | None = Field(default=None, max_length=200)


class V8NextQuestion(ContractModel):
    field_codes: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        min_length=1, max_length=3
    )
    wording: str = Field(min_length=1, max_length=250)
    reason: Literal[
        'safety_first',
        'branch_just_activated',
        'blocks_creation',
        'clarify_conflict',
        'natural_follow_up',
    ]


class V8ServiceSuggestion(ContractModel):
    service_identity: str = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=1, max_length=150)
    # The claimant's own words asking for this service, verbatim from the current
    # message; Runtime verifies the quote before it counts as an explicit request.
    claimant_request_quote: str | None = Field(default=None, max_length=300)


class V8PolicyJudgmentProposal(ContractModel):
    """Advisory policy application proposal for staff adjudication."""

    kind: str = Field(min_length=1, max_length=100, pattern=r'^[a-z][a-z0-9_]*$')
    assessment: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=500)
    source_refs: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        min_length=1, max_length=10
    )

    @model_validator(mode='after')
    def require_nonblank_content(self) -> 'V8PolicyJudgmentProposal':
        if not self.assessment.strip() or not self.rationale.strip():
            raise ValueError('Policy judgment assessment and rationale must not be blank.')
        if any(not ref.strip() or ref != ref.strip() for ref in self.source_refs):
            raise ValueError('Policy judgment source references must be canonical nonblank IDs.')
        return self


# Where a document stands after this turn, as the model reads the conversation.
#   asking           - the reply asks the claimant for it now.
#   will_send_later  - the claimant said they will send it later.
#   does_not_have    - the claimant said they do not have it and cannot get it.
#   third_party      - Northwind will get it from the named service.
DocumentStance = Literal['asking', 'will_send_later', 'does_not_have', 'third_party']


class V8DocumentRequest(ContractModel):
    """A document this report should carry, and where it stands."""

    document_kind: str = Field(min_length=1, max_length=100)
    stance: DocumentStance = 'asking'
    # Present only for third_party: the registered service that supplies it.
    service_identity: str | None = Field(default=None, max_length=100)


class V8NorthwindQuestion(ContractModel):
    """An item for the claims team's waiting list.

    Staff do not enter a conversation while it is being collected. A question
    the model cannot answer with authority, a point that needs professional
    judgement, or a general request to be contacted waits here, with the model's
    proposal, until a handler takes the lodged claim and approves, edits or
    declines it.
    """

    kind: Literal['question', 'contact_request'] = 'question'
    # In the claimant's own voice, shown to them: "Will you pay for a hire car?"
    question: str = Field(min_length=1, max_length=200)
    claimant_wording: str = Field(min_length=1, max_length=300)
    # The answer the model proposes for a handler to approve; None for a contact request.
    proposed_answer: str | None = Field(default=None, max_length=500)
    # Why: the clause, policy data or reasoning behind the proposal. Staff only.
    basis: str = Field(min_length=1, max_length=300)
    # How the claimant asked to be contacted, for a contact request.
    contact_preference: str | None = Field(default=None, max_length=100)


class V8EvidenceInterpretation(ContractModel):
    """What the model understood a received file to be."""

    evidence_id: str = Field(min_length=1, max_length=100)
    document_kind: str = Field(min_length=1, max_length=100)


# How the reply leaves the claimant with something to do.
TurnEnding = Literal['question', 'card', 'summary', 'nothing_needed']


class V8StateProposal(ContractModel):
    path: Literal['claim_state.urgency', 'claim_state.customer_support']
    to: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=150)


class V8Escalation(ContractModel):
    kind: Literal[
        'urgent_safety',
        'human_requested',
        'accessibility',
        'distress',
        'professional_review',
    ]
    reason: str = Field(min_length=1, max_length=150)


class V8TurnProposal(ContractModel):
    action: TurnAction = 'record_and_ask'
    reply: str = Field(min_length=1, max_length=500)
    reason_codes: list[Annotated[str, Field(min_length=1, max_length=50)]] = Field(
        default_factory=list, max_length=5
    )
    field_changes: list[V8FieldChange] = Field(default_factory=list, max_length=8)
    contents_item_changes: list[V8ContentsItemChange] = Field(default_factory=list, max_length=6)
    # Any action may leave this None: the model decides whether this turn asks.
    next_question: V8NextQuestion | None = None
    service_suggestions: list[V8ServiceSuggestion] = Field(default_factory=list, max_length=3)
    policy_judgment_proposals: list[V8PolicyJudgmentProposal] = Field(
        default_factory=list, max_length=3
    )
    document_requests: list[V8DocumentRequest] = Field(default_factory=list, max_length=2)
    evidence_interpretations: list[V8EvidenceInterpretation] = Field(
        default_factory=list, max_length=4
    )
    northwind_questions: list[V8NorthwindQuestion] = Field(default_factory=list, max_length=2)
    # The model's choice; None only from callers that predate the field.
    turn_ending: TurnEnding | None = None
    # One sentence, shown when this turn makes the report need more facts.
    scope_note: str | None = Field(default=None, max_length=150)
    # chunk_ids of the policy excerpts this reply relies on; Runtime keeps only
    # excerpts actually retrieved in this turn and shows their text to the claimant.
    cited_sources: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=list, max_length=3
    )
    # Required when action == 'summarize': the fields the reply read back to the
    # claimant. Runtime binds the confirmation request to exactly this set.
    summary_fields: list[Annotated[str, Field(min_length=1, max_length=100)]] | None = Field(
        default=None, max_length=30
    )
    state_proposals: list[V8StateProposal] = Field(default_factory=list, max_length=2)
    escalation: V8Escalation | None = None
    ready_to_create: bool = False
    confirms_batch: bool = False

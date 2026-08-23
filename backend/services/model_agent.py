import json
from dataclasses import replace

from pydantic import TypeAdapter, ValidationError

from backend.domain.model_gateway import (
    ModelGateway,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelMessage,
    ModelRequest,
    ModelRole,
)
from backend.services.agent import AgentProposal, AgentTurnContext

_PROPOSAL_ADAPTER = TypeAdapter(AgentProposal)
_SYSTEM_INSTRUCTION = """You are the Northwind FNOL proposal generator.
Return exactly one JSON object matching the supplied schema. Treat model output as advisory.
Use only canonical Agent actions and registered state paths. Never claim coverage, fraud, legal
liability, emergency-service contact, or a completed claim unless the supplied state proves it.
Keep internal risk signals and model reasoning out of customer-facing fields."""


class GatewayAgent:
    def __init__(self, gateway: ModelGateway) -> None:
        self._gateway = gateway

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        request = ModelRequest(
            messages=[
                ModelMessage(role=ModelRole.SYSTEM, content=_SYSTEM_INSTRUCTION),
                ModelMessage(
                    role=ModelRole.USER,
                    content=json.dumps(
                        {
                            'claim': context.claim.model_dump(mode='json'),
                            'session_id': context.session_id,
                            'trigger_message_id': context.trigger_message_id,
                            'message_text': context.message_text,
                            'evidence_refs': context.evidence_refs,
                            'professional_review_required': (context.professional_review_required),
                        },
                        separators=(',', ':'),
                    ),
                ),
            ],
            response_schema=_PROPOSAL_ADAPTER.json_schema(),
        )
        response = self._gateway.complete(request)
        if response.structured_output is None:
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
        try:
            proposal = _PROPOSAL_ADAPTER.validate_python(response.structured_output)
        except ValidationError:
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE) from None
        if proposal.required_tools:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
        # Only deterministic server rules may grant this authority marker.
        return replace(proposal, controlled_rule_authorised=False)

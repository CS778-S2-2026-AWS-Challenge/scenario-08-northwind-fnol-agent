"""Provider-neutral read tools exposed to the Agent Runtime.

Tool contracts are deliberately separate from the namespaced Action Registry. A tool
returns a bounded observation; it does not grant authority to mutate Claim State.
"""

from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field


class AgentToolContract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    name: str = Field(pattern=r'^[a-z]+\.[a-z][a-z0-9_]*$')
    description: str = Field(min_length=1, max_length=500)
    input_schema: dict[str, object]
    purpose: str = Field(min_length=1, max_length=120)
    read_only: bool = True


AGENT_TOOL_REGISTRY = MappingProxyType(
    {
        'claim.read': AgentToolContract(
            name='claim.read',
            description='Read the latest authorised Claim State for the current claimant session.',
            purpose='claimant_status_and_context',
            input_schema={
                'type': 'object',
                'properties': {},
                'required': [],
                'additionalProperties': False,
            },
        ),
    }
)


def tool_contract(name: str) -> AgentToolContract:
    try:
        return AGENT_TOOL_REGISTRY[name]
    except KeyError as error:
        raise ValueError(f'Unknown Agent tool: {name}.') from error

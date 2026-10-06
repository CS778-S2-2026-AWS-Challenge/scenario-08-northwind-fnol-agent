"""INV-16: on a model-authored turn, Runtime adds no words of its own to the reply.

The claimant hears the model. The only Runtime text allowed in front of it is
the safety notice. Field codes, template questions and confirmation dumps never
reach the conversation.
"""

import ast
import inspect
import re
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from backend.domain.branch_registry import build_default_registry
from backend.domain.intake import INTAKE_REQUIREMENTS
from backend.repositories.fixture import FixtureRepository
from backend.services import turn_reducer
from tests.journey_v8_support import Journey, V8JourneyProvider
from tests.test_journey_v8_contents import agent_turn_provider as contents_provider
from tests.test_journey_v8_home import agent_turn_provider as home_provider
from tests.test_journey_v8_motor import agent_turn_provider as motor_provider

# Sentences Runtime used to splice into model replies. None may appear again.
RETIRED_RUNTIME_PHRASES = (
    'Please confirm these details:',
    'Please review the remaining details in your form.',
    'I can also help arrange',
    'see the option below',
    'Northwind support has your request. You can keep adding details here.',
    'You can answer when you are ready; your support request will continue.',
    'I have saved what you shared. Northwind may follow up on the remaining information.',
    'I have two different versions of an incident detail.',
    'I have recorded your message.',
)

FIELD_CODE = re.compile(r'\b[a-z_]+\.[a-z_]+\b')


def test_compose_reply_returns_only_safety_notice_and_model_words() -> None:
    source = inspect.getsource(turn_reducer.compose_reply)
    tree = ast.parse(source)
    returns = [node for node in ast.walk(tree) if isinstance(node, ast.Return)]
    # The model-authored early return happens before any template append.
    assert (
        any(
            isinstance(node.value, ast.Call) and 'model_authored' in segment
            for node in returns
            if (segment := ast.get_source_segment(source, node)) is not None
        )
        or 'if model_authored:' in source
    )


@pytest.mark.parametrize(
    'provider_factory',
    [motor_provider, home_provider, contents_provider],
    ids=['motor', 'home', 'contents'],
)
def test_fixture_journeys_expose_no_runtime_text_or_field_codes(
    client: TestClient,
    repository: FixtureRepository,
    provider_factory: Callable[[], V8JourneyProvider],
) -> None:
    provider = cast(Callable[[], V8JourneyProvider], inspect.unwrap(provider_factory))()
    scripted = [
        response.structured_output['reply']
        for response in provider.gateway.responses
        if response.structured_output is not None
    ]
    family = provider_factory.__module__.rsplit('_', 1)[-1]
    client.app.state.agent_turn_provider = provider  # type: ignore[attr-defined]
    journey = Journey(client, family, f'inv16-{family}')
    scripts = {
        'motor': [
            'My car was rear-ended on Queen St yesterday around 3pm, bumper damaged, '
            'need an assessor',
            'No one was hurt',
            'Actually my passenger has a sore neck',
            "Just the passenger, she says it's minor, no ambulance",
            "Can't drive it, can you get a tow?",
        ],
        'home': [
            'A pipe burst in my bathroom last night in Wellington and flooded the lounge.',
            'No one was hurt but water is still dripping from the ceiling.',
            '12 Example Street, Wellington. The lounge ceiling and wall are affected; '
            'we can still live here.',
            'Yes all correct.',
        ],
        'contents': [
            'My laptop was stolen from my house in Wellington yesterday afternoon. '
            'No one was hurt.',
            'The back window was forced open; I found out at 8am today. '
            'It was one Laptop computer that I own, an Example Laptop 13, worth NZD 1000.',
            'Yes all correct.',
        ],
    }[family]
    registered = set(build_default_registry().field_codes) | set(INTAKE_REQUIREMENTS)
    templates = {item.prompt for item in INTAKE_REQUIREMENTS.values()}
    for index, text in enumerate(scripts):
        # A past injury stays a fact; every scripted turn continues through
        # the model, including the later motor injury and towing details.
        turn = journey.send(text)
        reply = turn['agent_message']['content']['text']
        for phrase in RETIRED_RUNTIME_PHRASES:
            assert phrase not in reply, (index, phrase, reply)
        assert not (set(FIELD_CODE.findall(reply)) & registered), (index, reply)
        assert not any(template in reply for template in templates), (index, reply)
        # Everything the claimant reads is the scripted model reply, optionally
        # preceded by the fixed safety notice.
        assert any(reply.endswith(candidate) for candidate in scripted), (index, reply)


def test_no_module_splices_claimant_text_outside_compose_reply() -> None:
    root = Path(turn_reducer.__file__).parent
    offenders: list[str] = []
    for path in (root / 'turn_reducer.py', root / 'turn_proposal_validation.py'):
        text = path.read_text(encoding='utf-8')
        for phrase in RETIRED_RUNTIME_PHRASES:
            if phrase in text and phrase not in (
                'Northwind support has your request. You can keep adding details here.',
                'You can answer when you are ready; your support request will continue.',
                'I have two different versions of an incident detail.',
            ):
                offenders.append(f'{path.name}: {phrase}')
    assert offenders == [], offenders

from importlib.resources import files

CLAIMANT_V8_PROMPT_ID = 'northwind-fnol-claimant-v8'
STAFF_ASSISTANT_PROMPT_ID = 'northwind-fnol-staff-assistant-v1'


def load_staff_assistant_prompt() -> str:
    prompt = (
        files(__package__)
        .joinpath('northwind_fnol_staff_assistant_v1.md')
        .read_text(encoding='utf-8')
    )
    if f'Prompt ID: `{STAFF_ASSISTANT_PROMPT_ID}`' not in prompt:
        raise RuntimeError('The Staff Assistant prompt ID does not match its runtime identifier.')
    return prompt

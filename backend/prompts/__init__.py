from importlib.resources import files

MOTOR_CLAIMANT_PROMPT_ID = 'northwind-fnol-motor-claimant-v4'
STAFF_ASSISTANT_PROMPT_ID = 'northwind-fnol-staff-assistant-v1'


def load_motor_claimant_prompt() -> str:
    prompt = (
        files(__package__)
        .joinpath('northwind_fnol_motor_claimant_v4.md')
        .read_text(encoding='utf-8')
    )
    if f'Prompt ID: `{MOTOR_CLAIMANT_PROMPT_ID}`' not in prompt:
        raise RuntimeError('The Motor claimant prompt ID does not match its runtime identifier.')
    return prompt


def load_staff_assistant_prompt() -> str:
    prompt = (
        files(__package__)
        .joinpath('northwind_fnol_staff_assistant_v1.md')
        .read_text(encoding='utf-8')
    )
    if f'Prompt ID: `{STAFF_ASSISTANT_PROMPT_ID}`' not in prompt:
        raise RuntimeError('The Staff Assistant prompt ID does not match its runtime identifier.')
    return prompt

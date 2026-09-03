from importlib.resources import files

MOTOR_CLAIMANT_PROMPT_ID = 'northwind-fnol-motor-claimant-v3'


def load_motor_claimant_prompt() -> str:
    prompt = (
        files(__package__)
        .joinpath('northwind_fnol_motor_claimant_v3.md')
        .read_text(encoding='utf-8')
    )
    if f'Prompt ID: `{MOTOR_CLAIMANT_PROMPT_ID}`' not in prompt:
        raise RuntimeError('The Motor claimant prompt ID does not match its runtime identifier.')
    return prompt

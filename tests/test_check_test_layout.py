from scripts.check_test_layout import advice

EXISTING = ['tests/test_retention_contract.py', 'tests/test_claim_api.py']


def test_process_named_file_gets_advice() -> None:
    for name in (
        'test_pr975_profile',
        'test_issue_928_agreement',
        'test_week5_rag',
        'test_turn_v8',
    ):
        assert advice([f'tests/{name}.py'], EXISTING), name


def test_file_extending_an_existing_test_file_gets_advice() -> None:
    messages = advice(['tests/test_retention_contract_edges.py'], EXISTING)

    assert messages == [
        'tests/test_retention_contract_edges.py: extends tests/test_retention_contract.py; '
        'add these cases there unless they test a different module.'
    ]


def test_behaviour_named_file_and_non_test_files_get_none() -> None:
    assert (
        advice(['tests/test_triage.py', 'tests/journey_runs/engine.py', 'docs/x.md'], EXISTING)
        == []
    )

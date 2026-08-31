import subprocess


def test_customer_chat_stays_inside_claim_detail() -> None:
    completed = subprocess.run(
        ['node', 'tests/employee_navigation.test.mjs'],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr

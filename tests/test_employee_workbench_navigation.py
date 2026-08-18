import subprocess


def test_direct_customer_chat_url_returns_to_workbench_without_leaving_page() -> None:
    completed = subprocess.run(
        ['node', 'tests/employee_navigation.test.mjs'],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr

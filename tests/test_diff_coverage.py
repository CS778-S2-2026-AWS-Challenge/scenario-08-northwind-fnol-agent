import json
from pathlib import Path

import pytest

from scripts.check_diff_coverage import changed_backend_lines, diff_coverage, main


def test_changed_backend_lines_tracks_added_lines_and_ignores_non_backend_files() -> None:
    diff = """\
diff --git a/backend/example.py b/backend/example.py
--- a/backend/example.py
+++ b/backend/example.py
@@ -1,2 +1,4 @@
 old()
+new()
+newer()
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1,2 @@
+documentation
"""

    assert changed_backend_lines(diff) == {'backend/example.py': {2, 3}}


def test_changed_backend_lines_ignores_deleted_lines() -> None:
    diff = """\
diff --git a/backend/example.py b/backend/example.py
--- a/backend/example.py
+++ b/backend/example.py
@@ -1,3 +1,2 @@
 kept()
-removed()
+replacement()
"""

    assert changed_backend_lines(diff) == {'backend/example.py': {2}}


def test_diff_coverage_counts_only_executable_changed_lines() -> None:
    coverage = {
        'files': {
            'backend/example.py': {
                'executed_lines': [2],
                'missing_lines': [3],
            }
        }
    }

    assert diff_coverage(coverage, {'backend/example.py': {1, 2, 3, 4}}) == (
        1,
        2,
        {'backend/example.py': [3]},
    )


def test_main_skips_non_backend_diff_and_fails_uncovered_changed_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / 'coverage.json'
    report.write_text(
        json.dumps(
            {
                'files': {
                    'backend/example.py': {
                        'executed_lines': [],
                        'missing_lines': [2],
                    }
                }
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(
        'scripts.check_diff_coverage._git_diff',
        lambda _base: (
            'diff --git a/backend/example.py b/backend/example.py\n'
            '--- a/backend/example.py\n'
            '+++ b/backend/example.py\n'
            '@@ -1 +1,2 @@\n'
            ' old()\n'
            '+new()\n'
        ),
    )
    assert main(['--coverage', str(report), '--min', '80']) == 1

    report.write_text(
        json.dumps(
            {
                'files': {
                    'backend/example.py': {
                        'executed_lines': [2],
                        'missing_lines': [],
                    }
                }
            }
        ),
        encoding='utf-8',
    )
    assert main(['--coverage', str(report), '--min', '80']) == 0

    monkeypatch.setattr(
        'scripts.check_diff_coverage._git_diff',
        lambda _base: (
            'diff --git a/README.md b/README.md\n'
            '--- a/README.md\n'
            '+++ b/README.md\n'
            '@@ -1 +1,2 @@\n'
            ' existing\n'
            '+docs\n'
        ),
    )
    assert main(['--coverage', str(report)]) == 0

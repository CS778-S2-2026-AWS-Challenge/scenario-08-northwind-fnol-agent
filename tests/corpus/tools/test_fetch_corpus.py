import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest

from tests.corpus.tools import fetch_corpus


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _setup(tmp_path: Path, tamper: bool = False) -> tuple[Path, Path]:
    """A controlled folder with a committed manifest, and a release zip of the same files."""
    pack_bytes = b'{"facts": {}}\n'
    manifest = {
        'corpus_files': [{'path': 'sampling.json', 'sha256': _sha(b'{}\n')}],
        'packs': [
            {
                'case_id': 'CTL-X-001',
                'files': [{'path': 'cases/CTL-X-001/input/facts.json', 'sha256': _sha(pack_bytes)}],
            }
        ],
    }
    controlled = tmp_path / 'controlled'
    (controlled / 'v1').mkdir(parents=True)
    (controlled / 'v1' / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    asset = tmp_path / 'packs.zip'
    with zipfile.ZipFile(asset, 'w') as archive:
        archive.writestr('controlled/v1/manifest.json', json.dumps(manifest))
        archive.writestr('controlled/v1/sampling.json', '{}\n')
        archive.writestr(
            'controlled/v1/cases/CTL-X-001/input/facts.json',
            b'{"facts": {"x": 1}}\n' if tamper else pack_bytes,
        )
    release = {
        'repository': 'owner/repo',
        'tag': 'corpus-test',
        'asset': 'packs.zip',
        'sha256': _sha(asset.read_bytes()),
        'corpora': ['v1'],
    }
    (controlled / 'release.json').write_text(json.dumps(release), encoding='utf-8')
    return controlled, asset


def _fake_gh(asset: Path, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(command: list[str], check: bool) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        target = Path(command[command.index('--dir') + 1]) / asset.name
        target.write_bytes(asset.read_bytes())
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, 'run', run)
    return calls


def test_installs_packs_when_every_hash_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controlled, asset = _setup(tmp_path)
    calls = _fake_gh(asset, monkeypatch)

    assert fetch_corpus.main(['--dest', str(controlled)]) == 0

    assert calls[0][:4] == ['gh', 'release', 'download', 'corpus-test']
    facts: Any = json.loads(
        (controlled / 'v1' / 'cases' / 'CTL-X-001' / 'input' / 'facts.json').read_text()
    )
    assert facts == {'facts': {}}
    assert (controlled / 'v1' / 'sampling.json').is_file()


def test_changes_nothing_when_the_asset_hash_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controlled, asset = _setup(tmp_path)
    release = json.loads((controlled / 'release.json').read_text(encoding='utf-8'))
    release['sha256'] = '0' * 64
    (controlled / 'release.json').write_text(json.dumps(release), encoding='utf-8')
    _fake_gh(asset, monkeypatch)

    assert fetch_corpus.main(['--dest', str(controlled)]) == 1

    assert not (controlled / 'v1' / 'cases').exists()


def test_changes_nothing_when_a_pack_file_was_altered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controlled, asset = _setup(tmp_path, tamper=True)
    _fake_gh(asset, monkeypatch)

    assert fetch_corpus.main(['--dest', str(controlled)]) == 1

    assert not (controlled / 'v1' / 'cases').exists()

import hashlib
import json
import os
import subprocess
import warnings
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.corpus.tools import fetch_corpus

PACK_FILE = 'cases/CTL-X-001/input/facts.json'
NEW_FACTS = b'{"facts": {}}\n'
OLD_FACTS = b'{"facts": {"old": true}}\n'


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _setup(
    tmp_path: Path,
    *,
    corpora: tuple[str, ...] = ('v1',),
    tamper: bool = False,
    extra: str | None = None,
    drop_listed: bool = False,
    duplicate: bool = False,
    old_install: bool = False,
    pack_path: str = PACK_FILE,
) -> tuple[Path, Path]:
    """A controlled folder with committed manifests, and a release zip built for them.

    The committed manifests are indented and the released ones are not, so a test can tell
    whether the committed bytes were kept.
    """
    controlled = tmp_path / 'controlled'
    asset = tmp_path / 'packs.zip'
    with zipfile.ZipFile(asset, 'w') as archive:
        for corpus in corpora:
            manifest = {
                'corpus_files': [{'path': 'sampling.json', 'sha256': _sha(b'{}\n')}],
                'packs': [
                    {
                        'case_id': 'CTL-X-001',
                        'files': [{'path': pack_path, 'sha256': _sha(NEW_FACTS)}],
                    }
                ],
            }
            (controlled / corpus).mkdir(parents=True)
            (controlled / corpus / 'manifest.json').write_text(
                json.dumps(manifest, indent=2), encoding='utf-8'
            )
            if old_install:
                old = controlled / corpus / pack_path
                old.parent.mkdir(parents=True)
                old.write_bytes(OLD_FACTS)
                (controlled / corpus / 'sampling.json').write_bytes(b'{"old": true}\n')
                (controlled / corpus / 'stale.txt').write_bytes(b'from an older version\n')
            archive.writestr(f'controlled/{corpus}/manifest.json', json.dumps(manifest))
            archive.writestr(f'controlled/{corpus}/sampling.json', '{}\n')
            if not drop_listed:
                content = b'{"x": 1}\n' if tamper else NEW_FACTS
                archive.writestr(f'controlled/{corpus}/{pack_path}', content)
        if duplicate:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                archive.writestr(f'controlled/{corpora[0]}/sampling.json', '{}\n')
        if extra:
            archive.writestr(extra, b'' if extra.endswith('/') else b'not in the manifest\n')
    release = {
        'repository': 'owner/repo',
        'tag': 'corpus-test',
        'asset': 'packs.zip',
        'sha256': _sha(asset.read_bytes()),
        'corpora': list(corpora),
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


def _failing_swap(
    destination_suffix: str, error: BaseException, *, after_move: bool = False
) -> Callable[[Path, Path], None]:
    """A swap that fails when it moves something to the given destination.

    With after_move the rename happens first, as when Ctrl+C lands just after it.
    """
    real_replace = os.replace  # bound now, so a test may break os.replace for the rollback only

    def swap(source: Path, destination: Path) -> None:
        if str(destination).replace('\\', '/').endswith(destination_suffix):
            if after_move:
                real_replace(source, destination)
            raise error
        real_replace(source, destination)

    return swap


def _snapshot(folder: Path) -> dict[str, bytes | None]:
    """Every path under the folder, with file bytes, so before and after compare exactly."""
    return {
        str(p.relative_to(folder)).replace('\\', '/'): (p.read_bytes() if p.is_file() else None)
        for p in sorted(folder.rglob('*'))
    }


def test_installs_exactly_the_manifest_files_over_an_earlier_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controlled, asset = _setup(tmp_path, corpora=('v1', 'v2'), old_install=True)
    calls = _fake_gh(asset, monkeypatch)
    manifests = {c: (controlled / c / 'manifest.json').read_bytes() for c in ('v1', 'v2')}

    assert fetch_corpus.main(['--dest', str(controlled)]) == 0

    assert calls[0][:4] == ['gh', 'release', 'download', 'corpus-test']
    files = sorted(k for k, v in _snapshot(controlled).items() if v is not None)
    expected = ['release.json']
    for corpus in ('v1', 'v2'):
        expected += [f'{corpus}/{PACK_FILE}', f'{corpus}/manifest.json', f'{corpus}/sampling.json']
    assert files == sorted(expected)
    assert not any(p.name.startswith('.') for p in controlled.iterdir())
    for corpus in ('v1', 'v2'):
        assert (controlled / corpus / PACK_FILE).read_bytes() == NEW_FACTS
        assert (controlled / corpus / 'manifest.json').read_bytes() == manifests[corpus]


def test_changes_nothing_when_the_asset_hash_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controlled, asset = _setup(tmp_path)
    release = json.loads((controlled / 'release.json').read_text(encoding='utf-8'))
    release['sha256'] = '0' * 64
    (controlled / 'release.json').write_text(json.dumps(release), encoding='utf-8')
    _fake_gh(asset, monkeypatch)
    before = _snapshot(controlled)

    assert fetch_corpus.main(['--dest', str(controlled)]) == 1

    assert _snapshot(controlled) == before


def test_changes_nothing_when_a_pack_file_was_altered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controlled, asset = _setup(tmp_path, tamper=True)
    _fake_gh(asset, monkeypatch)
    before = _snapshot(controlled)

    assert fetch_corpus.main(['--dest', str(controlled)]) == 1

    assert _snapshot(controlled) == before


@pytest.mark.parametrize(
    ('extra', 'message'),
    [
        # An unlisted file inside a pack, where the claimant simulator reads its input.
        ('controlled/v1/cases/CTL-X-001/input/unlisted.txt', 'not in the committed manifests'),
        # A corpus folder that release.json does not name.
        ('controlled/v2/manifest.json', 'not in the committed manifests'),
        # Folder entries: an extra pack, a letter-case variant of a listed pack (one folder on a
        # case-insensitive filesystem), and a folder with the name of a listed file.
        ('controlled/v1/cases/CTL-X-999/', 'folder entry'),
        ('controlled/v1/cases/ctl-x-001/', 'folder entry'),
        ('controlled/v1/sampling.json/', 'folder entry'),
    ],
)
def test_changes_nothing_when_the_asset_holds_a_member_no_manifest_lists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: str,
    message: str,
) -> None:
    controlled, asset = _setup(tmp_path, extra=extra)
    _fake_gh(asset, monkeypatch)
    before = _snapshot(controlled)

    assert fetch_corpus.main(['--dest', str(controlled)]) == 1

    assert message in capsys.readouterr().err
    assert _snapshot(controlled) == before


def test_changes_nothing_when_a_listed_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    controlled, asset = _setup(tmp_path, drop_listed=True)
    _fake_gh(asset, monkeypatch)
    before = _snapshot(controlled)

    assert fetch_corpus.main(['--dest', str(controlled)]) == 1

    assert 'listed file(s) missing' in capsys.readouterr().err
    assert _snapshot(controlled) == before


def test_changes_nothing_when_a_member_is_repeated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    controlled, asset = _setup(tmp_path, duplicate=True)
    _fake_gh(asset, monkeypatch)
    before = _snapshot(controlled)

    assert fetch_corpus.main(['--dest', str(controlled)]) == 1

    assert 'appears more than once' in capsys.readouterr().err
    assert _snapshot(controlled) == before


@pytest.mark.parametrize(
    'pack_path',
    [
        # A drive letter would make the hash check read a file outside the extracted folder.
        'C:/Windows/win.ini',
        # Windows drops a trailing dot, so the installed name would differ from the listed one.
        'cases/CTL-X-001./input/facts.json',
    ],
)
def test_refuses_a_manifest_path_that_is_not_plain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    pack_path: str,
) -> None:
    controlled, asset = _setup(tmp_path, pack_path=pack_path)
    _fake_gh(asset, monkeypatch)
    before = _snapshot(controlled)

    assert fetch_corpus.main(['--dest', str(controlled)]) == 1

    assert 'not a plain relative path' in capsys.readouterr().err
    assert _snapshot(controlled) == before


@pytest.mark.parametrize(
    ('destination', 'error', 'after_move'),
    [
        # Fails while placing the second corpus, after the first is fully swapped in.
        ('v2/sampling.json', OSError('injected failure'), False),
        # Ctrl+C just before, and just after, a rename in the middle of the first corpus: while
        # the previous files are moved aside, and while the new files are put in place.
        ('v1/sampling.json', KeyboardInterrupt(), False),
        ('.v1.previous/sampling.json', KeyboardInterrupt(), True),
        ('v1/cases', KeyboardInterrupt(), True),
    ],
)
def test_puts_every_previous_file_back_when_a_swap_fails_or_is_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    destination: str,
    error: BaseException,
    after_move: bool,
) -> None:
    controlled, asset = _setup(tmp_path, corpora=('v1', 'v2'), old_install=True)
    _fake_gh(asset, monkeypatch)
    before = _snapshot(controlled)
    monkeypatch.setattr(
        fetch_corpus, 'swap', _failing_swap(destination, error, after_move=after_move)
    )

    if isinstance(error, KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            fetch_corpus.main(['--dest', str(controlled)])
    else:
        assert fetch_corpus.main(['--dest', str(controlled)]) == 1

    assert _snapshot(controlled) == before


def test_keeps_the_backup_and_names_it_when_putting_files_back_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    controlled, asset = _setup(tmp_path, old_install=True)
    _fake_gh(asset, monkeypatch)
    monkeypatch.setattr(fetch_corpus, 'swap', _failing_swap('v1/sampling.json', OSError('x')))

    def refuse(source: object, destination: object) -> None:
        raise OSError('injected restore failure')

    monkeypatch.setattr(os, 'replace', refuse)

    assert fetch_corpus.main(['--dest', str(controlled)]) == 2

    error = capsys.readouterr().err
    backup = controlled / '.v1.previous'
    assert 'putting the previous files back failed' in error
    assert str(backup) in error
    assert (backup / PACK_FILE).read_bytes() == OLD_FACTS


def test_refuses_to_start_while_an_earlier_backup_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    controlled, asset = _setup(tmp_path)
    calls = _fake_gh(asset, monkeypatch)
    backup = controlled / '.v1.previous'
    backup.mkdir()
    (backup / 'sampling.json').write_bytes(b'{"kept": true}\n')
    before = _snapshot(controlled)

    assert fetch_corpus.main(['--dest', str(controlled)]) == 2

    assert str(backup) in capsys.readouterr().err
    assert calls == []
    assert _snapshot(controlled) == before

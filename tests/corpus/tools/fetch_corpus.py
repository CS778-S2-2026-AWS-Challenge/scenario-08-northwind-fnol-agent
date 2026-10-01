"""Download the controlled corpus packs from their GitHub release and verify every file.

Usage (from the repository root):
  python -m tests.corpus.tools.fetch_corpus [--dest DIR]

The packs are not in the Git history (Discussion #1153). `release.json` names the release tag and
asset and gives the asset's SHA-256. Each corpus folder holds a committed `manifest.json` that
lists every pack file with its SHA-256. The script:

1. refuses to start while a staging or backup folder from an earlier interrupted run exists;
2. downloads the asset with the GitHub CLI (the repository is private, so `gh auth login` first);
3. checks the asset's SHA-256;
4. checks, before extracting anything, that the asset holds exactly the files the committed
   manifests list plus the manifests themselves: no folder entry and no extra, missing or
   repeated member;
5. extracts it to a temporary folder and checks every file's SHA-256 against the manifest;
6. installs the files in two phases: it first stages every corpus beside its destination, then
   swaps the staged files in. If a swap step fails or is interrupted, the files that were there
   before are put back. A backup that could not be put back is kept and named.

On any verification failure it stops and changes nothing. The committed manifests are never
replaced.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

HERE = Path(__file__).resolve().parent
CONTROLLED = HERE.parent / 'controlled'
MANIFEST = 'manifest.json'
# A path segment that extracts to the same name on every system: no characters zipfile or Windows
# rewrite, and no trailing dot or space, which Windows drops.
SAFE_SEGMENT = re.compile(r'^[^\\/:*?"<>|\x00-\x1f]*[^\\/:*?"<>|\x00-\x1f. ]$')


class VerificationError(Exception):
    """The downloaded asset or one of its files does not match what the repository records."""


class RestoreError(Exception):
    """An install step failed or was interrupted, and the previous files are not all back."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def manifest_files(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Every file a corpus manifest lists: the corpus-level files and each pack's files."""
    files: list[dict[str, Any]] = list(manifest.get('corpus_files', []))
    for pack in manifest.get('packs', []):
        files.extend(pack.get('files', []))
    return files


def plain_relative(path: str, what: str) -> str:
    """Refuse a corpus name or manifest path that could leave its folder or change its name."""
    segments = path.split('/')
    if not path or any(s in ('', '.', '..') or not SAFE_SEGMENT.match(s) for s in segments):
        raise VerificationError(f'{what} {path!r} is not a plain relative path')
    return path


def staging_folders(controlled: Path, corpus: str) -> tuple[Path, Path]:
    return controlled / f'.{corpus}.incoming', controlled / f'.{corpus}.previous'


def expected_members(release: dict[str, Any], controlled: Path) -> set[str]:
    """The archive paths the asset must hold: each corpus's listed files and its manifest."""
    members: set[str] = set()
    for corpus in release['corpora']:
        plain_relative(corpus, 'corpus name')
        members.add(f'controlled/{corpus}/{MANIFEST}')
        for entry in manifest_files(load_json(controlled / corpus / MANIFEST)):
            members.add(f'controlled/{corpus}/{plain_relative(entry["path"], "manifest path")}')
    return members


def download(release: dict[str, Any], folder: Path) -> Path:
    command = [
        'gh',
        'release',
        'download',
        release['tag'],
        '--repo',
        release['repository'],
        '--pattern',
        release['asset'],
        '--dir',
        str(folder),
    ]
    subprocess.run(command, check=True)
    return folder / str(release['asset'])


def check_members(archive: zipfile.ZipFile, expected: set[str], label: str) -> None:
    """Refuse an archive whose members differ in any way from the committed manifests."""
    names = archive.namelist()
    for name in names:
        if name.startswith('/') or '\\' in name or '..' in PurePosixPath(name).parts:
            raise VerificationError(f'{label}: unsafe path {name!r}')
        if name.endswith('/'):
            # The release holds files only; a folder entry could add an unlisted folder or
            # change the letter case of a listed one on a case-insensitive filesystem.
            raise VerificationError(f'{label}: folder entry {name!r} is not allowed')
    if len(names) != len(set(names)):
        raise VerificationError(f'{label}: an archive member appears more than once')
    unexpected = sorted(set(names) - expected)
    if unexpected:
        raise VerificationError(
            f'{label}: {len(unexpected)} file(s) not in the committed manifests, '
            f'for example {unexpected[0]!r}'
        )
    missing = sorted(expected - set(names))
    if missing:
        raise VerificationError(
            f'{label}: {len(missing)} listed file(s) missing, for example {missing[0]!r}'
        )


def verify_and_extract(
    asset: Path, release: dict[str, Any], controlled: Path, workdir: Path
) -> list[str]:
    """Check the asset, its file set and every extracted file; return the corpora to install."""
    if sha256(asset) != release['sha256']:
        raise VerificationError(f'{asset.name}: SHA-256 does not match release.json')
    expected = expected_members(release, controlled)
    extracted = workdir / 'extracted'
    with zipfile.ZipFile(asset) as archive:
        check_members(archive, expected, asset.name)
        archive.extractall(extracted)
    for corpus in release['corpora']:
        committed = load_json(controlled / corpus / MANIFEST)
        shipped = load_json(extracted / 'controlled' / corpus / MANIFEST)
        if committed != shipped:
            raise VerificationError(
                f'{corpus}: the released manifest differs from the committed one'
            )
        for entry in manifest_files(committed):
            path = extracted / 'controlled' / corpus / entry['path']
            if sha256(path) != entry['sha256']:
                raise VerificationError(
                    f'{corpus}/{entry["path"]}: SHA-256 does not match the manifest'
                )
    return list(release['corpora'])


def swap(source: Path, destination: Path) -> None:
    """Rename within one filesystem; a separate function so a test can make a step fail."""
    os.replace(source, destination)


def _make_writable(function: Callable[..., Any], path: str, _error: BaseException) -> None:
    """Clear the read-only flag that stops a delete on Windows, then try again."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, onexc=_make_writable)
    elif path.exists():
        os.chmod(path, stat.S_IWRITE)
        path.unlink()


def install(extracted: Path, controlled: Path, corpora: list[str]) -> list[str]:
    """Swap the verified files of every corpus in, keeping the committed manifests.

    Phase 1 moves the verified files into a staging folder beside each corpus, so nothing in the
    destination changes until every corpus is staged. Phase 2 moves the current files aside and the
    staged files in. Each move is recorded before it is made, so a failure or an interruption
    (including Ctrl+C) at any point can be undone: the new files are removed and the files moved
    aside are put back. The staging and backup folders are removed only after a complete install
    or a complete rollback; a backup that still holds files is kept and RestoreError names it.
    Returns warnings about leftover folders that could not be deleted.
    """
    folders: list[Path] = []
    plan: list[tuple[Path, Path, Path]] = []
    moved_aside: list[tuple[Path, Path]] = []
    placed: list[Path] = []
    finished = False
    try:
        for corpus in corpora:
            target = controlled / corpus
            staging, backup = staging_folders(controlled, corpus)
            for folder in (staging, backup):
                folder.mkdir()
                folders.append(folder)
            for item in sorted((extracted / 'controlled' / corpus).iterdir()):
                if item.name != MANIFEST:
                    shutil.move(str(item), str(staging / item.name))
            plan.append((target, staging, backup))
        for target, staging, backup in plan:
            for item in sorted(target.iterdir()):
                if item.name != MANIFEST:
                    moved_aside.append((backup / item.name, item))
                    swap(item, backup / item.name)
            for item in sorted(staging.iterdir()):
                placed.append(target / item.name)
                swap(item, target / item.name)
        finished = True
    except BaseException as failure:
        try:
            # A recorded move may not have happened yet: skip a path that is not there.
            for path in reversed(placed):
                if path.exists():
                    remove(path)
            for saved, original in reversed(moved_aside):
                if saved.exists():
                    os.replace(saved, original)
            finished = True
        except OSError as restore_error:
            kept = ', '.join(str(f) for f in folders if f.name.endswith('.previous'))
            raise RestoreError(
                f'putting the previous files back failed ({restore_error}); they are in {kept}'
            ) from failure
        raise
    finally:
        warnings: list[str] = []
        for folder in folders:
            backup_in_use = folder.name.endswith('.previous') and folder.exists()
            if backup_in_use and not finished and any(folder.iterdir()):
                continue  # the only copy of the previous files; RestoreError or the caller names it
            try:
                remove(folder)
            except OSError as error:
                warnings.append(
                    f'could not remove {folder} ({error}); delete it before the next run'
                )
    return warnings


def leftovers(controlled: Path, corpora: list[str]) -> list[Path]:
    """Staging or backup folders left by an earlier run that was interrupted."""
    return [f for corpus in corpora for f in staging_folders(controlled, corpus) if f.exists()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0] if __doc__ else None)
    parser.add_argument(
        '--dest', type=Path, default=CONTROLLED, help='the controlled corpus folder'
    )
    args = parser.parse_args(argv)
    controlled: Path = args.dest
    release = load_json(controlled / 'release.json')
    found = leftovers(controlled, list(release['corpora']))
    if found:
        print(
            'error: an earlier run was interrupted and left '
            + ', '.join(str(f) for f in found)
            + '; a .previous folder holds the files that were installed before it. Move them back'
            ' or delete the folders, then run again.',
            file=sys.stderr,
        )
        return 2
    with tempfile.TemporaryDirectory(prefix='fnol-corpus-') as temp:
        workdir = Path(temp)
        asset = download(release, workdir)
        try:
            corpora = verify_and_extract(asset, release, controlled, workdir)
        except VerificationError as error:
            print(f'error: {error}; nothing was changed', file=sys.stderr)
            return 1
        try:
            warnings = install(workdir / 'extracted', controlled, corpora)
        except RestoreError as error:
            print(f'error: {error}', file=sys.stderr)
            return 2
        except OSError as error:
            print(
                f'error: installing failed ({error}); the previous files were restored',
                file=sys.stderr,
            )
            return 1
    for warning in warnings:
        print(f'warning: {warning}', file=sys.stderr)
    for corpus in corpora:
        print(f'{corpus}: verified and installed in {controlled / corpus}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

"""Download the controlled corpus packs from their GitHub release and verify every file.

Usage:
  python tests/corpus/tools/fetch_corpus.py [--dest DIR]

The packs are not in the Git history (Discussion #1153). `release.json` names the release tag and
asset and gives the asset's SHA-256. Each corpus folder holds a committed `manifest.json` that
lists every pack file with its SHA-256. The script downloads the asset with the GitHub CLI (the
repository is private, so `gh auth login` is needed first), checks the asset hash, extracts it to
a temporary folder, and checks every file against the committed manifest. Only when everything
matches does it replace the pack files in the destination; on any mismatch it stops and changes
nothing.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CONTROLLED = HERE.parent / 'controlled'


class VerificationError(Exception):
    """A downloaded or extracted file does not match its recorded SHA-256."""


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


def verify_and_extract(
    asset: Path, release: dict[str, Any], controlled: Path, workdir: Path
) -> list[str]:
    """Check the asset and every extracted file; return the corpus names ready to install."""
    if sha256(asset) != release['sha256']:
        raise VerificationError(f'{asset.name}: SHA-256 does not match release.json')
    extracted = workdir / 'extracted'
    with zipfile.ZipFile(asset) as archive:
        for name in archive.namelist():
            if name.startswith('/') or '..' in Path(name).parts:
                raise VerificationError(f'{asset.name}: unsafe path {name!r}')
        archive.extractall(extracted)
    for corpus in release['corpora']:
        committed = load_json(controlled / corpus / 'manifest.json')
        shipped = load_json(extracted / 'controlled' / corpus / 'manifest.json')
        if committed != shipped:
            raise VerificationError(
                f'{corpus}: the released manifest differs from the committed one'
            )
        for entry in manifest_files(committed):
            path = extracted / 'controlled' / corpus / entry['path']
            if not path.is_file():
                raise VerificationError(f'{corpus}/{entry["path"]}: missing from the release')
            if sha256(path) != entry['sha256']:
                raise VerificationError(
                    f'{corpus}/{entry["path"]}: SHA-256 does not match the manifest'
                )
    return list(release['corpora'])


def install(extracted: Path, controlled: Path, corpora: list[str]) -> None:
    """Replace each corpus's pack files, keeping the committed manifest."""
    for corpus in corpora:
        source = extracted / 'controlled' / corpus
        target = controlled / corpus
        for item in source.iterdir():
            if item.name == 'manifest.json':
                continue
            destination = target / item.name
            if destination.is_dir():
                shutil.rmtree(destination)
            elif destination.exists():
                destination.unlink()
            shutil.move(str(item), str(destination))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0] if __doc__ else None)
    parser.add_argument(
        '--dest', type=Path, default=CONTROLLED, help='the controlled corpus folder'
    )
    args = parser.parse_args(argv)
    controlled: Path = args.dest
    release = load_json(controlled / 'release.json')
    with tempfile.TemporaryDirectory(prefix='fnol-corpus-') as temp:
        workdir = Path(temp)
        asset = download(release, workdir)
        try:
            corpora = verify_and_extract(asset, release, controlled, workdir)
        except VerificationError as error:
            print(f'error: {error}; nothing was changed', file=sys.stderr)
            return 1
        install(workdir / 'extracted', controlled, corpora)
    for corpus in corpora:
        print(f'{corpus}: verified and installed in {controlled / corpus}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

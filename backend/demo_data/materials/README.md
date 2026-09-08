# Demonstration Materials

The image and document assets a Validation Prototype demonstration uses for the `motor`, `home`,
and `contents` paths, together with the machine-readable record of what each one is.

## What these are

Product runtime demonstration data. They exist to be seeded into a running demo and read through
the same paths a claimant and a staff member use.

They are **not test fixtures**. `docs/fixtures_convention.md` reserves `tests/fixtures/media/` for
synthetic bytes a test needs to exercise the upload boundary, and keeps runtime demo data, static
fixtures, executable assertions, and test doubles under independent ownership. Nothing in this
directory may be what a test asserts against, and nothing under `tests/fixtures/` may appear in a
demonstration.

**Every asset is generated, not sourced.** No file here is a photograph of a real incident, a
document issued by a real authority, or a record from a real retailer or assessor. Each asset states
that in two places: on its face for a human reader, and in a machine-readable place so the claim can
be checked rather than trusted — a JPEG comment segment for the images, the page text for the
documents. That is what `docs/demonstration-material-catalogue.md` requires of provenance and what
issue #601 requires of its failure boundary.

## What governs the set

`docs/demonstration-material-catalogue.md` is the specification: it defines the material classes,
the conditions, and what each of the three paths must demonstrate. It deliberately fixes no
filename, format, or layout — those are decided here.

The conditions that describe an absence — missing, pending, and unavailable — have **no asset by
design**. A material that has not arrived is demonstrated by its absence and its recorded state, not
by a placeholder file. That is why the asset count is smaller than the number of catalogue cells.

## Layout and naming

```text
materials/<path>/<path>-<subject>-<qualifier>.<ext>
```

One directory per claim path. `jpg` for the schematic stand-ins that represent photographs, `pdf`
for the ones that represent documents. The filename carries no claimant name, address,
registration, policy number, or date, because it is shown on both the claimant and staff surfaces.

## `materials.json`

The runtime metadata for the set. For every asset it records the path, the claim path, the material
class, the catalogue condition it demonstrates, its media type, its title, the text rendered onto
it, and that its origin is simulated.

It deliberately carries **no Claim, Evidence, or storage reference**. Associating a material with a
claim record, a source, and a processing status is issue #602; this file describes only the
materials themselves, so that work has something authoritative to read.

`generate_materials.py` writes it, and `--check` fails if it has drifted from the `ASSETS` table.

## Byte exactness

`.gitattributes` in this directory marks `*.pdf` and `*.jpg` as non-text, overriding the repository
root's `* text=auto`. This is not cosmetic. A PDF cross-reference table is a fixed-width record
format whose rows end in a mandatory space and whose entries are byte offsets into the file; if Git
normalises line endings on checkout, every offset shifts and the document stops opening. The same
applies to the JPEG entropy-coded data.

## Regenerating and verifying

```bash
python backend/demo_data/materials/generate_materials.py          # write every asset
python backend/demo_data/materials/generate_materials.py --check  # verify, write nothing
```

`--check` opens every asset with the standard library alone: it parses the JPEG markers for the
pixel size and the comment segment, decompresses the PDF page stream to read its text, confirms each
file is the media type the table declares, confirms the simulated-origin statement is present, and
confirms `materials.json` still matches the table. It needs no third-party package, so anyone can
reproduce the acceptance evidence from the declared project dependencies.

Writing the images needs Pillow, which this repository deliberately does not declare. Nothing in the
application or the test suite imports this module, and nothing needs Pillow to *use* the committed
assets; only regenerating them does, which is why the write path resolves it with
`importlib.import_module` instead of a static import. A static import would put an undeclared
package into a tree that `mypy` type-checks and that CI installs from the declared requirements
files, which is what `--check` is arranged to avoid needing.

If you want to regenerate, install Pillow into your own environment:

```bash
python -m pip install pillow
python backend/demo_data/materials/generate_materials.py
```

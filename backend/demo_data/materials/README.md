# Demonstration Materials

The image and document assets a Validation Prototype demonstration uses for the `motor`, `home`,
and `contents` paths.

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
that on its own face, which is what `docs/demonstration-material-catalogue.md` requires of
provenance and what issue #601 requires of its failure boundary: simulated origin is explicit, and
no live provider is represented.

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

## Regenerating

`generate_materials.py` in this directory is the producer and the manifest: its `ASSETS` table is
the authoritative list of what exists, and for each asset it records the path, the claim path, the
material class, the condition it demonstrates, and the text rendered onto it.

```bash
python backend/demo_data/materials/generate_materials.py          # write every asset
python backend/demo_data/materials/generate_materials.py --check  # verify each one exists
```

It imports Pillow, which is **not** a declared project dependency. That is deliberate: the assets
are committed, so nothing in the application or the test suite needs Pillow to use them. Only
regenerating them does. The script is not imported by any application module.

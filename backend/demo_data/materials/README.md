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

**Missing and pending have no asset by design.** A material that has not been offered, or whose
wait is on someone identifiable, is demonstrated by its absence and its recorded state, not by a
placeholder file. Nothing came back, so there is nothing to produce.

**Unavailable is not the same kind of absence, and does have an asset.** Section 7 requires it to
state why, and says it "must not silently degrade into a claim of unavailability where none was
established". Establishing it produces a record: the issuer or assessor answering that they cannot
supply, and for what reason. That answer is a real material, so `motor` carries an assessment that
cannot be provided and `contents` carries an official report that cannot be issued, each stating its
reason. Section 5.2 marks both cells `R`, and a marked condition must be reachable rather than
merely describable.

That is why the asset count is smaller than the number of catalogue cells but larger than the number
of present conditions.

## Layout and naming

```text
materials/<path>/<path>-<subject>-<qualifier>.<ext>
```

One directory per claim path. `jpg` for the schematic stand-ins that represent photographs, `pdf`
for the ones that represent documents. The filename carries no claimant name, address,
registration, policy number, or date, because it is shown on both the claimant and staff surfaces.

## `materials.json`

The runtime metadata for the set, and the authoritative description #602 reads when it associates
materials with Claim and Evidence records.

For every asset it answers all ten attributes section 3 of the catalogue requires: the decision the
material supports, the path and journey point it applies to, who provides it, every condition it can
occupy and what each means for that material specifically, what makes an instance usable or
insufficient, its provenance and what checking it has received, whether disclosure needs consent and
what each side may see, what it attaches to, what the surfaces must show in each condition, and its
retention handling.

**Where the catalogue leaves a decision open, the manifest records the dependency rather than
inventing a value.** Section 3 says an unanswered attribute is an open decision from section 9, not
a blank filled in during production, so those entries read
`{"unresolved": "...", "blocked_on": "P2"}` and name the work that would settle them — P2 for
registered fields, P3 for issuing stakeholders, P5 for consent copy and disclosure scope, privacy
review for the retention rule of the Elevated classes, and backend contract work for how a condition
maps onto persisted status values.

Answers that belong to a material class rather than one asset — who provides it, what disclosure
requires, how long it is kept — are held once in `CLASS_PROFILE` and merged in. Behaviour when a
material is not usable is a property of the condition, from section 7, and is merged from
`CONDITION_BEHAVIOUR`.

It deliberately carries **no Claim, Evidence, or storage reference**. Associating a material with a
claim record, a source, and a processing status is issue #602.

`generate_materials.py` writes it, and `--check` fails if any material omits a required attribute,
if the manifest has drifted from the tables, if a material demonstrates a condition it does not
record itself as able to occupy, or if any cell section 5.2 marks `R` is not reached. That last
check reads `REQUIRED_COVERAGE`, which is section 5.2 transcribed as a table so an unreached cell is
a failure rather than something a reader has to notice.

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

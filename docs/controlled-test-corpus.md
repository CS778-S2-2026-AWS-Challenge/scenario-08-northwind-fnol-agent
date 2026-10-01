# Controlled test corpus standard

This standard defines what one controlled test pack contains, how its materials are made, labelled
and checked, and how the corpus is stored, reviewed and frozen. It serves #1117, the controlled
slice of #1065, and does not cover the blind corpus, test execution or scoring (#1066).

The corpus has two versions: samples `0.2` (four packs, reviewed by the maintainer) and `v1` (100
packs). Both were checked against `main@1183e248` on 2026-09-30. The triage and review-indicator
labels follow the maintainer's design note of 2026-09-30, referred to below as **the rules**. The
note was shared in the team chat and is not in the repository, so every oracle records its SHA-256
in `rules_ref`. Values marked **bind at RC1** are checked against the RC1 contracts before the
corpus is frozen.

The parts of the corpus live in three places:

- the tools in `tests/corpus/tools/`;
- the pack specs, the committed manifests and the planning record in `tests/corpus/controlled/`;
- the pack files in a GitHub release (section "Store and fetch the packs").

## Define one pack

One pack is one complete claim journey. An image or a document alone is never a pack. Every pack
has four parts, and a pack with any part missing fails the checker:

1. **Oracle.** Hidden labels and expected outcomes (section "Write the oracle").
2. **Initial message.** The claimant's first message, as typed on the entry page.
3. **Fact sheet.** Every fact the claimant knows, used to answer the Agent's questions.
4. **Materials.** Images and documents, each with provenance.

A pack also has a **setup** for the runner (section "Prepare the run").

## Lay out a pack

A pack is a folder named by its `case_id`. Model-visible input and the oracle are in separate
folders. The runner passes only `input/` to the claimant simulator and the system under test. Only
the scorer reads `oracle/`.

```text
tests/corpus/controlled/v1/
  manifest.json
  cases/
    CTL-M-001/
      input/
        initial_message.txt
        facts.json
        materials.json
        materials/
          photo-rear-bumper.jpg
          repair-quote.pdf
      oracle/
        labels.json
      setup.json
      provenance.json
      review.json
```

- `input/materials.json` lists only the file name, Evidence kind and when the claimant has it.
  Purposes, prompts, printed fields and intermediate sources would give the answer away, so they
  live in `provenance.json`, which only the checker and the scorer read.
- `setup.json` is read by the runner before the run. It is not model input.
- `review.json` records the review of every image (section "Review every image"). The runner never
  reads it. The manifest is rewritten after every review record, so sign-offs are covered by the
  manifest hash.
- `case_id` is `CTL-<family letter>-<three digits>`, for example `CTL-M-001`. The number never
  changes once assigned.
- `manifest.json` lists every pack and every file with its SHA-256 hash, the corpus version, the
  pack schema version and the generator version.
- Images are JPEG. Documents are PDF, except where a boundary variant needs another format.

## Store and fetch the packs

The pack files are not in the Git history. Version `v1` takes about 45 MB, more than the rest of
the repository, so the maintainer chose on 2026-10-01 (Discussion #1153) to keep them as one zip
asset of a GitHub release. The repository holds everything needed to identify and verify them:

```text
tests/corpus/
  tools/                  generator, checker, image review and fetch tools
  controlled/
    release.json          release tag, asset name and the asset's SHA-256
    specs/v1/             one spec per pack, the source each pack is built from
    specs/samples-0.2/
    plan/                 the v1 distribution plan and audit record
    v1/manifest.json      every v1 pack file with its SHA-256
    samples-0.2/manifest.json
```

A version is identified by a commit and the hash of its committed manifest. To fetch the packs,
log in to the GitHub CLI (the repository is private) and run the fetch script from the repository
root:

```bash
gh auth login
python -m tests.corpus.tools.fetch_corpus
```

The script downloads the asset named in `release.json` and checks its SHA-256. Before extracting
anything, it checks that the asset holds exactly the files the committed manifests list, plus the
manifests: a folder entry, or an extra, missing or repeated file stops it, and so does a manifest
path that is not a plain relative path. It then extracts the asset to a temporary folder and
checks every file's SHA-256 against the manifest. On any mismatch it stops and changes nothing.
Installing has two phases: every corpus is first staged beside its folder under
`tests/corpus/controlled/`, and then the staged files are swapped in. The committed manifests are
never replaced. If a swap step fails or is interrupted, the previous files are put back; if even
that fails, the script keeps the backup folder that holds them, names it, and refuses to run again
until it is dealt with. The fetched folders are ignored by Git.

Rebuilding packs from their specs is for making the next version, not for using this one.
`tests/corpus/tools/build_pack.py` needs the libraries in `tests/corpus/tools/requirements.txt`
for the documents, and the image model, or its local cache, for the images. A rebuilt image has a different
hash and needs its own sign-off (section "Review every image"). Publishing a release is a protected
operation that needs the current user's explicit authorisation
([authority boundary](skills/repo-governance-for-novice/authority-boundary.md), section 1.2).

## Write the initial message

The first message is what a real claimant would type, not a tidy summary. Each pack names its
`message_style` in the oracle's `design` block:

| Style | What it looks like |
| --- | --- |
| `plain` | Clear, one event, standard English |
| `many_facts` | Several facts in one breath, some the Agent has not asked for yet |
| `emotional` | Upset or stressed, with exclamation marks and asides |
| `typos` | Lower case, missing punctuation, misspelt words |
| `non_native` | Grammar of a non-native English speaker |
| `wrong_product_term` | Names the wrong product, for example "house insurance" for a contents item |

The style changes only the wording. It never changes a fact: "water came through the ceiling" may
become "water started coming through my ceiling!!", not "water was pouring".

Dates in the message are absolute, for example "on Tuesday night (the 22nd)". A relative date such as
"last night" means a different day on every run, which would move the incident and can turn an
innocent pack into a date-check hit.

## Write the fact sheet

`facts.json` holds the claimant's knowledge. Keys use Field Registry codes where a code exists. The
snapshot the checker uses is `tests/corpus/tools/registry_codes.json`: Field Registry version `7`, 52 codes, taken
from `backend/domain/field_registry.py` on `main@1183e248`. `docs/fnol-field-model.md` still
describes version `6` and is not the source.

- The fact sheet may also hold facts that have no registry code, such as a vehicle make, a purchase
  date or a serial number. The claimant simulator needs them to answer questions.
- The fact sheet answers every question main makes the Agent ask. For contents items that includes
  ownership (`owned`, `leased`, `borrowed`, `gifted`, `other`), without which main cannot confirm an
  item. An unplanned "I don't know" would add a triage reason the oracle does not expect.
- The oracle splits the Claim's facts in two, both keyed by registry codes and checked against the
  registry's value types and allowed values:
  - `expected_facts`: facts main requires on this path (the common, family and active-branch
    required sets) or that the first message states. They must end confirmed with this value.
  - `optional_facts`: facts a good Agent may collect but main does not require. If present, they
    must match; a list gives the acceptable values, for example `police.status` in `not_required`,
    `not_reported`.
- Temporal facts are ISO dates; the scorer compares the calendar day.
- Facts the claimant does not know are recorded as `unknown`. The simulator then answers
  "I don't know".
- A fact the claimant learns only later, such as a Police reference not issued yet, is recorded with
  the turn or condition from which it is known.
- The simulator answers only what the Agent asks. It never volunteers facts, and it never reads
  `oracle/` or `setup.json`.

The answer policy itself belongs to the runner that plays the claimant (S5-E, #1066), not to this
corpus.

## Prepare the run

`setup.json` tells the runner what state the system must be in before the claimant starts.

| Field | Values | Meaning |
| --- | --- | --- |
| `claimant_session` | `signed_in`, `anonymous_then_sign_in` | Signed in from the start, or starts without an account and signs in before the first upload. On main an anonymous claimant cannot upload or submit, so every journey ends signed in. |
| `history_lookup` | `available` | The claim-history lookup works during the run. The corpus supplies materials and does not simulate runtime failures, so there is no outage value (maintainer, 2026-10-01). |
| `policies_in_system` | List of `{policy_number, family, effective_from, effective_to, excess_nzd, uncertainty}` | Policies the insurer's lookup must know. `effective_from` is the current period start. `uncertainty` lists markers the lookup returns, for example `COVERAGE_SECTION_INCOMPLETE`; a marker on the pack policy requires `coverage_unclear`. Leave the pack's policy out to test `policy_lookup_failed`. |
| `prior_submitted_claims` | List of `{family, incident_date, submitted_date}` | Earlier submitted claims of the same account, created by the runner before the run |

The checker recomputes from this file the history checks, the policy lookup and the need for
`coverage_unclear`. It recomputes policy inception from `design.policy_inception_date`.

How the runner signs in and creates earlier claims on the full stack is recorded in section
"Bind to the system".

## Write the oracle

`labels.json` is the answer key.

| Key | Content |
| --- | --- |
| `family` | `motor`, `home` or `contents` |
| `scenario_category` | `M1`–`M5`, `H1`–`H3`, `C1`–`C2` (`docs/status/sprint4-rubric-anchors.md`) |
| `condition`, `additional_conditions` | `normal` or boundary codes (section "Use these boundary conditions") |
| `design` | `message_style`, `incident_window` (first and last possible day), `policy_inception_date` (original inception), `planted_indicators`, `innocent_controls`, optional `notes` |
| `triage` | `expected_class`, `required_reasons`, `allowed_reasons`, `rationale` (section "Label triage") |
| `review_indicators` | `expected_fraud_signal`, and one expected outcome for every check (section "Label the review indicators") |
| `expected_facts` | Registry codes and values the Claim must hold as confirmed at the end (section "Write the fact sheet") |
| `optional_facts` | Registry codes that must match if the Claim holds them |
| `assertions` | Structured checks of the end state and of what each side saw (section "Write assertions") |
| `expected_rag_sources` | Clause IDs from `config/knowledge-source-corpus/` |
| `allowed_variation` | Differences that still count as a pass, such as question order |
| `intended_conflicts` | Every deliberate mismatch between the fact sheet and a material |
| `rules_ref` | File, date and SHA-256 of the rules the labels follow |

## Label triage

Triage says how much human attention a Claim needs next, not how serious the event was. Labels follow
section 2 of the rules: first look for anything that needs professional judgement (`complex`), then
for anything that needs follow-up (`standard`); only a pack with neither is `fast_track`. The class
is the highest class among the reasons, and every reason that applies is listed.

| Reason code | Class | Rule |
| --- | --- | --- |
| `injury_or_danger` | complex | Someone is injured, the scene is dangerous, or an urgent handoff was made |
| `liability_unresolved` | complex | Another party is involved and liability is unconfirmed or disputed |
| `coverage_unclear` | complex | The policy lookup carries an uncertainty marker, or the Agent recorded that the loss may not be covered; `coverage = review_required` alone does not count |
| `claimant_disputes_terms` | complex | The claimant disagrees with the excess or the scope of cover |
| `uninhabitable_or_ongoing_risk` | complex | The home cannot be lived in, or damage is still happening |
| `review_indicator_escalated` | complex | The review indicators reached `review_required` |
| `evidence_outstanding` | standard | Required material is missing, unreadable, incomplete, or not available yet |
| `question_unanswered` | standard | A required question is unanswered, or answered "I don't know" |
| `inconsistency_unresolved` | standard | Statements disagree, or a material contradicts the statement, and it is not clarified |
| `policy_lookup_failed` | standard | The system could not find the policy |
| `vehicle_undrivable_or_assessor` | standard | The vehicle cannot be driven, needs towing, or needs an assessor |
| `amount_over_threshold_or_unknown` | standard | The largest known amount is over NZD 5,000, or no amount is known |
| `review_hint` | standard | Exactly one weak indicator |
| `possible_duplicate` | standard | Another submitted claim may be the same event |

- `required_reasons` must all be reported by the system. `allowed_reasons` may be reported without
  counting as an error; they are for cases the rules leave open, and they never raise the class.
- The amount is the largest of: a quote or assessment total including GST, the claimant's own
  estimate, and for contents the sum of item values. Exactly NZD 5,000 is still `fast_track`. The
  threshold is a project assumption; the brief gives no number.
- A Claim that is never formed, for example after an urgent handoff before submission, is not
  triaged: `triage.applies` is `false`.
- The reason codes are the corpus's own. The backend has no triage codes yet; when it does, the
  scorer maps them one to one.

### Readings of the rules this corpus uses

Where the rules leave a case open, the labels read them as follows. Each reading rests on the
rules' own wording; none is a new rule.

- **Liability is not confirmed by an apology at the scene.** The rules make a Claim `complex` while
  liability is "not yet confirmed or disputed" and give "the other driver does not accept liability"
  as an example. At first notice, the claimant's report that the other driver apologised or admitted
  fault is not a confirmation, so `liability_unresolved` stays required (CTL-M-020, M-022, M-024,
  M-025, M-026). Liability counts as confirmed only when a material in the pack shows it.
- **A time-range incident.** The rules use the end of the range that favours the claimant for each
  date check: the last day for "receipt after the loss", the first day for "quote before the loss".
  `incident.occurred_at` accepts any day of the range, so it sits in `optional_facts` as a list of
  those days.
- **An explanation does not clear an inconsistency.** The rules keep a reminder when the claimant
  explains a date, with the explanation attached for staff. In the same way, a document that
  contradicts the statement stays `inconsistency_unresolved` until a corrected document arrives,
  even when the claimant explains the error (CTL-H-014, H-028).
- **A pending Police report is outstanding material.** The rules give "the Police report is not out
  yet" as an example of `evidence_outstanding`, although main does not require a Police report for
  every motor claim (CTL-M-023).
- **An expired repair quote is outstanding material** on a repair claim, because the quote is the
  evidence of the repair cost (CTL-C-011), even where main does not list a quote as required.
- **An assessor's report may stand in for a repair quote, or may not.** The rules do not say, so
  `evidence_outstanding` is an allowed reason in those packs (CTL-M-030, M-033).
- **A file the system refuses.** Whether main refuses an upload or stores it with a failed file
  status is the system's behaviour, not a property of the material. Packs with a corrupt or
  unsupported file therefore assert what the Agent tells the claimant (it asks for a usable file or
  accepts that one will come later, and does not describe a file it could not open). They do not
  assert that an Evidence record exists for that file.
- **Writer's choices in M5.** M5 rows with feature `none` and condition `normal` carry the writer's
  own scenario (CTL-M-048 disputed excess, M-049 amount only, M-050 a self-corrected date). Their
  labels follow the rules; a `fast_track` pack in M5 is allowed.

## Label the review indicators

The fraud label means "should a person look at this Claim", not "is this fraud". Labels follow
section 3 of the rules.

| Check | Strength | Rule |
| --- | --- | --- |
| `ownership_doc_after_loss` | strong | A receipt, proof of purchase or proof of ownership is dated after the incident. Only the purchase date counts; a reprint date is ignored. A time range uses its last day. |
| `quote_before_loss` | strong | A repair quote or assessment report is dated before the incident. A time range uses its first day. |
| `prior_claims_12m` | weak | Two or more other submitted claims by the same person in the past year. Drafts and this claim do not count. A possible duplicate is not counted again. |
| `policy_inception_30d` | weak | The incident is less than 30 days after the policy was first taken out. Needs the original inception date, which the system does not hold (the lookup has only the current period start). |
| `possible_duplicate` | separate | Another submitted claim by the same person, same family, incident within 3 days. Not a fraud indicator. |

Every pack labels every check with one outcome:

| Outcome | Meaning |
| --- | --- |
| `hit` | The rule fires |
| `clear` | Checked and fine |
| `not_checked` | The system cannot check it here: date unknown, unreadable or on a missing page, lookup error, or data the system does not hold |
| `not_applicable` | The pack has nothing this check looks at, for example no receipt at all |

`not_checked` is never the same as `clear`. The scorer reports `not_checked` counts separately.

From the outcomes:

- One strong hit, or two weak hits: `expected_fraud_signal` is `review_required`, and triage
  requires `review_indicator_escalated`.
- Exactly one weak hit and no strong hit: `none`, and triage requires `review_hint`.
- Otherwise `none`.

A receipt dated after the loss is always `review_required`, even when the story gives an innocent
explanation. The explanation goes to staff with the indicator; the system does not judge it.

A check that needs data the system does not hold is labelled `not_checked`, because the system
cannot run it. `policy_inception_30d` needs the date the policy was first taken out. The policy
lookup holds only the start of the current period, which changes at every renewal, so it cannot show
that a policy is new (maintainer, 2026-09-30). Each pack therefore states the original inception
date in `design.policy_inception_date`, separate from `effective_from` in `setup`. The value the
rule gives from that date goes in `value_if_data`, so the label can be switched when the system holds
the date. No pack relies on this check for its fraud signal until then.

Two more points from section 3 of the rules, both derived by the checker:

- A date on a page that was removed, or on an unreadable copy, gives `not_checked` for that document.
- A receipt whose purchase date cannot be told apart from its other dates is left out of the check.
  The template marks it with `purchase_date_ambiguous`.

### Innocent controls

An innocent control looks suspicious but is `none` under the rules. The oracle names it in
`design.innocent_controls`:

| Control | Why it is `none` |
| --- | --- |
| `reprint_date_after_loss` | A reprinted receipt has a purchase date before the incident and a print date after it; only the purchase date counts |
| `same_day_purchase` | Bought and lost on the same New Zealand calendar day; at least one day's difference is needed |
| `one_prior_claim` | Exactly one other claim in the past year; two are needed |
| `non_date_inconsistency` | A plain inconsistency unrelated to dates; triage `standard`, no indicator |

## Write assertions

Each assertion is one object:

| Key | Content |
| --- | --- |
| `id` | Unique in the pack, for example `A1` or `F2` |
| `kind` | `required` (must hold) or `forbidden` (must not happen) |
| `judge` | `state`, `text` or `human` |
| `path`, `op`, `value` | For `state`: a path in the end state, an operator (`equals`, `not_equals`, `in`, `contains`, `exists`, `absent`) and a value |
| `scope`, `must_not_match`, `rubric` | For `text`: `claimant_visible` or `staff_visible`, regular expressions that must not match, or a rubric for a text judge |
| `question` | For `human`: the question a person answers |
| `bind_at_rc1` | `true` when the path or value must be checked against RC1; the checker fails a frozen corpus that still has one |

Paths and values come from `docs/api.md` and the backend models on `main@1183e248` (section "Bind
to the system"). A path starts with its source (`claimant:claim`, `staff:evidence`, and so on). A
filter `[field=value]` selects list items. A field code with dots is quoted:
`claimant:claim.form["claim.product_family"].value`. Every `state` assertion carries
`bind_at_rc1: true` until its path is checked on the RC1 commit.

Every pack asserts, by file name, that its required photos and documents reached the Claim as
Evidence records (the kind depends on how the claimant uploaded them), and that
contents items exist with the stated loss type.

Corpus-wide assertions are in `tests/corpus/tools/global_assertions.json` and apply to every pack:

- `G1`: the claimant never sees the triage class or reasons, a review indicator, or any suggestion
  that the insurer suspects the claimant or the claim. Talking about the Police investigation of a
  theft is fine, and so is the word "standard" in a policy wording name.
- `G2`: the claimant is never told an excess, limit or payable amount that the schedule does not
  state.
- `G3`: the Claim ends in the pack's product family, even when the claimant names the wrong product.

## Bind to the system

Checked against `main@1183e248` on 2026-09-30. Every point was found by one reader and re-checked
by a second. Values here are **bind at RC1**: re-check them on the RC1 commit before freeze.

### Where the runner reads the end state

| Path prefix | Endpoint | Credentials | Holds |
| --- | --- | --- | --- |
| `claimant:claim` | `GET /api/v1/claims/{claim_id}` | Claimant session | `workflow_state`, `form`, `contents_items`, `external_claim`, `handoff` (active support handoff only), `dynamic_form` |
| `claimant:claims` | `GET /api/v1/claims` | Claimant session | The stored `customer_next_step` of each claim (the detail route returns a read-time projection instead) |
| `claimant:messages` | `GET /api/v1/claims/{claim_id}/sessions/{session_id}/messages` | Claimant session | Everything the claimant saw; the source for `text` assertions with scope `claimant_visible` |
| `staff:claim` | `GET /api/v1/workbench/claims/{claim_id}` | Staff, `workbench:read` | `claim_state` (all eight dimensions), `lifecycle_state`, `tags`, `work_summary` |
| `staff:fields` | `GET /api/v1/workbench/claims/{claim_id}/fields` | Staff | The full form, including claimant-hidden fields |
| `staff:handoffs` | `GET /api/v1/workbench/claims/{claim_id}/handoffs` | Staff | Handoff records: `type`, `status`, `support_need`, `trigger`, `reason_codes` |
| `staff:signals` | `GET /api/v1/workbench/claims/{claim_id}/signals` | Staff | Review signals with `code`, `status`, `reason_codes` |
| `claimant:evidence` | `GET /api/v1/claims/{claim_id}/evidence` | Claimant session | The claimant's Evidence records with `original_filename`, `kind`, `status`, `file_status` |
| `staff:evidence` | `GET /api/v1/workbench/claims/{claim_id}/evidence` | Staff | Evidence records with `kind`, `status`, `file_status` |

A path filter `[field=value]` selects list items, for example `staff:handoffs[support_need=urgent]`.

### What the labels map to

| Label | Field on main | Written by live code on main? |
| --- | --- | --- |
| Claim created | `workflow_state = created` and `external_claim.creation_status = created` | Yes. The dev-stack mock claims service always returns `created`. |
| Urgent handoff | Any handoff with `support_need = urgent`, or `claim_state.urgency` in `urgent`, `immediate_safety_risk` | Yes. Do not rely on `type = urgent_support` alone: an upgraded support handoff keeps `human_support`. |
| `triage.expected_class` | `claim_state.severity` (`fast_track`, `standard`, `complex`; default `unassessed`) | **No.** Nothing writes it; live runs read `unassessed`. |
| `triage` reasons | None yet (the rules add a reason list, section 4) | **No.** |
| `expected_fraud_signal` | `claim_state.fraud_signal` (`none`, `review_required`) | **No.** No agent, rule or registered staff action writes it. |
| Review-indicator checks | None yet (the rules reuse review signals with new codes) | **No.** Live signal codes are only `POLICY_RETRIEVAL_UNCERTAINTY` and `CLAIM_HISTORY_RETRIEVAL_UNCERTAINTY`. |
| `expected_facts` | `form[code].value` with `form[code].status = confirmed` | Yes. |

Until the triage and review-indicator code lands, a scorer reports those labels as not
implemented, not as failures of the corpus.

### What the runner must set up, and what main cannot do yet

1. **Accounts.** An anonymous claimant can start a claim but cannot upload evidence or submit it.
   Every journey therefore ends signed in: `signed_in` from the start, or `anonymous_then_sign_in`,
   which signs in and promotes the claim before the first upload.
2. **Staff credentials.** Most end-state fields are readable only through the Workbench routes. The
   runner needs a staff login with `workbench:read`.
3. **Policies.** The dev-stack policy lookup knows two hard-coded references only
   (`synthetic-policy-101`, `synthetic-policy-ambiguous`), and no route adds policies yet. The
   development team will add a "seed policies" switch under `/api/v1/workbench/demo`; the runner
   seeds `setup.policies_in_system` through it. The interface is to be announced.
4. **Coverage state (decided by the maintainer, 2026-09-30).** `coverage_unclear` counts only a
   policy lookup that carries an uncertainty marker (for example `COVERAGE_SECTION_INCOMPLETE` on
   `synthetic-policy-ambiguous`) or an Agent record that the loss may not be covered.
   `claim_state.coverage = review_required` on its own does not count, although the turn reducer
   (`backend/services/turn_reducer.py`, the `Coverage.REVIEW_REQUIRED` update) sets it for any cited
   policy record. Labels follow this rule. A pack plants the marker with
   `setup.policies_in_system[].uncertainty`.
5. **Documents.** A PDF stays `processing` on the dev stack, and the dev-stack model reads images but
   not PDFs; #1129 is working on PDFs. No code reads dates from any document, so the two date checks
   cannot fire until document dates are extracted (rules, section 4).
6. **Evidence kinds and the upload path.**
   - Uploading through the Documents tab of the claim, against a requested item, records that
     item's kind.
   - The chat records every photo as `incident_photo` and every PDF as `other_document`. The
     development team will add a way to choose the material in the chat.

   Until then the runner uploads the way the interface allows:
   - each material a pack requires (the incident photo, the repair quote, the receipt or proof of
     ownership, the Police report) through the Documents tab, against the item the claim requests,
     with the kind the interface sends for that item;
   - other files through the chat, with the interface's default.

   It never copies `evidence_kind` from `input/materials.json`; that field is the corpus's name for
   the material, for the simulator and the scorer. The triage labels assume the required materials
   arrive this way. A run that can only use the chat records photos as `incident_photo` and
   documents as `other_document`, neither of which matches the family requirement (`incident_image`,
   `repair_quote`, `proof_of_ownership`), so main then reports those documents as not received.
   Assertions match Evidence by `original_filename`, not by kind.
7. **Earlier claims.** No seed route creates submitted claims for an account. The runner creates
   each earlier claim by driving the public API to creation.
8. **History not checked.** The corpus does not plant `not_checked` history. On 2026-09-30 the
   maintainer proposed making it with a lookup-error switch; on 2026-10-01 he ruled that a lookup
   error is runtime logic, and that the corpus supplies valid materials, not system reactions.
   Simulating the error would stand in for real system behaviour with a fake state. An anonymous
   claimant cannot reach claim creation on main in any case (`docs/api.md`, evidence upload). How
   the product reports `not_checked` is tested by the product's own tests, not by these packs.
9. **Police not issued yet.** A pending Police report is recorded only when the claimant's wording
   matches fixed phrases (for example "later", "not issued", "pending"). Fact sheets that need it
   use those words.
10. **After an urgent handoff** the model stops extracting facts, and the claim cannot be created
    until staff resolve the handoff.
11. **Field Registry.** Version `7`, 52 codes. `property.address` is home-only;
    `authorities.police_report_reference` is motor-only. Contents theft uses
    `contents.police_reference`.

## Cover these material types

Every material maps to a registered Evidence kind (`backend/domain/evidence.py`). The family
requirements on `main` are an incident image plus a repair quote for motor and home, and an
incident image plus proof of ownership for contents. The theft branches also require a Police
report (`backend/domain/branch_registry.py`).

| Material | Evidence kind | Required content | Optional content | Prohibited content |
| --- | --- | --- | --- | --- |
| Incident or loss photo | `incident_photo`, `item_photo` | The damage or loss stated in the facts: same object, colour, position and extent | Wider scene, time-of-day cues | Readable plates, plates that do not look like New Zealand plates, real brand logos, people's faces, real street signs |
| Police record | `police_report` | For NZ motor and theft: the Police event reference and the date it was reported | A synthetic crash or theft report summary that states it is not issued by NZ Police | NZ Police crest or real form layouts (for example POL685), real officer names |
| Policy schedule | `policy` | Policy number, policyholder, insured item or address, cover type, period, excess, the wording name | Named drivers, endorsements | Values that contradict the wording in `config/knowledge-source-corpus/` unless labelled as a conflict |
| Receipt, invoice or valuation | `receipt` | Seller, purchase date, item description, amount, payment method | Serial number, warranty, reprint date | Real retailer names or logos |
| Proof of ownership | `proof_of_ownership` | Owner name, item, date of acquisition, value | Photo of the item in use, serial number | Real government documents |
| Assessor report | `assessment_report` | Assessor, date, item inspected, findings, estimate | Photos, recommendation | Coverage or liability decisions |
| Repair quote | `repair_quote` | Repairer, date, itemised parts and labour, total including GST, quote validity (90 days, unless the pack is `expired`) | Photos, timeline | Real business names or registration numbers |
| Attendance note | `other_document` | Who attended, when, what was found, what was done | Follow-up needed | Real business names |
| Unavailable notice | `other_document` | Which material is unavailable, why, and when it is expected | Contact for follow-up | Any statement that the material exists |
| Consent record | `other_document` | Who consents, to what (for example sharing details with a repairer or the other party's insurer), the date, the claimant's name and policy number | Expiry or withdrawal terms | Real signatures, images of identity documents |
| Conflict record | `other_document` | Which statements or documents disagree, on which field, when it was noticed and by whom | The resolution once known | Any judgement of honesty or fraud |

No `v1` pack uses a consent record or a conflict record; they are defined so that later versions
follow the same rules. Within a pack, a deliberate mismatch is listed in the oracle's
`intended_conflicts`, not written as a conflict record.

Every document states in its footer: "SYNTHETIC TEST DOCUMENT - Northwind FNOL student project -
not a real record", and "Page X of N" on every page.

## Use these boundary conditions

Each pack uses `normal` or one of these conditions. Several conditions in one pack are allowed only
when every condition is listed in the oracle.

| Code | Meaning | How it is made |
| --- | --- | --- |
| `illegible` | A photo or scan cannot be read | Blur, low light or heavy compression applied to the normal file |
| `missing_page` | A multi-page document is incomplete | A page removed from the normal PDF; the remaining pages still say "Page X of N" |
| `expired` | A document is out of date | The date on the normal document moved past its validity |
| `missing_information` | A required field is absent | The field removed from the normal document |
| `conflicting` | A material contradicts the statement | One stated fact changed in the document and listed in `intended_conflicts` |
| `corrupt_file` | The file cannot be opened | Truncated bytes of the normal file |
| `unsupported_format` | The format is not accepted | The same content saved in a format outside JPEG, PNG and PDF |
| `not_yet_available` | The material will exist later | An unavailable notice, with the fact sheet saying when it arrives |

A boundary condition is not a fraud indicator by itself. Whether a `conflicting` pack is
`review_required` depends only on the checks: a receipt dated after the loss is, a mistyped
unrelated detail is not.

## Keep material synthetic and private

- **Names.** Taken from the corpus name list, which uses invented names only.
- **Licence plates.** `TST-` followed by three digits, for example `TST-104`. New Zealand plates have
  at most six characters, all letters or digits, so this cannot be a real plate. Plates in images are
  cropped out.
- **Driver licence numbers.** Three letters and five digits, for example `TST00104`. New Zealand uses
  two letters and six digits.
- **Phone numbers.** `+64 00 000 NNNN`. No New Zealand number starts with `00` after the country
  code.
- **Email addresses.** Always end in `.invalid`.
- **Addresses.** A real suburb or city with a street name from the corpus street list of invented
  names.
- **Policy and claim references.** Formats from the repository fixtures.
- **Brands.**
  - A vehicle make and model may appear in the fact sheet and in documents. They never appear in an
    image prompt, because the image model then draws the maker's badge.
  - Every issuer is invented and marked "(Synthetic)". Contents items use invented brands.
  - No logo of any real company appears in any image.
- **Sources.** Nothing is copied from the web. Images come from an image model, documents from
  templates, and variants from transforms of those files.
- **Image service.** The image generator reads the ComfyUI address from the `CORPUS_COMFYUI`
  environment variable only. No address is stored in the repository.

## Record provenance for every file

`provenance.json` (beside `input/` and `oracle/`) holds one entry per file. The model-visible
`input/materials.json` repeats only `file`, `evidence_kind` and `available_from`.

| Field | Content |
| --- | --- |
| `file` | Path inside `input/materials/` |
| `evidence_kind` | Registered Evidence kind |
| `method` | `template`, `image_model` or `transform` |
| `model` | For images, the model and weights file, for example `qwen_image_2.1_bf16.safetensors` |
| `generator_version` | Hash of the generator tools that produced the file |
| `inputs` | Template name, prompt and seed, or the source file and transform |
| `created_utc` | Generation time |
| `purpose` | Why this file is in the pack |
| `synthetic` | Always `true` |
| `usage_rights` | "Synthetic, created by the team for this project" |

## Review every image

`review.json` holds these records per image, each with the image's SHA-256:

- `model_blind`: `tests/corpus/tools/model_check.py --blind` sends the image alone, with no facts and no purpose,
  to `openai/gpt-4o` through OpenRouter, the vision model the product itself uses on the dev stack.
  It records what the model sees unprompted: the damaged object, the damage, its extent, plates,
  logos, people and readable text. This is the check that counts for "can the system see what the
  pack assumes": on samples 0.2 it read a close-up of a broken TV as a glass table, so that photo
  was replaced.
- `model_check`: the same model with the facts and the purpose given, with a hash of what it was
  shown, so an edited fact sheet makes it stale. It is led by the facts (its size estimates copied
  the fact sheet), so it is used for `matches_facts` and for plates, logos, people and text; sizes
  are never used. On samples 0.2 it found the white edge of a plate that the assistant check had
  missed.
- `assistant_check`: an optional first pass by the assistant against the fact sheet. No rule
  depends on it.
- `model_flag`: the result of the fixed flag rule below.
- `human_signoff`: the decision of a named person, with their GitHub login and a `method`. A
  replaced sign-off moves to `signoff_history`, so a rejection is never lost.

The maintainer's four rules (2026-09-30), and how `tests/corpus/tools/image_review.py` enforces them. The rules
are the maintainer's; the enforcement details below them are this corpus's own.

1. **A fixed rule decides which images a person must look at.** An image is flagged when:
   - the damaged object the image-only pass names does not end, as whole words, with one of the
     pack's `expect_object` names (English puts the head noun last, so "tv cabinet" names a cabinet
     and does not match "tv");
   - either pass reports a licence plate, a person, a logo or readable text, or does not answer
     one of them (`licence_plate` must be exactly "none", the three lists exactly empty);
   - the pass with facts does not answer `matches_facts: yes`, or is missing or stale.

   A deliberately unreadable image is exempt from the `matches_facts` point only. The image-only
   point still applies, and such an image cannot match its facts, so every one goes to a person.
   Size estimates are never used. Decisions are per image hash: a hash is flagged if any pack copy
   of it is flagged.
2. **A sample of the rest.** Of the images that are not flagged, at least 10 % are drawn at random
   with a recorded seed, and at least one per scenario category. Every sampled image is signed off
   one by one. If a person rejects a sampled image, the model missed a problem, and every image in
   that category must then be signed off one by one.
   - A corpus version has one draw. `sampling.json` is written once and carries a hash of the
     draw; any edit, or a second draw, makes every release by sampling fail the freeze.
   - Escalation is read from the sign-off records: a rejected sign-off that was `sampled` escalates
     every category recorded on it (all categories of that image hash). No file edit clears it.
   - A material slot (pack and material id) that ever held a rejected image is signed per image
     from then on, whatever the replacement file is called.
   - Only unsigned, unflagged hashes in the recorded population can be released; an image added
     later is signed per image.
   - `--freeze` also checks that each population row's categories still match the corpus.
3. **One sign-off per image hash.** A sign-off covers every pack that uses the same image; a second
   sign-off of the same hash is refused.
4. **Every sign-off names its method:** `per_image` (a person looked at it) or
   `model_check_with_sampling` (released after a clean model check and a clean sample in its
   category). `--freeze` checks that each release still meets its rule.

The commands, in order, run in module mode from the repository root (`CORPUS` is a corpus folder
such as `tests/corpus/controlled/v1`):

```bash
python -m tests.corpus.tools.model_check --blind CORPUS
python -m tests.corpus.tools.model_check CORPUS
python -m tests.corpus.tools.review_tool flags CORPUS
python -m tests.corpus.tools.review_tool sample CORPUS --seed N
python -m tests.corpus.tools.review_tool sign CORPUS CASE FILE accepted "note" --by @login
python -m tests.corpus.tools.review_tool release CORPUS --by @login
```

- `sign` is used for every flagged image and every sampled image.
- `release` releases the remaining images of each clean category.
- `review_tool.py sheet` produces the page a reviewer works from: every image with its facts, a
  four-point checklist and both model passes.

When an image changes, every record on it goes stale.

Before the draw, a flagged model image may be regenerated with other seeds
(`repair_parallel.py`); every attempt is kept in the spec's `seed_history`. After the draw, an
image a person rejected is regenerated from a prompt rewritten for the rejection, and the person
picks one of three candidates or rejects all three (`redo_rejected.py`). The pick is that image's
`per_image` sign-off, and the spec keeps the old prompt, the rejection, the candidates and the pick
in `redo_history`.

The review state of each version is as follows:

- Samples 0.2: the maintainer signed off all six images `per_image` on 2026-09-30.
- `v1`, 125 images, all reviewed on 2026-10-01:
  - 37 were flagged and 10 sampled (seed `20261001`), and @bdfa123 signed off all 47 one by one;
  - 11 were rejected and replaced by a picked candidate;
  - all 10 sampled images were accepted, so the other 78 were released by sampling.

## Check every pack

`tests/corpus/tools/check_corpus.py` fails a pack when any of these checks fails. With `--freeze`,
missing human sign-offs and assertions still marked `bind_at_rc1` also fail. It reads document text
with the libraries in `tests/corpus/tools/requirements.txt`. Run it, and the self-tests
of the checker and the image-review rules, in module mode from the repository root:

```bash
python -m tests.corpus.tools.check_corpus tests/corpus/controlled/v1
python -m tests.corpus.tools.selftest_checker
python -m tests.corpus.tools.selftest_review
```

Each self-test copies the fetched 0.2 samples, plants one error per case and confirms that the
checker reports it. They need the fetched packs, so pytest does not collect them; the fetch script
has its own pytest tests (`tests/corpus/tools/test_fetch_corpus.py`).

- **Schema.** All four parts, `setup.json` and `provenance.json` are present and valid.
- **Labels follow the rules.**
  - The triage class equals the highest class among the required reasons.
  - The fraud signal follows from the check outcomes, and the implied triage reasons are present.
  - The two date checks are recomputed from the dates printed on the pages the pack keeps.
  - The two history checks are recomputed from `setup.json` (`prior_submitted_claims`).
  - Policy lookup and the need for `coverage_unclear` are recomputed from
    `setup.policies_in_system`. `policy_inception_30d` is `not_checked`, with the value the rule gives
    from `design.policy_inception_date` in `value_if_data`.
- **Registry.** Every `expected_facts` and `optional_facts` key is a Field Registry code, and every
  value has the code's type and one of its allowed values.
- **Assertions.** Every pack assertion and every corpus-wide assertion has a valid judge, path or
  scope, and operator.
- **Separation.** No oracle word appears in `input/`, and `input/materials.json` carries only the
  file name, Evidence kind and availability.
- **Provenance.** Every file has an entry, and every entry has a file with a matching hash.
- **Privacy.** Plates, licence numbers, phone numbers and email addresses follow the formats above;
  names, streets and document issuers come from the corpus lists; no blocked brand name appears in
  document text.
- **Dates.**
  - "Expired" is judged against 2026-10-01. A pack with condition `expired` has a quote that
    lapsed before that day.
  - Every other quote is valid for 90 days and stays valid until at least 2026-11-30. A run
    with a live clock therefore does not see it as expired and add `evidence_outstanding`.
  - Every policy period starts on or after 2026-01-01, when wording version MVP-2026.1 takes
    effect. The wording says it must not be applied when the schedule's period does not match.
  - A weekday written next to a date matches that date.
  - A current period that does not start on an anniversary of the original inception is a warning
    only.
- **Consistency.** Fields that appear in both the fact sheet and a document match, unless the
  mismatch is listed in `intended_conflicts`.
- **Format.** Normal files open and match their declared type; only a `corrupt_file` or
  `unsupported_format` file may fail this.
- **Review.** For freeze, every image hash has exactly one accepted human sign-off on its current
  hash, with method `per_image`, or `model_check_with_sampling` where the release still meets rule 2:
  - the model check is clean;
  - the image was in the sampled population and not in the sample;
  - its categories are clean and never escalated;
  - it does not replace a rejected image;
  - `sampling.json` is unchanged since the release and is the draw its seed gives.

## Plan the distribution

100 packs, confirmed by the maintainer on 2026-09-30. Section 5 of the rules gives the mix for 30
packs (5 to flag, 4 innocent controls); the tables below keep those shares at 100 (17 and 13).
`v1` was built to this plan (`tests/corpus/controlled/plan/corpus-plan-v1.md`).

| Family | Categories and counts |
| --- | --- |
| Motor (50) | M1 12, M2 6, M3 10, M4 12, M5 10 |
| Home (30) | H1 8, H2 14, H3 8 |
| Contents (20) | C1 12, C2 8 |

| Group | Packs | Made up of |
| --- | --- | --- |
| Should flag (`review_required`) | 17 | Receipt after the loss 9 (3 with an incident time range); quote before the loss 8. The rules' "two weak indicators" packs need the original inception date, which the system does not hold; as the rules allow, they are date conflicts instead |
| Innocent controls (`none`) | 13 | Reprinted receipt 4; same-day purchase 3; one prior claim 3; non-date inconsistency 3 |
| Hint only (`none`, `review_hint`) | 3 | Two prior claims and nothing else |
| Possible duplicate | 3 | A second claim for the same event within 3 days |
| Starts anonymous | about 10 | `anonymous_then_sign_in`, spread across families |
| Policy not found | 3 | Pack policy left out of `policies_in_system`; triage `standard` |
| Coverage unclear | 3 | Pack policy carries a lookup uncertainty marker; triage `complex` with `coverage_unclear` |
| Boundary conditions | 40 planned, plus the planted date indicators | Five of each of the eight conditions. Every planted date indicator is also `conflicting` by construction, so `conflicting` appears in about 21 packs (`tests/corpus/controlled/plan/corpus-plan-v1.md`) |
| Message styles | all 100 | `plain` about 40, each other style about 12 |

## Version and freeze

- **Samples first.** Sample packs go to the maintainer before bulk generation.
- **Freeze.** The corpus is frozen as `v1` after RC1, identified by its commit and manifest hash.
  `check_corpus.py --freeze` must pass.
- **After freeze.** Oracle and materials are not changed to improve results. A real error is fixed
  in the next version, with the reason recorded in that version's audit record under
  `tests/corpus/controlled/plan/`.
- **Failed runs.** Failed runs stay in the results and are never removed.
- **What the scores mean.** The controlled corpus is labelled with the same rules the system is
  meant to implement, so a pass shows that the code follows the rules. Whether the rules are right
  is measured separately by the claims-staff blind review (rules, section 2).

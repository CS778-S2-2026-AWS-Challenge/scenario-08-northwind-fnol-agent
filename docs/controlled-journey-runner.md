# Controlled journey runner

The runner plays the claimant of each controlled-corpus pack through the real claimant UI on the
`start-dev` stack, the way a person would, then a separate scorer compares the end state with the
pack's oracle (#1222). Pack contents and labels are defined in the
[Controlled Test Corpus Standard](controlled-test-corpus.md). The code is in `tests/corpus/runner/`.

It runs only on `scripts/start-dev.ps1`: the backend must report `environment` development or
test, `data_runtime_profile` `local_mvp`, and `agent` `configured`. It is not part of CI.

## Run it

A full run starts from empty stores. Journeys lodge real Claims, and those become the customer's
history, so a second run on the same data would count the first run's Claims as earlier claims.

1. Stop the backend.
2. `node tests/corpus/runner/runner.cjs reset` drops the start-dev MongoDB database and deletes the
   claimant identity file. It refuses while the backend answers, or when MongoDB is not local.
3. Start the backend with `scripts/start-dev.ps1`. Startup provisions the packaged business seed
   and the staff accounts again.
4. `node tests/corpus/runner/runner.cjs seed CTL-M-002 CTL-H-006 …` writes every pack of the run
   as one manifest in the shared business-seed shape (`config/business-seed.json`, #1221). It then
   provisions the manifest through `load_business_seed` and the `provision_business_*` functions,
   which insert absent records only. It uses the backend's MongoDB settings and claimant identity
   file, so the records land where the running backend reads them. The corpus standard describes
   selecting the manifest through `Settings.business_seed_path`, but that setting is fixed to
   `config/business-seed.json`, so the runner provisions after startup with the same functions.
5. `node tests/corpus/runner/runner.cjs run CTL-M-002 CTL-H-006 …` runs the packs one after another.
6. `node tests/corpus/runner/score.cjs <run folder>` scores the run.

Settings (environment):

| Setting | Used by | Content |
| --- | --- | --- |
| `CORPUS_CASES_DIR` | all | The corpus `cases` folder (a fetched release, outside git) |
| `RUN_OUTPUT_DIR` | seed, run | Where manifests and run records go; outside the repository |
| `NORTHWIND_MONGODB_URI`, `NORTHWIND_MONGODB_DATABASE` | reset, seed | The backend's values (start-dev: `northwind_fnol`) |
| `CORPUS_PYTHON` | reset, seed | The Python that runs the backend (default `py -3.12`) |
| `CORPUS_BACKEND_REPO` | reset, seed, run | The checkout the backend runs from, if not this one |
| `CLAIMANT_BACKEND` | run | `ollama` (default) or `claude` |
| `CLAIMANT_OLLAMA_URL`, `CLAIMANT_MODEL` | run | The claimant model, for example `qwen3.8:27b` on the operator's Ollama |
| `NODE_PATH` | run | A folder whose `node_modules` holds Playwright |

## Seeded customers

Each pack's claimant is its own customer, using the pack's name and email
(`policyholder.name`, `claimant.email`). The rest is fixed by the pack ID, so the same packs always
give the same manifest:

- customer `cus_corpus_<pack>`;
- a synthetic development password;
- each policy in `policies_in_system`, owned by that customer, with status `active` and no coverage
  sections;
- each earlier claim as `clm_corpus_<pack>_p<n>` with claim number `NW-SYN-<pack>-P<n>`.

The seed refuses the four policy numbers #1206 uses, a policy number shared by two packs, and a
pack listed twice. Before a pack starts, the runner checks that its customer has no Claim other
than its seeded earlier claims. A leftover Claim means the stores were not reset.

`signed_in` packs log in before the first message. `anonymous_then_sign_in` packs start in a fresh
unsigned-in browser context and send their first message anonymously. Their customer isolation
check and phone setup use a separate browser context whose session is revoked and closed before
the journey starts; those setup reads never reach the claimant model.

When the claimant first selects a file, the runner waits for the product's visible instruction to
sign in. It opens the existing UI login entry, signs in as the pack's seeded customer, and lets the
client promote the current Claim. It verifies that the UI returns to the same Claim and the seeded
account can read it, then selects the file again through the same requested upload spot. If that
spot is no longer on the screen after sign-in, the pack stops as `stuck` at the upload step: the
file is never sent through the chat instead, which would record it under a different evidence
kind. If the claimant reaches the payout card first, its visible `Log in to continue` gate triggers
the same mechanical sign-in. The runner never calls promotion directly, starts a replacement Claim,
or resends the initial message. A failed login or promotion leaves the pack `stuck`.

## The claimant

The claimant model is independent of the system under test and of the team's keys. Each run
records the model's name and version.

| Backend | Model | Behaviour |
| --- | --- | --- |
| `ollama` | The operator's own model; the reference runs used `qwen3.8:27b` | Temperature 0 and a fixed seed, so the same screen gives the same reply |
| `claude` | The Claude Code CLI on the operator's own login, with no tools and no session | Replies can differ from run to run |

The system's reply review already uses Claude Haiku 4.5, so the reference runs use the Ollama
model.

What the claimant model may see (`claimant_view.cjs`):

- the initial message;
- the persona and answer policy;
- the facts;
- the materials, under plain-language labels (`material-labels.json`, every pack of corpus v1).

The labels say what the claimant holds, the way a claimant would name it. None is written by
hand. The ten reference packs were written one at a time with the contributor's AI assistant. The
rest were drafted by the operator's local model from each file's content alone, without the file
name, evidence kind, provenance, setup or oracle. Every label was then reviewed one by one. Where a
photo is unclear or a file is cut short on purpose, the label says what the claimant photographed
or holds.

It never sees evidence kinds, generation prompts, materials marked `include: false`, `setup.json`,
or `oracle/`. A leak check stops the run if any of those values reaches the prompt. It treats as
known only what the model actually receives without the labels: the system prompt and the brief as
rendered. A label that repeats an oracle or setup value is therefore caught, including a value that
appears elsewhere only in the case id or a file name, which the brief never shows.

Each turn, the claimant model gets only what the screen shows:

- the latest reply;
- the cards under it;
- the to-do bar;
- the open service card;
- any alert;
- the buttons it can press.

Network traffic is recorded for evidence but never given to it. The claimant model replies with a
message, files to upload and at most one button to press. It answers only what is asked, invents
nothing, and sends each file once. When it presses a button, it does nothing else that turn. A
service card's "Agree…" is offered while the card's permission box is still unticked; pressing it
ticks that box first, as a person does.

The runner fills the payout form, the contact choice and the agreement checkboxes by fixed rules.
It signs in at the pack's declared entry or visible login gate, adds the pack's phone to the profile
so SMS can be chosen, and attaches files one at a time. It presses Send only after every file shows
Ready or "Processing failed".

A file the product cannot process is the product's answer, not a stall. The product leaves that
file out of the message, so the message goes without it:

- `run.json` lists the file under `processing_failed`, and its upload path is marked
  `processing: failed, sent: false`. Only the tray entries the message's uploads add or reuse are
  read, so a file failed earlier and still in the tray does not count again;
- the claimant's transcript says it could not be processed;
- the claimant may try that file once more, as a person would, and that counts as a recovery.
  After a second failure it is not sent again;
- a message whose files all failed, with no words of the claimant's own, says the file could not be
  processed.

On the payout form, the runner reads the panel afresh until it can act:

- it waits for "Loading saved payout accounts" to finish (`payout_loading_waits`);
- a new-account form (no saved account, or a failed load) is filled by its own rule, but only if it
  is still there a second later, since the panel shows it briefly before loading starts;
- otherwise it chooses the contact method and selects the saved account whenever none is selected
  (`payout_reselected`). Selecting is a fixed rule, not a recovery;
- it presses "Continue to agreement" once the button is enabled.

A disabled "All correct" is not pressed. Login is a mechanical prerequisite and does not count as a
recovery.
`run.json` records the anonymous sign-in trigger, original Claim, conversation session and whether
promotion succeeded.

After every button the claimant model presses, and after the fixed rules' presses of the steps
below, the runner waits for the request the press started, if any, before it does anything else,
for up to 20 seconds. ("Retry message", "Retry response" and the login keep their own waits for the
agent's turn and the sign-in.) A request is running while the product shows it: the pressed
button disabled, "Saving…" or "Submitting…" on the button, or the product's busy signal (the
rail's "New chat" button disabled), which stays on when a panel is replaced mid-request. A
workspace without that signal stops the pack. Then:

- for the steps' presses, the runner reads the product's answer:
  - confirming the details: "All correct", "Looks right" or the side panel's "Right"; an error
    shows under the composer;
  - the payout step: "Save payout account" and "Continue to agreement", pressed only by fixed
    rules; an error shows on the contact form's own line;
  - submitting the claim: "Submit claim" or "Retry claim submission"; an error shows in the
    submission error card, or under the composer when the panel has been replaced.

  No error means the product accepted the press. An error is a refusal (see below);
- after any other press, such as a service card's "Not now", the claimant reads the result on the
  next screen;
- a request still running after 20 seconds leaves what the product did unknown. The runner stops
  the pack at that step (`confirmation`, `payout`, `agreement`, or `press` for any other press)
  rather than guess, and presses nothing more.

Uploads follow "Evidence kinds and the upload path" in the corpus standard:

- The screen lists the upload spots the claim offers for requested documents: the to-do bar, the
  "Still to do" list, a requested file under a reply, and the Documents cards.
- When the claimant sends a material the claim asks for, it names the matching spot. The runner
  uploads through that item's own input, so the file carries the kind the interface sends for that
  item. If the spot it names is not on the screen, the pack stops as `stuck` at the upload step,
  signed in or not: the file is never sent through the chat instead.
- Other files go through the chat.
- The runner never copies `evidence_kind` from the pack. Each run records which path every file
  took (`upload_paths`).

## Recovery and stuck

A person's recoveries are allowed once each. A run that used one ends as `lodged_after_retry`,
never `lodged_first_time`. The recoveries are:

- pressing "Retry message" or "Retry response";
- answering a question once more when the agent asks it again. Each question sentence is tracked
  on its own, whatever else the reply asks with it, so each repeated question counts as one retry;
- confirming once more after the product refuses a confirmation ("All correct", "Looks right" or
  "Right").
  Refusals after a press by the claimant model and by the fixed rule count together, and
  `run.json` lists each one under `confirmation_refusals`;
- pressing "Continue to agreement", or saving a new payout account, once more after the payout
  form's own error line shows an error for that attempt (a failed save, a conflict). These refusals
  are counted apart from confirmations, under `payout_refusals`;
- submitting the claim once more after the product refuses the submission. These refusals are
  counted on their own too, under `agreement_refusals`;
- sending a file again after the product could not process it;
- after about nine seconds with nothing to act on, typing "OK.".

A pack is `stuck` when any of these happens:

- a second failure follows a recovery;
- the agent asks the same question a third time;
- after the nudge, there is still nothing to act on;
- the claimant reaches 30 messages;
- a file shows neither Ready nor "Processing failed";
- a confirmation is refused a second time (step `confirmation`), the payout step is (step
  `payout`), or the claim submission is (step `agreement`);
- a press's request is still running after 20 seconds, at that press's step (`press` for a press
  outside the steps). The reason reads
  `no answer to "<button>" within 20 s`, or says the product was already busy before the press;
- the saved payout accounts are still loading after 30 seconds, "Continue to agreement" stays
  disabled for 30 seconds with the payout account and contact method chosen, or the new payout
  account form comes back after four saves;
- the claimant names an upload spot that is not on the screen;
- a wait times out.

## Scoring

`score.cjs` is the only reader of `oracle/`. Every comparison is mechanical. Per pack and in
`summary.md` it reports:

- **Journey:** outcome, claim number, messages, agent questions, repeated questions, time, and the
  effort target (under five minutes and under ten questions, lodged runs only). Every question
  sentence counts as one question, a repeated one included, by the rule the runner uses to
  recognise a repeat.
- **Files the product could not process:** each pack's `processing_failed`. In a `corrupt_file` or
  `unsupported_format` pack, the material made for that condition is expected to fail. Any other
  failed file is a valid file the product could not handle, and is listed in the summary as not made
  broken by the corpus, even when the pack lodged.
- **Completed without follow-up:** lodged, nothing owed by the claimant, and no missing-information
  triage reason (`document_outstanding`, `fact_unresolved`, `policy_not_verified`,
  `amount_unknown`).
- **Triage:** the class, and whether the reasons include every required reason and nothing outside
  the allowed list. A pack that never lodged is `not_lodged`: nothing was triaged.
- **Fraud review:** `claim_state.fraud_signal` against the pack's expected fraud signal, the only
  field the corpus standard maps it to. Nothing on main writes it, and its default is `none`, so
  only `review_required` is scored: a pass, or a false positive when the pack expects none. Every
  other pack is `not_implemented` (or `not_lodged`), and false negatives cannot be measured yet.
  Other staff signals, such as a policy judgment proposal, never count. Innocent controls are
  reported on their own: `flagged` when the signal is written, otherwise the review's result.
- **Staff side:** each item of the staff to-answer list, with its kind (`question` or
  `contact_request`), the Agent's proposed answer and basis, or the claimant's contact preference.
- **Facts:** expected facts against the confirmed value in the staff field list. Incident time is
  compared by New Zealand calendar day, read from every stored form: a date, a date with a part of
  day such as `2026-09-11 night`, or a clock time.
- **Assertions:** the pack's assertions and the corpus-wide `global_assertions.json`. A `forbidden`
  assertion passes when its condition does not hold. Rubric-only text assertions are left for a
  person.

Capabilities main does not implement are reported as `not_implemented`, and packs that never
lodged as `not_lodged`. Both are kept out of the pass and fail counts.

A pack that has a Claim needs every end-state read:

- from the claimant: the Claim, its evidence and its messages;
- from the staff sign-in: the Claim, its fields, handoffs, signals and evidence.

If any read is missing or not 200, the pack is reported as evidence incomplete and kept out of
every count.

## Evidence and limits

Run records stay outside the repository:

- screenshots of every turn and, for a stuck pack, of the screen it stopped on, taken by the runner
  itself (#1222 named the capture function of #1218, which was not merged);
- the claimant prompts and replies;
- the network log (authentication bodies are not recorded; tokens and passwords are masked);
- the claimant and staff end states.

A summary table goes on the issue or PR.

Not yet covered:

- a material available only later. The claimant is told to say it will have it later, but the
  runner does not hold the file back, and every material in corpus v1 is `available_from: start`;
- cost per pack. Standard `start-dev` does not keep the backend log, which is where model token
  counts are written, and the reply review's use is not logged.

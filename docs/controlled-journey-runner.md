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

Each pack's claimant is its own customer, signed in with the pack's name and email
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

The labels say what the claimant holds, the way a claimant would name it. The ten reference packs
were labelled by hand. The rest were drafted by the operator's local model from each file's content
alone, without the file name, evidence kind, provenance, setup or oracle, and then reviewed one by
one. Where a photo is unclear or a file is cut short on purpose, the label says what the claimant
photographed or holds.

It never sees evidence kinds, generation prompts, materials marked `include: false`, `setup.json`,
or `oracle/`. A leak check stops the run if any of those values reaches the prompt. The labels are
the runner's own text, so a label that repeats one of those values is caught too.

Each turn, the claimant model gets only what the screen shows:

- the latest reply;
- the cards under it;
- the to-do bar;
- the open service card;
- any alert;
- the buttons it can press.

Network traffic is recorded for evidence but never given to it. The claimant model replies with a
message, files to upload and at most one button to press. It answers only what is asked, invents
nothing, and sends each file once. When it presses a button, it does nothing else that turn.

The runner fills the payout form, the contact choice and the agreement checkboxes by fixed rules.
It logs in, adds the pack's phone to the profile so SMS can be chosen, and attaches files one at a
time. It presses Send only after every file shows Ready.

Uploads follow "Evidence kinds and the upload path" in the corpus standard:

- The screen lists the upload spots the claim offers for requested documents: the to-do bar, the
  "Still to do" list, a requested file under a reply, and the Documents cards.
- When the claimant sends a material the claim asks for, it names the matching spot. The runner
  uploads through that item's own input, so the file carries the kind the interface sends for that
  item.
- Other files go through the chat.
- The runner never copies `evidence_kind` from the pack. Each run records which path every file
  took (`upload_paths`).

## Recovery and stuck

A person's recoveries are allowed once each. A run that used one ends as `lodged_after_retry`,
never `lodged_first_time`. The recoveries are:

- pressing "Retry message" or "Retry response";
- answering a question once more when the agent asks it again. Each question sentence is tracked
  on its own, whatever else the reply asks with it, so each repeated question counts as one retry;
- after about nine seconds with nothing to act on, typing "OK.".

A pack is `stuck` when any of these happens:

- a second failure follows a recovery;
- the agent asks the same question a third time;
- after the nudge, there is still nothing to act on;
- the claimant reaches 30 messages;
- a file never shows Ready;
- a wait times out.

## Scoring

`score.cjs` is the only reader of `oracle/`. Every comparison is mechanical. Per pack and in
`summary.md` it reports:

- **Journey:** outcome, claim number, messages, agent questions, repeated questions, time, and the
  effort target (under five minutes and under ten questions, lodged runs only). Every question
  sentence counts as one question, a repeated one included, by the rule the runner uses to
  recognise a repeat.
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

- screenshots of every turn, taken by the runner itself (#1222 named the capture function of #1218,
  which was not merged);
- the claimant prompts and replies;
- the network log (authentication bodies are not recorded; tokens and passwords are masked);
- the claimant and staff end states.

A summary table goes on the issue or PR.

Not yet covered:

- packs whose `claimant_session` is `anonymous_then_sign_in` (recorded as `runner_not_implemented`);
- a material available only later. The claimant is told to say it will have it later, but the
  runner does not hold the file back, and every material in corpus v1 is `available_from: start`;
- cost per pack. Standard `start-dev` does not keep the backend log, which is where model token
  counts are written, and the reply review's use is not logged.

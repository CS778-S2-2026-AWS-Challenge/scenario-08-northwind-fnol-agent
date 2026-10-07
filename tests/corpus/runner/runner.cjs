// Controlled-corpus journey runner (#1222).
//
// Plays the claimant of each pack through the real claimant UI on start-dev, the way a person
// would, and records the run. Decisions use only what the screen shows; network traffic is
// recorded for evidence and scoring and is never given to the claimant model. The claimant model
// sees only the claimant view (claimant_view.cjs). Scoring is a separate step (score.cjs) and is
// the only reader of `oracle/`.
//
// A full run starts from empty stores (the journeys lodge real Claims, which become history):
//
//   1. stop the backend
//   2. node tests/corpus/runner/runner.cjs reset                       empty MongoDB and the claimant identities
//   3. start the backend with scripts/start-dev.ps1
//   4. node tests/corpus/runner/runner.cjs seed CTL-M-002 CTL-H-006 ...  seed every pack of the run once
//   5. node tests/corpus/runner/runner.cjs run  CTL-M-002 CTL-H-006 ...  run them, one after another
//
// Settings (environment):
//   CORPUS_CASES_DIR            the corpus `cases` folder (fetched release, outside git)
//   NORTHWIND_MONGODB_URI       reset and seed: the backend's MongoDB, which must be local
//   NORTHWIND_MONGODB_DATABASE  reset and seed: the backend's database (start-dev: northwind_fnol)
//   CORPUS_PYTHON               reset and seed: the Python that runs the backend (default: py -3.12)
//   CORPUS_BACKEND_REPO         the checkout the backend runs from, if not this one
//   CLAIMANT_BACKEND            ollama (default) or claude; see claimant_simulator.cjs
//   CLAIMANT_OLLAMA_URL         ollama: the operator's Ollama server, e.g. http://100.x.y.z:11434
//   CLAIMANT_MODEL              ollama: e.g. qwen3.8:27b; claude: e.g. haiku or sonnet (default haiku)
//   RUN_OUTPUT_DIR              where run records go; outside the repository
//   NORTHWIND_CUSTOMER_URL      default http://127.0.0.1:5173
//   NORTHWIND_API_URL           default http://127.0.0.1:8000
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')
const { execSync, spawnSync } = require('node:child_process')

const { buildClaimantView, hiddenValues, assertNoLeak } = require('./claimant_view.cjs')
const { buildClaimantPrompt, claimantKnownText, claimantFromEnvironment } = require('./claimant_simulator.cjs')
const { buildBusinessSeed, packKey, seedAccount } = require('./corpus_seed.cjs')

const MAX_CLAIMANT_MESSAGES = 30
// The payout panel's own error line, inside its contact form: a refused save or "Continue to
// agreement". Each attempt clears it when it starts. A failed load of the saved accounts shows its
// error elsewhere in the panel.
const PAYOUT_FORM_ERROR = '.payout-contact-panel form.payout-contact-section .backend-status[role=alert]'
// Presses of the claimant model that belong to a step: confirming the collected details (the
// review card's "All correct", a reply's "Looks right", the side panel's "Right") and submitting
// the claim. Any other press (a service card, a navigation button) is `press`. The payout panel's
// buttons sit in its forms and are left to fixed rules.
const STEP_PRESSES = [
  { press: /^(All correct|Looks right|Right)$/, action: 'confirmation' },
  { press: /^(Submit claim|Retry claim submission)$/, action: 'agreement' },
]
// The composer's error line, where the product shows the error of most requests (`showError`).
const COMPOSER_ERROR = 'form.workspace-composer .backend-status[role=alert]'
// The rail's "New chat" button. The product disables it whenever a request runs (`isBusy`),
// whichever panel is on the screen; its label reads "Saving..." while a session pause is being saved.
const APP_BUSY = '.intake-history .history-actions button[aria-label="New chat"], .intake-history .history-actions button[aria-label="Saving..."]'
const MEDIA = { '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.pdf': 'application/pdf' }
const LABELS = require('./material-labels.json')

function required(name) {
  const value = (process.env[name] || '').trim()
  if (!value) throw new Error(`${name} is required`)
  return value
}

const CUSTOMER = process.env.NORTHWIND_CUSTOMER_URL || 'http://127.0.0.1:5173'
const API = process.env.NORTHWIND_API_URL || 'http://127.0.0.1:8000'
const REPO = path.resolve(__dirname, '..', '..', '..')
// The checkout the backend runs from: its code provisions the seed, and its working directory
// holds the claimant identity file. The same repository unless set.
const BACKEND_REPO = path.resolve((process.env.CORPUS_BACKEND_REPO || '').trim() || REPO)

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'))
}

// ---------- stores: reset and seed ----------

// corpus_store.py runs on the backend's own code and settings, from the repository root.
function runStore(args) {
  const python = (process.env.CORPUS_PYTHON || '').trim()
  const [command, ...prefix] = python ? [python] : ['py', '-3.12']
  const result = spawnSync(command, [...prefix, path.join(__dirname, 'corpus_store.py'), ...args], { cwd: BACKEND_REPO, env: { ...process.env, PYTHONPATH: BACKEND_REPO }, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`corpus_store.py ${args[0]} failed: ${(result.stderr || result.stdout).trim().split('\n').slice(-3).join(' ')}`)
  return result.stdout.trim()
}

// One manifest for every pack of the run, kept with the run records, then provisioned.
function seedPacks(caseIds) {
  const manifest = buildBusinessSeed(required('CORPUS_CASES_DIR'), caseIds)
  const outDir = required('RUN_OUTPUT_DIR')
  fs.mkdirSync(outDir, { recursive: true })
  const file = path.join(outDir, 'corpus-business-seed.json')
  fs.writeFileSync(file, JSON.stringify(manifest, null, 1))
  return `${runStore(['seed', file])} (manifest ${file})`
}

// ---------- preflight ----------

async function preflight() {
  const response = await fetch(`${API}/health/ready`)
  const ready = await response.json()
  const checks = ready.checks || {}
  // start-dev reports `degraded` because the AWS adapters are pending; only `unavailable` stops a run.
  if (!['ready', 'degraded'].includes(ready.status)) throw new Error(`backend not ready: ${ready.status}`)
  if (checks.agent !== 'configured') throw new Error('the backend runs the controlled agent; the runner needs start-dev with the configured model')
  if (checks.data_runtime_profile !== 'local_mvp') throw new Error(`the backend profile is ${checks.data_runtime_profile}; the runner needs start-dev (local_mvp)`)
  if (!['development', 'test'].includes(checks.environment)) throw new Error(`environment ${checks.environment} is not development or test`)
  return checks
}

// ---------- the screen (what a person sees) ----------

// Each question sentence of a reply, normalised so the same question asked again matches, whatever
// else the reply asks with it. A list number in front is dropped; a question is listed once.
// The scorer counts questions with the same rule.
function questionSentences(reply) {
  const questions = String(reply)
    .split(/(?<=[.!?])\s+|\n+/)
    .filter((sentence) => sentence.includes('?'))
    .map((sentence) => sentence.toLowerCase().replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim().replace(/^\d+ /, ''))
    .filter(Boolean)
  return [...new Set(questions)]
}

// Records the questions of one reply in `asked` (question -> times asked) and says which were
// asked a second time (the claimant answers each once more) and which a third time (stuck, #1222).
function trackQuestions(asked, reply) {
  const repeated = []
  const third = []
  for (const question of questionSentences(reply)) {
    const times = (asked.get(question) || 0) + 1
    asked.set(question, times)
    if (times === 2) repeated.push(question)
    if (times >= 3) third.push(question)
  }
  return { repeated, third }
}

// Actions a person tries once more when the product refuses them, each with its own count:
// confirming the details ("All correct", "Looks right", "Right"), saving the payout step and
// submitting the claim.
const REFUSABLE = {
  confirmation: { field: 'confirmation_refusals', step: 'confirmation', what: 'confirmation' },
  payout: { field: 'payout_refusals', step: 'payout', what: 'payout step' },
  agreement: { field: 'agreement_refusals', step: 'agreement', what: 'claim submission' },
}

// Records one refusal shown by the product (`by` is `claimant` or `runner`). The first refusal of
// an action is the pack's one recovery for it and counts as a retry; a second refusal of the same
// action, by either, ends the pack as stuck. Returns true when the pack has to stop.
function recordRefusal(record, action, by, alert, at = new Date().toISOString()) {
  const { field, step, what } = REFUSABLE[action]
  record[field] = [...(record[field] || []), { by, alert, at }]
  if (record[field].length >= 2) {
    record.outcome = 'stuck'
    record.stuck = { step, reason: `${what} refused ${record[field].length} times: ${alert}` }
    return true
  }
  record.retries += 1
  record.retry_kinds = [...(record.retry_kinds || []), `${what} refused: ${alert}`]
  return false
}

// For each kind of press: the step a pack stops at when the product never answers it, how the
// step itself shows that its request is still running, and the error lines where the product shows
// a refusal of that request. Each request clears these lines when it starts.
// - confirmation: the pressed button stays disabled while the request runs, then is enabled again
//   or gone; the error is under the composer.
// - payout: the panel's buttons show "Saving…" whenever the product is busy, so during a save or
//   "Continue to agreement"; the error is the contact form's own line.
// - agreement: the submit button shows "Submitting…"; the error is the submission error card, or
//   the composer's line when the panel has been replaced.
// - press: any other press. Its result is the claimant's to read on the next screen, so no error is
//   read here; the runner only waits for the request, if the press started one.
// A request also counts as running while the product's busy signal is on (`APP_BUSY`), so a panel
// replaced while its request runs is not taken for an answer.
const STEP_ANSWERS = {
  confirmation: {
    step: 'confirmation',
    errorLines: [COMPOSER_ERROR],
    running: async (page, pressed, pollMs) => (await pressed.count().catch(() => 0)) > 0 && !(await pressed.isEnabled({ timeout: pollMs }).catch(() => false)),
  },
  payout: {
    step: 'payout',
    errorLines: [PAYOUT_FORM_ERROR],
    running: async (page) => (await page.getByRole('button', { name: 'Saving…' }).count().catch(() => 0)) > 0,
  },
  agreement: {
    step: 'agreement',
    errorLines: ['.agreement-submission-error[role=alert]', COMPOSER_ERROR],
    running: async (page) => (await page.getByRole('button', { name: 'Submitting…' }).count().catch(() => 0)) > 0,
  },
  press: { step: 'press', errorLines: [], running: async () => false },
}

// Whether the product shows a request running: its "New chat" button disabled. False when the
// rail is not on the screen.
async function appBusy(page, pollMs = 250) {
  const button = page.locator(APP_BUSY).first()
  return (await button.count().catch(() => 0)) > 0 && !(await button.isEnabled({ timeout: pollMs }).catch(() => true))
}

// The workspace must show the product's busy signal: without it a panel replaced mid-request would
// read as an answer. Throws when the conversation is on the screen but the signal is not.
async function requireBusySignal(page) {
  if ((await page.locator(APP_BUSY).count().catch(() => 0)) > 0) return
  if ((await page.locator('form.workspace-composer').count().catch(() => 0)) === 0) return
  throw new Error('the product\'s busy signal (the rail\'s "New chat" button) is not on the screen')
}

// After a press that asks the product to act (`action`, a key of STEP_ANSWERS): waits, by clock
// time, until the product has answered. Returns `{ alert }`, the error it showed, or null when it
// accepted; or `{ timedOut: true }` when the request is still running at the deadline. Then what
// the product did is unknown, and the caller stops the pack at that step rather than guess.
async function pressOutcome(page, action, pressed, { timeoutMs = 20000, pollMs = 250 } = {}) {
  const { errorLines, running } = STEP_ANSWERS[action]
  const readError = async () => {
    for (const selector of errorLines) {
      const text = ((await page.locator(selector).first().innerText({ timeout: pollMs }).catch(() => null)) || '').replace(/\s+/g, ' ').trim()
      if (text) return text
    }
    return null
  }
  const deadline = Date.now() + timeoutMs
  await page.waitForTimeout(pollMs)
  for (;;) {
    const error = await readError()
    if (error) return { alert: error }
    if (!(await running(page, pressed, pollMs)) && !(await appBusy(page, pollMs))) return { alert: await readError() }
    if (Date.now() >= deadline) return { timedOut: true, waitedMs: timeoutMs }
    await page.waitForTimeout(pollMs)
  }
}

// Records the product's answer to a press of `label` by `by` (`claimant` or `runner`): a refusal is
// counted (`recordRefusal`), and no answer by the deadline ends the pack at the press's step.
// Returns true when the pack has to stop.
// `busyBefore`: the product already had a request running before the press, so a timeout is not
// this press's alone, and the reason says so.
function recordAnswer(record, action, by, label, outcome, { busyBefore = false } = {}) {
  if (outcome.timedOut) {
    const seconds = Math.round(outcome.waitedMs / 1000)
    record.outcome = 'stuck'
    record.stuck = { step: STEP_ANSWERS[action].step, reason: busyBefore ? `the product was already busy before "${label}" and still busy ${seconds} s after it` : `no answer to "${label}" within ${seconds} s` }
    return true
  }
  return outcome.alert ? recordRefusal(record, action, by, outcome.alert) : false
}

// After the claimant model's press of `label` (the tagged button `pressed`): waits for the product's
// answer as the press's kind requires (`STEP_PRESSES`) and records it. `busyBefore` says whether
// the product was busy just before the press (some buttons under a reply stay enabled while it
// is). Returns true when the pack has to stop.
async function claimantPressAnswered(page, record, label, pressed, { busyBefore = false, ...options } = {}) {
  const action = (STEP_PRESSES.find((entry) => entry.press.test(label)) || { action: 'press' }).action
  return recordAnswer(record, action, 'claimant', label, await pressOutcome(page, action, pressed, options), { busyBefore })
}

// Which saved payout account to select when the form shows none selected: the first one that can
// be chosen, or -1 when one is already selected or none can be.
function payoutDestinationToSelect(options) {
  if (options.some((option) => option.checked)) return -1
  return options.findIndex((option) => !option.disabled)
}

// The materials of one message whose file the tray shows as "Processing failed". The product
// leaves such a file out of the message, so it is not sent: its upload path is marked
// `processing: failed, sent: false`, and only the other files count as sent. `touched` lists the
// tray entries this message's uploads added or changed (`watchTray`), with their final labels.
// Entries left from earlier messages are not in it, and a file sent again through a requested
// item's own upload, which reuses the earlier entry, is. A file failed when every entry of its name
// that the uploads touched shows "Processing failed".
function markProcessingFailed(usable, sentVia, touched) {
  const failed = usable.filter((entry) => {
    const mine = touched.filter((item) => item.name === entry.material.file)
    return mine.length > 0 && mine.every((item) => item.label === 'Processing failed')
  }).map((entry) => entry.material.id)
  const paths = sentVia.map((entry) => (failed.includes(entry.material) ? { ...entry, processing: 'failed', sent: false } : entry))
  const sent = usable.map((entry) => entry.material.id).filter((id) => !failed.includes(id))
  return { failed, sent, paths }
}

// Watches the composer's file tray, in the page, while one message's files upload. Every file
// entry the uploads add, or change in place (a file sent again through a requested item's own
// upload reuses that item's entry), is recorded; entries left from earlier messages are not.
// The whole page is watched, because an anonymous sign-in in the middle replaces the workspace and
// its composer; only entries inside a composer form are kept. Returns a function that stops
// watching and gives those entries' names and final labels.
async function watchTray(page) {
  await page.evaluate(() => {
    window.__corpusTrayObserver?.disconnect()
    const touched = new Set()
    const own = (node) => (node && (node.nodeType === 1 ? node : node.parentElement))?.closest?.('.composer-file-copy')
    const added = (node) => (node.nodeType !== 1 ? [] : node.matches('.composer-file-copy') ? [node] : [...node.querySelectorAll('.composer-file-copy')])
    const record = (mutations) => {
      for (const mutation of mutations) {
        const entry = own(mutation.target)
        if (entry) touched.add(entry)
        if (mutation.type === 'childList') mutation.addedNodes.forEach((node) => added(node).forEach((copy) => touched.add(copy)))
      }
    }
    const observer = new MutationObserver(record)
    observer.observe(document.body, { subtree: true, childList: true, characterData: true })
    window.__corpusTrayObserver = observer
    window.__corpusTrayRecord = record
    window.__corpusTrayTouched = touched
  })
  return () => page.evaluate(() => {
    const observer = window.__corpusTrayObserver
    if (observer) {
      window.__corpusTrayRecord(observer.takeRecords())
      observer.disconnect()
    }
    return [...(window.__corpusTrayTouched || [])].filter((node) => node.isConnected && node.closest('form.workspace-composer')).map((node) => ({
      name: (node.querySelector('strong')?.textContent || '').trim(),
      label: (node.querySelector('small')?.textContent || '').trim(),
    }))
  })
}

// Sending a file again after the product could not process it is a person's recovery: each such
// file of a message counts as one retry.
function recordFileRetries(record, materials) {
  for (const material of materials.filter((id) => (record.processing_failed || []).includes(id))) {
    record.retries += 1
    record.retry_kinds = [...(record.retry_kinds || []), `file sent again after processing failed: ${material}`]
  }
}

// Whether a material may be handed over: not already sent, and not failed twice already. A file
// the product could not process may be tried once more, as a person would; after a second
// failure it is not sent again.
function mayHandOver(record, material) {
  return !record.uploads.includes(material) && (record.processing_failed || []).filter((id) => id === material).length < 2
}

// Which upload input a material goes through: the requested item's own spot when the claimant
// named one, otherwise (`null`) the chat. A named spot that is not on the screen stops the pack,
// before or after any sign-in: the file is never sent through the chat instead, which would record
// it under a different evidence kind (corpus standard, "Evidence kinds and the upload path").
function uploadSpotIndex(spots, spot) {
  if (!spot) return null
  const index = spots.indexOf(spot)
  if (index < 0) throw new Error(`the upload spot "${spot}" the claimant named is not on the screen; the file was not sent another way`)
  return index
}

// In the page: the places where the claim asks for a document and offers its own upload (the
// to-do bar, the "Still to do" list, a requested file under a reply, a Documents card). A file
// uploaded there carries the requested item's evidence kind; the chat composer records every
// PDF as `other_document` (docs/controlled-test-corpus.md, "Evidence kinds and the upload path").
// Each input is tagged so the runner uploads to exactly the spot the claimant named.
function uploadSpotsInPage() {
  const visible = (node) => node && node.getBoundingClientRect().width > 0
  const spots = [
    ['.open-items-bar', '.open-items-bar-text'],
    ['li.open-item', 'strong'],
    ['.turn-chip', '.turn-chip-text'],
    ['li.claim-document-card', 'h4'],
  ]
  for (const node of document.querySelectorAll('[data-corpus-upload]')) node.removeAttribute('data-corpus-upload')
  const titles = []
  for (const [container, titleSelector] of spots) {
    for (const node of document.querySelectorAll(container)) {
      const input = node.querySelector('input[type=file]')
      if (!input || !visible(node)) continue
      const title = (node.querySelector(titleSelector)?.innerText || '').replace(/\s+/g, ' ').trim()
      if (!title || titles.includes(title)) continue
      input.setAttribute('data-corpus-upload', String(titles.length))
      titles.push(title)
    }
  }
  return titles
}

async function screenText(page) {
  const now = await screenTextOnly(page)
  const uploadSpots = await page.evaluate(uploadSpotsInPage)
  if (uploadSpots.length) now.screen += `\nUpload spots the claim offers for requested documents: ${uploadSpots.map((title) => `"${title}"`).join(', ')}`
  return { ...now, uploadSpots }
}

async function screenTextOnly(page) {
  return page.evaluate(() => {
    const visible = (node) => node && node.getBoundingClientRect().width > 0
    const text = (node) => (node ? node.innerText.replace(/\s+\n/g, '\n').trim() : '')
    // Only replies with text count; the "Preparing a response" row is an agent row without text.
    const agents = [...document.querySelectorAll('article.msg-agent')].filter((node) => visible(node) && node.querySelector('.agent-text'))
    const last = agents[agents.length - 1]
    const reply = last ? text(last.querySelector('.agent-text')) : ''
    const under = last ? text(last.querySelector('.turn-attachments')) : ''
    const bar = [...document.querySelectorAll('.open-items-bar')].filter(visible).map(text).join(' | ')
    const alerts = [...document.querySelectorAll('[role=alert]')].filter(visible).map(text).filter(Boolean).join(' | ')
    // An open service card: what it is for, what it shares and the permission it asks for.
    const card = [...document.querySelectorAll('.conversation-action-purpose, .shared-data-list, .service-consent')].filter(visible).map(text).filter(Boolean).join(' | ')
    // Buttons the claimant could press: under the latest reply, then under earlier replies (a
    // person scrolls up when told to review "the summary above"), in the to-do bar and in the side
    // panel. Edit buttons and form controls (the fixed-rule forms) are left out. Each one is
    // tagged so the runner can press exactly the button the claimant named. A disabled button is
    // left out too, except a service card's "Agree…": the product keeps it disabled until the card's
    // permission box is ticked, and a person ticks the box as part of agreeing.
    const agreeAwaitingTick = (button) => /^Agree\b/.test((button.innerText || '').trim())
      && Boolean(button.closest('.conversation-action-card')?.querySelector('.service-consent input[type=checkbox]:not(:checked):not(:disabled)'))
    const earlier = agents.slice(0, -1).reverse().map((node) => node.querySelector('.turn-attachments')).filter(Boolean)
    const scopes = [last && last.querySelector('.turn-attachments'), ...earlier, ...document.querySelectorAll('.open-items-bar, .intake-details-panel')].filter(Boolean)
    const pressable = []
    const earlierCards = []
    for (const node of document.querySelectorAll('[data-corpus-press]')) node.removeAttribute('data-corpus-press')
    for (const scope of scopes) {
      const before = pressable.length
      for (const button of scope.querySelectorAll('button')) {
        if (!visible(button) || (button.disabled && !agreeAwaitingTick(button)) || button.closest('form')) continue
        // Section toggles carry their whole summary as text; the first words name the button.
        const full = (button.innerText || button.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim()
        const label = full.length > 60 ? `${full.slice(0, 57)}…` : full
        // Upload buttons open the system file picker; the claimant sends files through `upload`.
        // Panel chrome ("Close panel", "×") only moves the view and decides nothing.
        if (!label || label === 'Edit' || /^Edit /.test(button.getAttribute('aria-label') || '') || /^Upload\b/.test(label) || /^(Close panel|×)$/.test(label) || pressable.includes(label)) continue
        button.setAttribute('data-corpus-press', String(pressable.length))
        pressable.push(label)
      }
      // An earlier card that still offers a button is shown too, so the claimant can read it.
      if (earlier.includes(scope) && pressable.length > before && earlierCards.length < 2) earlierCards.push(text(scope))
    }
    const lines = [`Northwind: ${reply || '(no reply yet)'}`]
    if (under) lines.push(`Shown under the reply: ${under}`)
    for (const cardText of earlierCards) lines.push(`Earlier card still open further up: ${cardText}`)
    if (bar) lines.push(`To-do bar: ${bar}`)
    if (card) lines.push(`Open card: ${card}`)
    if (alerts) lines.push(`Alert: ${alerts}`)
    if (pressable.length) lines.push(`Buttons you can press: ${pressable.map((label) => `"${label}"`).join(', ')}`)
    return { screen: lines.join('\n'), reply, agentCount: agents.length, pressable }
  })
}

// A turn is over when the failed-message retry shows, or when a new reply with text is on the page
// and the app is idle again: no "Preparing a response" row and the send button is not queueing.
async function waitForTurn(page, previousCount, timeoutMs = 180000) {
  await page.waitForFunction((count) => {
    const buttons = [...document.querySelectorAll('button')].map((b) => b.textContent.trim())
    // A failed send shows "Retry message →" on the send button; a reply the app could not put
    // together shows "Retry response" under the claimant's message. Either ends the turn.
    // Only an enabled one counts: it stays on screen, disabled, while the app retries.
    const retryReady = [...document.querySelectorAll('button')].some((b) => !b.disabled && /^Retry message|^Retry response$/.test(b.textContent.trim()))
    if (retryReady) return true
    const replies = document.querySelectorAll('article.msg-agent .agent-text').length
    const preparing = /Preparing a response/.test(document.body.innerText)
    const queueing = buttons.some((label) => label.startsWith('Send after reply'))
    return replies > count && !preparing && !queueing
  }, previousCount, { timeout: timeoutMs })
  await page.waitForTimeout(800)
}

async function waitUntilIdle(page, timeoutMs = 180000) {
  await page.waitForFunction(() => {
    const buttons = [...document.querySelectorAll('button')].map((b) => b.textContent.trim())
    return !/Preparing a response/.test(document.body.innerText) && !buttons.some((label) => label.startsWith('Send after reply'))
  }, null, { timeout: timeoutMs })
}

// Authentication is a mechanical rule, never a claimant-model decision. Wait for the whole
// login handler (including promotion), not merely the token it stores before promotion starts.
async function signInSeededCustomer(page, account) {
  await page.fill('#customer-email', account.email)
  await page.fill('#customer-password', account.synthetic_password)
  await page.click('button.login-submit')
  await page.waitForFunction(() => !document.querySelector('form.login-form')
    || Boolean(document.querySelector('form.login-form [role=alert]')?.textContent), null, { timeout: 30000 })
  const error = await page.locator('form.login-form [role=alert]').textContent({ timeout: 500 }).catch(() => null)
  if (error) throw new Error(`sign-in failed: ${error}`)
  const token = await page.evaluate(() => localStorage.getItem('northwind.claimantToken'))
  if (!token) throw new Error('sign-in did not establish an authenticated session')
  return token
}

async function authenticatedRead(url, token) {
  const response = await fetch(`${API}${url}`, { headers: { Authorization: `Bearer ${token}` } })
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`)
  return response.json()
}

// Check isolation and add the phone before any Claim is started. These setup reads and writes
// are separate from the claimant's screen and are never passed to its model.
async function prepareSeededCustomer(caseId, facts, token) {
  const account = seedAccount(caseId, facts)
  const claims = await authenticatedRead('/api/v1/claims', token)
  const seeded = `clm_corpus_${packKey(caseId)}_p`
  const leftover = (claims.items || []).filter((item) => !String(item.claim_id).startsWith(seeded))
  if (leftover.length) throw new Error(`${account.email} already has ${leftover.length} claim(s) from an earlier run; reset the stores and seed again`)
  const profile = await authenticatedRead('/api/v1/account', token)
  if (profile.customer_id !== account.customer_id) throw new Error('sign-in returned a different seeded customer')
  if (facts['claimant.phone']) {
    const response = await fetch(`${API}/api/v1/account/profile`, { method: 'PATCH', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'If-Match': String(profile.revision) }, body: JSON.stringify({ phone: facts['claimant.phone'] }) })
    if (!response.ok) throw new Error(`profile setup: HTTP ${response.status}`)
  }
}

async function startClaimantSession(browser, page, session, caseId, facts) {
  const account = seedAccount(caseId, facts)
  if (session === 'signed_in') {
    await page.goto(`${CUSTOMER}/auth/login`)
    await prepareSeededCustomer(caseId, facts, await signInSeededCustomer(page, account))
  } else {
    // A separate setup context checks the seeded account, then revokes its token and closes.
    // The journey context remains fresh: its first message uses only the anonymous identity.
    const setupContext = await browser.newContext()
    let token = null
    try {
      const setupPage = await setupContext.newPage()
      await setupPage.goto(`${CUSTOMER}/auth/login`)
      token = await signInSeededCustomer(setupPage, account)
      await prepareSeededCustomer(caseId, facts, token)
    } finally {
      try {
        if (token) {
          const response = await fetch(`${API}/api/v1/auth/session`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } })
          if (!response.ok) throw new Error(`setup sign-out: HTTP ${response.status}`)
        }
      } finally { await setupContext.close() }
    }
  }
  await page.goto(`${CUSTOMER}/`)
}

async function signInAnonymousClaim(page, account, claimId) {
  // Clicking the existing profile/login entry keeps App's current Claim in memory. Navigating
  // directly to /auth/login would reload it and could lose the promotion target.
  if (!(await page.locator('form.login-form').isVisible().catch(() => false))) await page.locator('button.intake-profile').click()
  const token = await signInSeededCustomer(page, account)
  await page.locator('#workspace-incident-input').waitFor({ state: 'visible', timeout: 30000 })
  const resumedId = (page.url().match(/\/claims\/(clm_[a-z0-9]+)(?:$|[?#])/) || [null, null])[1]
  if (resumedId !== claimId) throw new Error('sign-in did not return to the original anonymous Claim')
  const profile = await authenticatedRead('/api/v1/account', token)
  if (profile.customer_id !== account.customer_id) throw new Error('sign-in returned a different seeded customer')
  // Ownership is checked by the server. A swallowed promotion error must not let an upload
  // proceed under a token that cannot read this Claim. Do not call /promote as a repair.
  const claim = await authenticatedRead(`/api/v1/claims/${claimId}`, token)
  if (claim.claim_id !== claimId) throw new Error('sign-in read a different Claim')
  return claim
}

// `resolveInput` returns `{ input, via }`: the file input to use and the upload path it belongs to
// (a requested item's own spot, or `chat`). Returns the path the file was finally selected through.
async function selectClaimantFile(page, file, resolveInput, signIn) {
  const first = await resolveInput()
  await first.input.setInputFiles(file)
  if (!signIn) return first.via
  // Let the real product reject the anonymous selection. This is a visible login gate,
  // not an upload failure or a human recovery, and the selection has created no Evidence.
  await page.getByText('Sign in before uploading a file.', { exact: false }).first().waitFor({ timeout: 10000 })
  await signIn('upload')
  // Promotion rerenders the UI; resolve the upload spot again and make a fresh authenticated
  // selection. Neither the initial message nor the Claim is recreated. A requested item's own
  // spot that is gone after sign-in is never swapped for the chat, which would record the file
  // under a different evidence kind: the pack stops instead.
  const again = await resolveInput()
  if (first.via !== 'chat' && again.via !== first.via) {
    throw new Error(`the upload spot "${first.via}" was not on the screen after sign-in; the file was not sent another way`)
  }
  await again.input.setInputFiles(file)
  return again.via
}

// The payout and contact step (fixed rules), read afresh on every poll until something is decided.
// - While the panel loads the saved accounts ("Loading saved payout accounts…"), it lists none and
//   keeps "Continue to agreement" disabled: the runner waits, up to `settleMs` of clock time.
// - With no saved account the panel shows the new-account form, also after a failed load: that is
//   `form`, for its own rule.
// - If the panel is replaced, or the button shows "Saving…", the step returns `gone` and the main
//   loop reads the screen again.
// - Otherwise the runner picks the contact method and the saved account whenever none is selected
//   (the panel can come back without them), and presses the button once it is enabled.
// - A button still disabled `enableMs` after the panel loaded ends the pack as stuck.
// - After the press it waits for the product's answer (`pressOutcome`). A refusal (a failed save,
//   a conflict) is the one retry, and a second ends the pack; no answer within `answerMs` ends it.
async function payoutStep(page, continueButton, facts, record, { settleMs = 30000, enableMs = 30000, answerMs = 20000, pollMs = 500 } = {}) {
  const panel = page.locator('.payout-contact-panel')
  const loading = panel.locator('.payout-contact-status', { hasText: 'Loading saved payout accounts' })
  const started = Date.now()
  let loadedAt = null
  for (;;) {
    if (await loading.isVisible().catch(() => false)) {
      if (Date.now() - started >= settleMs) return { done: 'stuck', reason: `saved payout accounts were still loading after ${Math.round(settleMs / 1000)} s` }
      record.payout_loading_waits = (record.payout_loading_waits || 0) + 1
      loadedAt = null
      await page.waitForTimeout(pollMs)
      continue
    }
    if (await page.locator('#payout-bank-name').isVisible().catch(() => false)) return { done: 'form' }
    if ((await continueButton.count().catch(() => 0)) === 0) return { done: 'gone' }
    loadedAt ??= Date.now()

    const wanted = String(facts['claimant.contact_preference'] || 'email').toLowerCase()
    const contacts = await page.locator('input[name=contact_preference]').evaluateAll((nodes) => nodes.map((n) => ({ value: n.value, disabled: n.disabled, checked: n.checked })))
    const pick = contacts.find((o) => o.value === wanted && !o.disabled) || contacts.find((o) => o.value === 'email' && !o.disabled)
    if (pick && !pick.checked) await page.locator(`input[name=contact_preference][value="${pick.value}"]`).check()
    record.contact_preference = pick ? pick.value : null
    const destinations = page.locator('input[name=payout_destination]')
    const select = payoutDestinationToSelect(await destinations.evaluateAll((nodes) => nodes.map((node) => ({ checked: node.checked, disabled: node.disabled }))))
    if (select >= 0) {
      await destinations.nth(select).check()
      record.payout_reselected = (record.payout_reselected || 0) + 1
    }

    if (await continueButton.isEnabled({ timeout: pollMs }).catch(() => false)) {
      await continueButton.click()
      const answer = await pressOutcome(page, 'payout', continueButton, { timeoutMs: answerMs, pollMs })
      if (recordAnswer(record, 'payout', 'runner', 'Continue to agreement', answer)) return { done: 'stuck', reason: record.stuck.reason }
      return { done: 'continued' }
    }
    if (Date.now() - loadedAt >= enableMs) return { done: 'stuck', reason: `"Continue to agreement" stayed disabled for ${Math.round(enableMs / 1000)} s with the payout account and contact method chosen` }
    await page.waitForTimeout(pollMs)
  }
}

// The payout panel's new-account form (fixed rule). Returns true when the pack has to stop.
// - The panel shows the form for a moment before it starts loading the saved accounts; only a
//   form still there a second later is filled.
// - A form shown again (another account asked for, or a save refused) is filled again, four times
//   at most.
// - After "Save payout account" it waits for the product's answer (`pressOutcome`). A refusal
//   leaves the form on the screen with the error: the one retry, and a second ends the pack. No
//   answer within `answerMs` ends it too.
async function payoutAccountForm(page, facts, record, { settleMs = 1000, answerMs = 20000, pollMs = 250 } = {}) {
  const form = page.locator('#payout-bank-name')
  await page.waitForTimeout(settleMs)
  if (!(await form.isVisible().catch(() => false))) return false
  if (await page.locator('.payout-contact-panel .payout-contact-status', { hasText: 'Loading saved payout accounts' }).isVisible().catch(() => false)) return false
  if ((record.payout_account_saves || 0) >= 4) {
    record.outcome = 'stuck'
    record.stuck = { step: 'payout', reason: 'the new payout account form came back after four saves' }
    return true
  }
  record.payout_account_saves = (record.payout_account_saves || 0) + 1
  await page.fill('#payout-bank-name', 'Northwind Test Bank')
  await page.fill('#payout-account-holder-name', String(facts['policyholder.name'] || 'Corpus Claimant'))
  await page.fill('#payout-account-type', 'cheque')
  await page.fill('#payout-account-number', `12-3456-${String(crypto.randomInt(1e6, 9e6))}-00`)
  await page.getByRole('button', { name: 'Save payout account' }).click()
  const saved = await pressOutcome(page, 'payout', null, { timeoutMs: answerMs, pollMs })
  if (saved.alert && !(await form.isVisible().catch(() => false))) saved.alert = null
  if (recordAnswer(record, 'payout', 'runner', 'Save payout account', saved)) return true
  await page.waitForTimeout(1500)
  return false
}

// The agreement step (fixed rule): ticks every confirmation box, presses the submit button and
// waits for the product's answer. A refusal is the one retry, and a second ends the pack; no
// answer within `answerMs` ends it too. Returns true when the pack has to stop.
async function submitClaim(page, record, shot, { answerMs = 20000, pollMs = 250, settleMs = 5000 } = {}) {
  const submit = page.locator('button.agreement-submit')
  for (const box of await page.locator('.agreement-confirmation-option input[type=checkbox]').all()) {
    if (!(await box.isChecked())) await box.check()
  }
  await shot('agreement')
  const label = ((await submit.innerText().catch(() => '')) || '').trim() || 'Submit claim'
  await submit.click()
  if (recordAnswer(record, 'agreement', 'runner', label, await pressOutcome(page, 'agreement', submit, { timeoutMs: answerMs, pollMs }))) return true
  await page.waitForTimeout(settleMs)
  return false
}

// Agreeing to a service card's permission request means ticking that card's permission box
// first, as a person does; other cards' boxes are left alone.
async function tickPermission(page, button) {
  const card = page.locator('section.conversation-action-card').filter({ has: button })
  for (const box of await card.locator('.service-consent input[type=checkbox]').all()) {
    if (await box.isVisible() && !(await box.isChecked())) await box.check()
  }
}

// ---------- one pack ----------

async function runPack(browser, caseId, claimant, outRoot) {
  const casesDir = required('CORPUS_CASES_DIR')
  const caseDir = path.join(casesDir, caseId)
  const setup = readJson(path.join(caseDir, 'setup.json'))
  const facts = readJson(path.join(caseDir, 'input', 'facts.json')).facts
  const view = buildClaimantView(caseDir, LABELS)
  const hidden = hiddenValues(caseDir, claimantKnownText(view))
  const out = path.join(outRoot, caseId)
  fs.mkdirSync(path.join(out, 'screens'), { recursive: true })
  const record = { case_id: caseId, claimant_session: setup.claimant_session, claimant_model: claimant.info, started_at: new Date().toISOString(), outcome: null, stuck: null, claim_id: null, claim_number: null, claimant_messages: 0, retries: 0, repeated_questions: 0, nothing_to_answer: 0, turn_ms: [], uploads: [], upload_paths: [], presses: [], steps: [], cost_usd: 0 }
  const transcript = []
  const log = (name, line) => fs.appendFileSync(path.join(out, name), `${JSON.stringify(line)}\n`)

  if (!['signed_in', 'anonymous_then_sign_in'].includes(setup.claimant_session)) {
    record.outcome = 'runner_not_implemented'
    record.stuck = { step: 'start', reason: `claimant_session ${setup.claimant_session} is not driven yet` }
    fs.writeFileSync(path.join(out, 'run.json'), JSON.stringify(record, null, 1))
    return record
  }

  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  // Every API exchange is kept as evidence. Sign-in and sign-up carry a password and a session
  // token, so their bodies are not written; any other `access_token` is masked.
  const redact = (value) => JSON.parse(JSON.stringify(value ?? null, (key, item) => (/token|password/i.test(key) ? '(redacted)' : item)))
  page.on('response', async (response) => {
    const url = response.url()
    if (!url.includes('/api/')) return
    const pathname = new URL(url).pathname
    const secret = /\/auth\//.test(pathname)
    let body = null
    try { body = secret ? '(not recorded)' : redact(await response.json()) } catch { body = null }
    let sent = null
    try { sent = secret ? '(not recorded)' : redact(JSON.parse(response.request().postData() || 'null')) } catch { sent = '(binary or form data)' }
    log('network.jsonl', { at: new Date().toISOString(), method: response.request().method(), path: pathname, status: response.status(), request: sent, response: body })
  })
  let step = 0
  const shot = async (name) => {
    const next = step + 1
    const file = `${String(next).padStart(2, '0')}-${name}.png`
    await page.screenshot({ path: path.join(out, 'screens', file) })
    step = next
    record.steps.push({ step, name, file, at: new Date().toISOString() })
  }

  let operation = 'runner'
  let signedIn = setup.claimant_session === 'signed_in'
  try {
    const account = seedAccount(caseId, facts)
    await startClaimantSession(browser, page, setup.claimant_session, caseId, facts)
    const signIn = async (trigger) => {
      const during = operation
      operation = 'sign-in'
      record.anonymous_sign_in = { trigger, claim_id: record.claim_id, started_at: new Date().toISOString(), succeeded: false }
      await shot('sign-in-required')
      const claim = await signInAnonymousClaim(page, account, record.claim_id)
      signedIn = true
      Object.assign(record.anonymous_sign_in, { succeeded: true, conversation_session_id: claim.conversation_session_id, finished_at: new Date().toISOString() })
      await shot('signed-in')
      operation = during
    }

    // The first message, as written.
    await page.getByPlaceholder('Tell us what happened…').fill(view.initial_message)
    await shot('entry')
    const firstSent = Date.now()
    await page.getByRole('button', { name: /Start claim/ }).click()
    record.claimant_messages = 1
    transcript.push({ who: 'claimant', text: view.initial_message })
    await waitForTurn(page, 0)
    record.turn_ms.push(Date.now() - firstSent)
    record.claim_id = (page.url().match(/clm_[a-z0-9]+/) || [null])[0]
    await requireBusySignal(page)

    // Types `text`, attaches `files` one after another and presses Enter, the way a person does.
    // Returns a reason when the files never became ready.
    // `files` are `{ material, spot }`: the material, and the upload spot the claimant chose for it
    // ('' for the chat).
    const sendAsClaimant = async (text, files, count) => {
      const usable = files.filter((entry) => MEDIA[path.extname(entry.material.file).toLowerCase()])
      const sentVia = []
      let failedNow = []
      if (usable.length) {
        // One file per pick. A person picks the next file once the last one shows Ready in the
        // tray; any other label ("Uploading…", "Upload incomplete", "Processing") means the file
        // is not there yet. A file sent through a requested item's own upload also lands in
        // the tray, carrying that item's kind, and goes with the message.
        const trayLabels = () => page.locator('form.workspace-composer .composer-file-copy').evaluateAll((nodes) => nodes.map((node) => `${node.querySelector('strong')?.textContent?.trim()}: ${node.querySelector('small')?.textContent?.trim()}`))
        const trayTouched = await watchTray(page)
        recordFileRetries(record, usable.map((entry) => entry.material.id))
        for (const { material, spot } of usable) {
          const resolveInput = async () => {
            let index
            try {
              index = uploadSpotIndex(spot ? await page.evaluate(uploadSpotsInPage) : [], spot)
            } catch (error) {
              log('claimant.jsonl', { at: new Date().toISOString(), upload_spot_missing: spot, material: material.id, reason: 'no such upload spot on the screen; the pack stops' })
              throw error
            }
            if (index === null) return { input: page.locator('form.workspace-composer input[type=file]:not([aria-hidden="true"])'), via: 'chat' }
            return { input: page.locator(`[data-corpus-upload="${index}"]`), via: spot }
          }
          operation = 'upload'
          const via = await selectClaimantFile(page, path.join(caseDir, 'input', 'materials', material.file), resolveInput, signedIn ? null : signIn)
          operation = 'runner'
          sentVia.push({ material: material.id, via })
          await page.locator('form.workspace-composer .composer-attachments').getByText(material.file).first().waitFor({ timeout: 30000 })
          const ready = await page.waitForFunction(() => {
            const labels = [...document.querySelectorAll('form.workspace-composer .composer-file-copy small')].map((node) => (node.textContent || '').trim())
            return labels.length > 0 && labels.every((label) => label === 'Ready' || label === 'Processing failed')
          }, null, { timeout: 90000 }).then(() => true, () => false)
          if (!ready) return `file never showed Ready: ${(await trayLabels()).join('; ')}`
        }
        // A file the product cannot process shows "Processing failed" in the tray. That is the
        // product's answer about the file, not a stalled journey: a person sends the message
        // anyway. The product leaves that file out of the message, so the run records it as not
        // sent, and the claimant's transcript says so.
        const marked = markProcessingFailed(usable, sentVia, await trayTouched())
        failedNow = marked.failed
        if (failedNow.length) {
          record.processing_failed = [...(record.processing_failed || []), ...failedNow]
          log('claimant.jsonl', { at: new Date().toISOString(), processing_failed: failedNow, reason: 'the product could not process the file; it is left out of the message' })
        }
        record.uploads.push(...marked.sent)
        record.upload_paths.push(...marked.paths)
        // With no words of its own, the message says what happened to the files: the agent
        // receives no file the product could not process.
        if (!text) text = marked.sent.length ? 'Here you go.' : 'I tried to send the file, but it could not be processed.'
      }
      await page.locator('#workspace-incident-input').fill(text)
      // The pause a person takes between typing and pressing Enter.
      await page.waitForTimeout(1000)
      const sent = Date.now()
      await page.locator('#workspace-incident-input').press('Enter')
      record.claimant_messages += 1
      const attached = usable.filter((entry) => !failedNow.includes(entry.material.id)).map((entry) => (entry.spot ? `${entry.material.label} (to "${entry.spot}")` : entry.material.label))
      const notSent = usable.filter((entry) => failedNow.includes(entry.material.id)).map((entry) => entry.material.label)
      transcript.push({ who: 'claimant', text: `${text}${attached.length ? ` [attached: ${attached.join(', ')}]` : ''}${notSent.length ? ` [could not be processed, not sent: ${notSent.join(', ')}]` : ''}` })
      await waitForTurn(page, count)
      record.turn_ms.push(Date.now() - sent)
      return null
    }

    const askedBefore = new Map()
    let seenAgentCount = 0
    let answeredAgentCount = 0
    let lastAskedScreen = null
    // A button the claimant named that is not on the screen: they are asked once more, told so.
    let pressNote = null
    let notedScreen = null
    let stalls = 0
    let nudged = false
    let retriedThisTurn = false
    for (let guard = 0; guard < 80; guard += 1) {
      await waitUntilIdle(page)
      const now = await screenText(page)
      await shot('turn')
      const lodged = await page.getByText(/Claim NWF-[A-Z0-9-]+ lodged/).first().textContent({ timeout: 500 }).catch(() => null)
      if (lodged) {
        record.claim_number = (lodged.match(/NWF-[A-Z0-9-]+/) || [null])[0]
        record.outcome = record.retries ? 'lodged_after_retry' : 'lodged_first_time'
        break
      }
      // The payout card can require login even when the claimant has no files to send.
      const loginGate = page.getByRole('button', { name: 'Log in to continue', exact: true })
      if (!signedIn && await loginGate.isVisible().catch(() => false)) {
        await signIn('payout')
        lastAskedScreen = null
        continue
      }
      if (now.reply && now.agentCount > seenAgentCount) {
        seenAgentCount = now.agentCount
        stalls = 0
        transcript.push({ who: 'northwind', text: now.reply })
        // A question asked again is answered once more, as a person would: that is the one
        // recovery for that question and counts as a retry. Asked a third time, the journey is
        // stuck (#1222). Each question sentence is tracked on its own.
        const { repeated, third } = trackQuestions(askedBefore, now.reply)
        if (third.length) { record.outcome = 'stuck'; record.stuck = { step: 'conversation', reason: `the same question a third time: ${third.join(' | ')}` }; break }
        for (const question of repeated) {
          record.repeated_questions += 1
          record.retries += 1
          record.retry_kinds = [...(record.retry_kinds || []), `repeated question: ${question}`]
        }
      }

      // A failed message or a reply the app could not put together: a person presses retry once.
      const retry = page.getByRole('button', { name: /^Retry (message|response)/, disabled: false }).first()
      if (await retry.isVisible().catch(() => false)) {
        const which = (await retry.textContent()).replace(/\s+/g, ' ').trim()
        if (retriedThisTurn) { record.outcome = 'stuck'; record.stuck = { step: 'message', reason: `"${which}" again after one retry: ${now.screen.split('Alert: ')[1] || ''}` }; break }
        retriedThisTurn = true
        record.retries += 1
        record.retry_kinds = [...(record.retry_kinds || []), which]
        const count = now.agentCount
        await retry.click()
        // Give the app a moment to disable the retry button before reading the turn.
        await page.waitForTimeout(1500)
        await waitForTurn(page, count)
        continue
      }
      retriedThisTurn = false

      // A person reads the screen before the fixed-rule cards: whenever it changed, the claimant
      // decides first (type, attach, press a button), and the cards come only when they do nothing.
      if (now.reply && now.screen !== lastAskedScreen) {
        const newReply = now.agentCount > answeredAgentCount
        answeredAgentCount = now.agentCount
        lastAskedScreen = now.screen
        if (record.claimant_messages >= MAX_CLAIMANT_MESSAGES) { record.outcome = 'stuck'; record.stuck = { step: 'conversation', reason: `reached ${MAX_CLAIMANT_MESSAGES} claimant messages` }; break }
        const prompt = buildClaimantPrompt(view, transcript, pressNote ? `${now.screen}\nNote: ${pressNote}` : now.screen)
        pressNote = null
        assertNoLeak(prompt.system + prompt.brief, hidden)
        const reply = await claimant.ask(prompt)
        log('claimant.jsonl', { at: new Date().toISOString(), screen: now.screen, prompt: prompt.user, reply: reply.raw, model: reply.model, ms: reply.ms, tokens: reply.tokens, cost_usd: reply.cost_usd })
        record.cost_usd += reply.cost_usd || 0
        // A person sends each file once, and tries a file the product could not process once more;
        // any other repeat pick is dropped and logged.
        const repeats = reply.upload.filter((entry) => !mayHandOver(record, entry.material)).map((entry) => entry.material)
        if (repeats.length) log('claimant.jsonl', { at: new Date().toISOString(), ignored_upload: repeats, reason: 'already sent, or could not be processed twice' })
        const files = reply.upload
          .filter((entry) => mayHandOver(record, entry.material))
          .map((entry) => ({ material: view.materials.find((m) => m.id === entry.material), spot: entry.for }))
          .filter((entry) => entry.material)
        const text = reply.message.trim()
        const index = reply.press ? now.pressable.indexOf(reply.press) : -1
        if (reply.press && index < 0) log('claimant.jsonl', { at: new Date().toISOString(), ignored_press: reply.press, reason: 'not a button on the screen' })
        if (reply.press && index < 0 && !text && !files.length && notedScreen !== now.screen) {
          notedScreen = now.screen
          pressNote = `there is no "${reply.press}" button on the screen.`
          lastAskedScreen = null
          continue
        }
        if (index >= 0) {
          stalls = 0
          const button = page.locator(`[data-corpus-press="${index}"]`)
          if (/^Agree\b/.test(reply.press)) await tickPermission(page, button)
          // A button that cannot be pressed (covered, or gone after a re-render) is logged and the
          // claimant decides again from the next screen; it does not end the pack.
          const busyBefore = await appBusy(page)
          const pressed = await button.click({ timeout: 5000 }).then(() => true, (error) => {
            log('claimant.jsonl', { at: new Date().toISOString(), press_failed: reply.press, reason: error.message.split('\n')[0] })
            return false
          })
          if (!pressed) { lastAskedScreen = null; continue }
          record.presses.push(reply.press)
          transcript.push({ who: 'claimant', text: `(pressed "${reply.press}")` })
          await page.waitForTimeout(2500)
          if (await claimantPressAnswered(page, record, reply.press, button, { busyBefore })) break
          // Pressing is the whole action for this turn: a person who presses "Review and agree"
          // does not also type in the chat, and a chat message would reopen the claim summary.
          if (text || files.length) log('claimant.jsonl', { at: new Date().toISOString(), not_sent_with_press: { message: text, upload: files.map((entry) => entry.material.id) } })
          continue
        }
        if (text || files.length) {
          stalls = 0
          const problem = await sendAsClaimant(text, files, now.agentCount)
          if (problem) { record.outcome = 'stuck'; record.stuck = { step: 'upload', reason: problem }; break }
          continue
        }
        if (newReply) record.nothing_to_answer += 1
      }

      // The pinned review-and-submit card: fixed rules.
      // A disabled "All correct" (nothing left to check, or a request running) is not pressed.
      const allCorrect = page.getByRole('button', { name: 'All correct' })
      if (await allCorrect.isVisible().catch(() => false) && await allCorrect.isEnabled().catch(() => false)) {
        stalls = 0
        await allCorrect.click()
        await page.waitForTimeout(2500)
        if (recordAnswer(record, 'confirmation', 'runner', 'All correct', await pressOutcome(page, 'confirmation', allCorrect))) break
        continue
      }
      if (await page.locator('#payout-bank-name').isVisible().catch(() => false)) {
        stalls = 0
        if (await payoutAccountForm(page, facts, record)) break
        continue
      }
      const continueButton = page.getByRole('button', { name: 'Continue to agreement' })
      if (await continueButton.isVisible().catch(() => false)) {
        stalls = 0
        const step = await payoutStep(page, continueButton, facts, record)
        if (step.done === 'stuck') { record.outcome = 'stuck'; record.stuck = { step: 'payout', reason: step.reason }; break }
        if (step.done === 'continued') await page.waitForTimeout(2500)
        continue
      }
      if (await page.locator('button.agreement-submit').isVisible().catch(() => false)) {
        stalls = 0
        if (await submitClaim(page, record, shot)) break
        continue
      }

      // Nothing on the screen to act on: no unanswered reply and no card. A person waits a little,
      // then types "OK." once (the one human recovery, counted as a retry); after that it is stuck.
      stalls += 1
      if (stalls < 3) { await page.waitForTimeout(3000); continue }
      if (nudged) { record.outcome = 'stuck'; record.stuck = { step: 'conversation', reason: 'nothing to act on after one nudge' }; break }
      nudged = true
      stalls = 0
      record.retries += 1
      await sendAsClaimant('OK.', [], now.agentCount)
    }
    if (!record.outcome) { record.outcome = 'stuck'; record.stuck = { step: 'runner', reason: 'step guard reached' } }
  } catch (error) {
    record.outcome = 'stuck'
    record.stuck = { step: operation, reason: error.message.split('\n')[0] }
    await shot('error').catch(() => {})
  } finally {
    // A stuck pack keeps the screen it stopped on (an error has its own screenshot).
    if (record.outcome === 'stuck' && record.steps.at(-1)?.name !== 'error') await shot('stuck').catch(() => {})
    // The claimant-side end state, read the way the app reads it, for the scorer.
    if (record.claim_id) {
      const endState = await page.evaluate(async (claimId) => {
        const token = localStorage.getItem('northwind.claimantToken')
        const read = async (url) => {
          const headers = token ? { Authorization: `Bearer ${token}` } : { 'X-Northwind-Anonymous-Session': sessionStorage.getItem('northwind.anonymousSession') }
          const response = await fetch(url, { headers })
          return { status: response.status, body: response.ok ? await response.json() : await response.text() }
        }
        const claim = await read(`/api/v1/claims/${claimId}`)
        const evidence = await read(`/api/v1/claims/${claimId}/evidence`)
        const sessionId = claim.body && claim.body.conversation_session_id
        const messages = sessionId ? await read(`/api/v1/claims/${claimId}/sessions/${sessionId}/messages?limit=100`) : null
        return { 'claimant:claim': claim, 'claimant:evidence': evidence, 'claimant:messages': messages }
      }, record.claim_id).catch((error) => ({ error: error.message }))
      fs.writeFileSync(path.join(out, 'claimant.json'), JSON.stringify(endState, null, 1))
    }
    record.finished_at = new Date().toISOString()
    fs.writeFileSync(path.join(out, 'transcript.json'), JSON.stringify(transcript, null, 1))
    fs.writeFileSync(path.join(out, 'run.json'), JSON.stringify(record, null, 1))
    await context.close()
  }
  return record
}

// ---------- staff side ----------

async function staffReads(record, outRoot) {
  if (!record.claim_id) return
  const seed = readJson(path.join(BACKEND_REPO, 'config', 'staff-seed.json'))
  const login = await fetch(`${API}/api/v1/staff/auth/sessions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: 'bdfa123@northwind.test', password: seed.password }) })
  if (!login.ok) throw new Error(`staff sign-in failed: HTTP ${login.status}`)
  const { access_token: token } = await login.json()
  const reads = {}
  for (const suffix of ['', '/fields', '/handoffs', '/signals', '/evidence']) {
    const response = await fetch(`${API}/api/v1/workbench/claims/${record.claim_id}${suffix}`, { headers: { Authorization: `Bearer ${token}` } })
    reads[`staff:claim${suffix.replace('/', '.')}`] = { status: response.status, body: response.ok ? await response.json() : await response.text() }
  }
  fs.writeFileSync(path.join(outRoot, record.case_id, 'staff.json'), JSON.stringify(reads, null, 1))
}

// ---------- main ----------

async function main() {
  const [command, ...caseIds] = process.argv.slice(2)
  if (command === 'reset' && !caseIds.length) {
    // corpus_store.py refuses while the backend answers, and refuses a MongoDB that is not local.
    console.log(`reset: ${runStore(['reset'])}`)
    return
  }
  if (!caseIds.length || !['seed', 'run'].includes(command)) throw new Error('Usage: runner.cjs reset | seed CTL-M-002 [...] | run CTL-M-002 [...]')
  const checks = await preflight()
  if (command === 'seed') {
    console.log(`seed: ${seedPacks(caseIds)}`)
    return
  }
  const claimant = claimantFromEnvironment()
  const modelInfo = await claimant.describe()
  claimant.info = modelInfo
  const head = execSync(`git -C "${REPO}" rev-parse --short HEAD`).toString().trim()
  const backendHead = execSync(`git -C "${BACKEND_REPO}" rev-parse --short HEAD`).toString().trim()
  const outRoot = path.join(required('RUN_OUTPUT_DIR'), `${new Date().toISOString().replace(/[:.]/g, '-')}-${backendHead}`)
  fs.mkdirSync(outRoot, { recursive: true })
  fs.writeFileSync(path.join(outRoot, 'run-context.json'), JSON.stringify({ runner_head: head, backend_head: backendHead, backend_repo: BACKEND_REPO, backend: checks, claimant_model: modelInfo, packs: caseIds }, null, 1))
  const { chromium } = require('playwright')
  const browser = await chromium.launch()
  try {
    for (const caseId of caseIds) {
      const started = Date.now()
      const record = await runPack(browser, caseId, claimant, outRoot)
      // Without the staff reads the pack cannot be scored; the reason is kept with the run so the
      // scorer reports the pack as incomplete instead of scoring what is missing.
      const staffError = await staffReads(record, outRoot).then(() => null, (error) => error.message)
      if (staffError) {
        record.staff_read_error = staffError
        fs.writeFileSync(path.join(outRoot, caseId, 'run.json'), JSON.stringify(record, null, 1))
        console.log(`  staff reads failed: ${staffError}`)
      }
      console.log(`${caseId}: ${record.outcome}${record.claim_number ? ` ${record.claim_number}` : ''}${record.stuck ? ` (${record.stuck.step}: ${record.stuck.reason})` : ''}, ${record.claimant_messages} messages, ${Math.round((Date.now() - started) / 1000)} s`)
    }
  } finally {
    await browser.close()
  }
  console.log(`run records: ${outRoot}`)
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message)
    process.exit(1)
  })
}

module.exports = { questionSentences, trackQuestions, startClaimantSession, signInAnonymousClaim, selectClaimantFile, uploadSpotIndex, recordRefusal, pressOutcome, recordAnswer, claimantPressAnswered, requireBusySignal, submitClaim, payoutDestinationToSelect, markProcessingFailed, watchTray, mayHandOver, recordFileRetries, payoutStep, payoutAccountForm, screenTextOnly, tickPermission }

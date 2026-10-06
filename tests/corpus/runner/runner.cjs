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
const { buildClaimantPrompt, promptScaffold, claimantFromEnvironment } = require('./claimant_simulator.cjs')
const { buildBusinessSeed, packKey, seedAccount } = require('./corpus_seed.cjs')

const MAX_CLAIMANT_MESSAGES = 30
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

async function screenText(page) {
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
    // tagged so the runner can press exactly the button the claimant named.
    const earlier = agents.slice(0, -1).reverse().map((node) => node.querySelector('.turn-attachments')).filter(Boolean)
    const scopes = [last && last.querySelector('.turn-attachments'), ...earlier, ...document.querySelectorAll('.open-items-bar, .intake-details-panel')].filter(Boolean)
    const pressable = []
    const earlierCards = []
    for (const node of document.querySelectorAll('[data-corpus-press]')) node.removeAttribute('data-corpus-press')
    for (const scope of scopes) {
      const before = pressable.length
      for (const button of scope.querySelectorAll('button')) {
        if (!visible(button) || button.disabled || button.closest('form')) continue
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

// ---------- one pack ----------

async function runPack(browser, caseId, claimant, outRoot) {
  const casesDir = required('CORPUS_CASES_DIR')
  const caseDir = path.join(casesDir, caseId)
  const setup = readJson(path.join(caseDir, 'setup.json'))
  const facts = readJson(path.join(caseDir, 'input', 'facts.json')).facts
  const view = buildClaimantView(caseDir, LABELS)
  const hidden = hiddenValues(caseDir, view, promptScaffold())
  const out = path.join(outRoot, caseId)
  fs.mkdirSync(path.join(out, 'screens'), { recursive: true })
  const record = { case_id: caseId, claimant_session: setup.claimant_session, claimant_model: claimant.info, started_at: new Date().toISOString(), outcome: null, stuck: null, claim_id: null, claim_number: null, claimant_messages: 0, retries: 0, repeated_questions: 0, nothing_to_answer: 0, turn_ms: [], uploads: [], presses: [], steps: [], cost_usd: 0 }
  const transcript = []
  const log = (name, line) => fs.appendFileSync(path.join(out, name), `${JSON.stringify(line)}\n`)

  if (setup.claimant_session !== 'signed_in') {
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
    step += 1
    const file = `${String(step).padStart(2, '0')}-${name}.png`
    await page.screenshot({ path: path.join(out, 'screens', file) })
    record.steps.push({ step, name, file, at: new Date().toISOString() })
  }

  try {
    // Log in through the UI as the pack's seeded customer, so its policy and earlier claims are
    // the ones the system finds (fixed rule). The synthetic password is never written to a record.
    const account = seedAccount(caseId, facts)
    await page.goto(`${CUSTOMER}/auth/login`)
    await page.fill('#customer-email', account.email)
    await page.fill('#customer-password', account.synthetic_password)
    await page.click('button.login-submit')
    await page.waitForFunction(() => Boolean(localStorage.getItem('northwind.claimantToken')), null, { timeout: 30000 })
    const token = await page.evaluate(() => localStorage.getItem('northwind.claimantToken'))
    // The customer is used once per run: any Claim beyond its seeded earlier claims comes from an
    // earlier run and would count as history, so the stores need a reset first.
    const claims = await (await fetch(`${API}/api/v1/claims`, { headers: { Authorization: `Bearer ${token}` } })).json()
    const seeded = `clm_corpus_${packKey(caseId)}_p`
    const leftover = (claims.items || []).filter((item) => !String(item.claim_id).startsWith(seeded))
    if (leftover.length) throw new Error(`${account.email} already has ${leftover.length} claim(s) from an earlier run; reset the stores and seed again`)
    // A person would add their phone in the profile before choosing SMS; this does that step directly.
    if (facts['claimant.phone']) {
      const account = await (await fetch(`${API}/api/v1/account`, { headers: { Authorization: `Bearer ${token}` } })).json()
      await fetch(`${API}/api/v1/account/profile`, { method: 'PATCH', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'If-Match': String(account.revision) }, body: JSON.stringify({ phone: facts['claimant.phone'] }) })
    }

    // The first message, as written.
    await page.goto(`${CUSTOMER}/`)
    await page.getByPlaceholder('Tell us what happened…').fill(view.initial_message)
    await shot('entry')
    const firstSent = Date.now()
    await page.getByRole('button', { name: /Start claim/ }).click()
    record.claimant_messages = 1
    transcript.push({ who: 'claimant', text: view.initial_message })
    await waitForTurn(page, 0)
    record.turn_ms.push(Date.now() - firstSent)
    record.claim_id = (page.url().match(/clm_[a-z0-9]+/) || [null])[0]

    // Types `text`, attaches `files` one after another and presses Enter, the way a person does.
    // Returns a reason when the files never became ready.
    const sendAsClaimant = async (text, files, count) => {
      const usable = files.filter((m) => MEDIA[path.extname(m.file).toLowerCase()])
      if (usable.length) {
        // The composer takes one file per pick. A person picks the next file once the last one
        // shows Ready in the tray; any other label ("Uploading…", "Upload incomplete",
        // "Processing") means the file is not there yet.
        const trayLabels = () => page.locator('form.workspace-composer .composer-file-copy').evaluateAll((nodes) => nodes.map((node) => `${node.querySelector('strong')?.textContent?.trim()}: ${node.querySelector('small')?.textContent?.trim()}`))
        for (const material of usable) {
          await page.locator('form.workspace-composer input[type=file]:not([aria-hidden="true"])').setInputFiles(path.join(caseDir, 'input', 'materials', material.file))
          await page.locator('form.workspace-composer .composer-attachments').getByText(material.file).first().waitFor({ timeout: 30000 })
          const ready = await page.waitForFunction(() => {
            const labels = [...document.querySelectorAll('form.workspace-composer .composer-file-copy small')].map((node) => (node.textContent || '').trim())
            return labels.length > 0 && labels.every((label) => label === 'Ready' || label === 'Processing failed')
          }, null, { timeout: 90000 }).then(() => true, () => false)
          if (!ready) return `file never showed Ready: ${(await trayLabels()).join('; ')}`
        }
        const failed = await page.locator('form.workspace-composer .composer-file-copy small', { hasText: 'Processing failed' }).count()
        if (failed) return `${failed} file(s) showed Processing failed`
        record.uploads.push(...usable.map((m) => m.id))
        if (!text) text = 'Here you go.'
      }
      await page.locator('#workspace-incident-input').fill(text)
      // The pause a person takes between typing and pressing Enter.
      await page.waitForTimeout(1000)
      const sent = Date.now()
      await page.locator('#workspace-incident-input').press('Enter')
      record.claimant_messages += 1
      transcript.push({ who: 'claimant', text: usable.length ? `${text} [attached: ${usable.map((m) => m.label).join(', ')}]` : text })
      await waitForTurn(page, count)
      record.turn_ms.push(Date.now() - sent)
      return null
    }

    const askedBefore = new Map()
    let seenAgentCount = 0
    let answeredAgentCount = 0
    let lastAskedScreen = null
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
      if (now.reply && now.agentCount > seenAgentCount) {
        seenAgentCount = now.agentCount
        stalls = 0
        transcript.push({ who: 'northwind', text: now.reply })
        const key = now.reply.toLowerCase().replace(/[^a-z ]/g, '').trim()
        if (askedBefore.has(key)) record.repeated_questions += 1
        askedBefore.set(key, true)
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
        const prompt = buildClaimantPrompt(view, transcript, now.screen)
        assertNoLeak(prompt.system + prompt.brief, hidden)
        const reply = await claimant.ask(prompt)
        log('claimant.jsonl', { at: new Date().toISOString(), screen: now.screen, prompt: prompt.user, reply: reply.raw, model: reply.model, ms: reply.ms, tokens: reply.tokens, cost_usd: reply.cost_usd })
        record.cost_usd += reply.cost_usd || 0
        // A person sends each file once; a repeat pick is dropped and logged.
        const repeats = reply.upload.filter((id) => record.uploads.includes(id))
        if (repeats.length) log('claimant.jsonl', { at: new Date().toISOString(), ignored_upload: repeats, reason: 'already sent' })
        const files = reply.upload.filter((id) => !record.uploads.includes(id)).map((id) => view.materials.find((m) => m.id === id)).filter(Boolean)
        const text = reply.message.trim()
        const index = reply.press ? now.pressable.indexOf(reply.press) : -1
        if (reply.press && index < 0) log('claimant.jsonl', { at: new Date().toISOString(), ignored_press: reply.press, reason: 'not a button on the screen' })
        if (index >= 0) {
          stalls = 0
          const button = page.locator(`[data-corpus-press="${index}"]`)
          // Agreeing to a permission card means ticking its permission box first, as a person does.
          if (/^Agree/.test(reply.press)) {
            for (const box of await page.locator('.service-consent input[type=checkbox]').all()) {
              if (await box.isVisible() && !(await box.isChecked())) await box.check()
            }
          }
          // A button that cannot be pressed (covered, or gone after a re-render) is logged and the
          // claimant decides again from the next screen; it does not end the pack.
          const pressed = await button.click({ timeout: 5000 }).then(() => true, (error) => {
            log('claimant.jsonl', { at: new Date().toISOString(), press_failed: reply.press, reason: error.message.split('\n')[0] })
            return false
          })
          if (!pressed) { lastAskedScreen = null; continue }
          record.presses.push(reply.press)
          transcript.push({ who: 'claimant', text: `(pressed "${reply.press}")` })
          await page.waitForTimeout(2500)
          // Pressing is the whole action for this turn: a person who presses "Review and agree"
          // does not also type in the chat, and a chat message would reopen the claim summary.
          if (text || files.length) log('claimant.jsonl', { at: new Date().toISOString(), not_sent_with_press: { message: text, upload: files.map((m) => m.id) } })
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
      const allCorrect = page.getByRole('button', { name: 'All correct' })
      if (await allCorrect.isVisible().catch(() => false)) {
        stalls = 0
        await allCorrect.click()
        await page.waitForTimeout(2500)
        const alert = await page.locator('form.workspace-composer [role=alert]').first().textContent({ timeout: 500 }).catch(() => null)
        if (alert) {
          if (record.stuck?.step === 'review') { record.outcome = 'stuck'; record.stuck.reason = `confirmation rejected twice: ${alert}`; break }
          record.retries += 1
          record.stuck = { step: 'review', reason: alert }
        }
        continue
      }
      if (await page.locator('#payout-bank-name').isVisible().catch(() => false)) {
        stalls = 0
        await page.fill('#payout-bank-name', 'Northwind Test Bank')
        await page.fill('#payout-account-holder-name', String(facts['policyholder.name'] || 'Corpus Claimant'))
        await page.fill('#payout-account-type', 'cheque')
        await page.fill('#payout-account-number', `12-3456-${String(crypto.randomInt(1e6, 9e6))}-00`)
        await page.getByRole('button', { name: 'Save payout account' }).click()
        await page.waitForTimeout(2000)
        continue
      }
      const continueButton = page.getByRole('button', { name: 'Continue to agreement' })
      if (await continueButton.isVisible().catch(() => false)) {
        stalls = 0
        const wanted = String(facts['claimant.contact_preference'] || 'email').toLowerCase()
        const radios = page.locator('input[name=contact_preference]')
        const options = await radios.evaluateAll((nodes) => nodes.map((n) => ({ value: n.value, disabled: n.disabled })))
        const pick = options.find((o) => o.value === wanted && !o.disabled) || options.find((o) => o.value === 'email' && !o.disabled)
        if (pick) await page.locator(`input[name=contact_preference][value="${pick.value}"]`).check()
        record.contact_preference = pick ? pick.value : null
        await continueButton.click()
        await page.waitForTimeout(2500)
        continue
      }
      const submit = page.locator('button.agreement-submit')
      if (await submit.isVisible().catch(() => false)) {
        stalls = 0
        for (const box of await page.locator('.agreement-confirmation-option input[type=checkbox]').all()) {
          if (!(await box.isChecked())) await box.check()
        }
        await shot('agreement')
        await submit.click()
        await page.waitForTimeout(5000)
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
    record.stuck = { step: 'runner', reason: error.message.split('\n')[0] }
    await shot('error').catch(() => {})
  } finally {
    // The claimant-side end state, read the way the app reads it, for the scorer.
    if (record.claim_id) {
      const endState = await page.evaluate(async (claimId) => {
        const token = localStorage.getItem('northwind.claimantToken')
        const read = async (url) => {
          const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } })
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
  const seed = readJson(path.join(REPO, 'config', 'staff-seed.json'))
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
      await staffReads(record, outRoot).catch((error) => console.log(`  staff reads failed: ${error.message}`))
      console.log(`${caseId}: ${record.outcome}${record.claim_number ? ` ${record.claim_number}` : ''}${record.stuck ? ` (${record.stuck.step}: ${record.stuck.reason})` : ''}, ${record.claimant_messages} messages, ${Math.round((Date.now() - started) / 1000)} s`)
    }
  } finally {
    await browser.close()
  }
  console.log(`run records: ${outRoot}`)
}

main().catch((error) => {
  console.error(error.message)
  process.exit(1)
})

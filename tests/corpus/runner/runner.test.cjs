// The runner recognises the same question asked again (#1222). Nothing here opens a browser.
// Run with: node --test tests/corpus/runner/runner.test.cjs
const assert = require('node:assert/strict')
const { test } = require('node:test')

const { questionSentences, trackQuestions, startClaimantSession, signInAnonymousClaim, selectClaimantFile, uploadSpotIndex, recordRefusal, confirmationOutcome, payoutDestinationToSelect, markProcessingFailed, mayHandOver, recordFileRetries, payoutStep } = require('./runner.cjs')
const { seedAccount } = require('./corpus_seed.cjs')

test('each question sentence of a reply is listed on its own, normalised', () => {
  assert.deepEqual(questionSentences('Thanks for the details. What is the vehicle registration number?'), ['what is the vehicle registration number'])
  assert.deepEqual(questionSentences('Got it. What is the vehicle registration number?'), ['what is the vehicle registration number'])
  assert.deepEqual(questionSentences('Was anyone hurt? Is the car drivable?'), ['was anyone hurt', 'is the car drivable'])
  assert.deepEqual(questionSentences('A few things:\n1. When did it happen?\n2. Where was the car?'), ['when did it happen', 'where was the car'])
  assert.deepEqual(questionSentences('Is it drivable? Is it drivable?'), ['is it drivable'])
  assert.deepEqual(questionSentences('Your claim is ready. We will be in touch.'), [])
})

test('a question repeated inside replies that ask other things is answered once more, then stuck', () => {
  const asked = new Map()
  assert.deepEqual(trackQuestions(asked, 'What is the registration?'), { repeated: [], third: [] })
  assert.deepEqual(trackQuestions(asked, 'What is the registration? What colour is it?'), { repeated: ['what is the registration'], third: [] })
  assert.deepEqual(trackQuestions(asked, 'What is the registration? Is it drivable?'), { repeated: [], third: ['what is the registration'] })
})

test('questions asked once each are never a repeat, however they are grouped', () => {
  const asked = new Map()
  trackQuestions(asked, 'When did it happen? Where were you?')
  assert.deepEqual(trackQuestions(asked, 'Was anyone hurt?'), { repeated: [], third: [] })
  assert.deepEqual(trackQuestions(asked, 'Is the car drivable? Do you have photos?'), { repeated: [], third: [] })
})

// These doubles exercise runner orchestration and fail-closed boundaries. Real browser/Runtime
// promotion is separate evidence from the start-dev journeys, not claimed by these unit tests.
function loginPage(events, name, { claimId = 'clm_abc123', loginError = null } = {}) {
  let token = null
  return {
    goto: async (url) => events.push(`${name}:goto:${new URL(url).pathname}`),
    fill: async (selector) => events.push(`${name}:fill:${selector}`),
    click: async () => { events.push(`${name}:login`); token = loginError ? null : `${name}-token` },
    waitForFunction: async () => events.push(`${name}:login-handler-finished`),
    evaluate: async () => token,
    url: () => `http://127.0.0.1:5173/claims/${claimId}`,
    locator: (selector) => ({
      isVisible: async () => false,
      textContent: async () => loginError,
      click: async () => events.push(`${name}:open-login:${selector}`),
      waitFor: async () => events.push(`${name}:workspace-ready`),
    }),
  }
}

function seedApi(t, events, { leftover = false, promotionStatus = 200, customerId = 'cus_corpus_ctl_m_001', claimId = 'clm_abc123' } = {}) {
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    const pathname = new URL(url).pathname
    events.push(`api:${options.method || 'GET'}:${pathname}:${options.headers.Authorization}`)
    let status = 200
    let body
    if (pathname === '/api/v1/claims') body = { items: [{ claim_id: leftover ? 'clm_old123' : 'clm_corpus_ctl_m_001_p1' }] }
    else if (pathname === '/api/v1/account') body = { customer_id: customerId, revision: 3 }
    else if (pathname === '/api/v1/account/profile') body = {}
    else if (pathname === '/api/v1/auth/session') { status = 204; body = null }
    else if (pathname === '/api/v1/claims/clm_abc123') { status = promotionStatus; body = { claim_id: claimId, conversation_session_id: 'ses_original' } }
    else assert.fail(`unexpected API request ${pathname}`)
    return { ok: status >= 200 && status < 300, status, json: async () => body }
  })
}

test('anonymous setup uses and revokes a separate login, leaving the journey unsigned in', async (t) => {
  const events = []
  seedApi(t, events)
  const journey = loginPage(events, 'journey')
  const setup = loginPage(events, 'setup')
  const browser = { newContext: async () => ({ newPage: async () => setup, close: async () => events.push('setup:closed') }) }
  await startClaimantSession(browser, journey, 'anonymous_then_sign_in', 'CTL-M-001', { 'claimant.phone': '+64 00 000 9001' })
  assert.equal(await journey.evaluate(), null)
  assert.deepEqual(events.filter((event) => event.startsWith('journey:')), ['journey:goto:/'])
  assert.ok(events.includes('api:DELETE:/api/v1/auth/session:Bearer setup-token'))
  assert.ok(events.includes('api:PATCH:/api/v1/account/profile:Bearer setup-token'))
  assert.ok(events.indexOf('setup:closed') < events.indexOf('journey:goto:/'))
})

test('anonymous isolation failure revokes setup and never starts the journey', async (t) => {
  const events = []
  seedApi(t, events, { leftover: true })
  const browser = { newContext: async () => ({ newPage: async () => loginPage(events, 'setup'), close: async () => events.push('setup:closed') }) }
  await assert.rejects(startClaimantSession(browser, loginPage(events, 'journey'), 'anonymous_then_sign_in', 'CTL-M-001', {}), /earlier run/)
  assert.ok(events.includes('api:DELETE:/api/v1/auth/session:Bearer setup-token'))
  assert.equal(events.at(-1), 'setup:closed')
  assert.ok(!events.some((event) => event.startsWith('journey:')))
})

test('signed-in packs keep their login in the journey context', async (t) => {
  const events = []
  seedApi(t, events)
  const page = loginPage(events, 'journey')
  const browser = { newContext: async () => assert.fail('signed-in setup must use the journey context') }
  await startClaimantSession(browser, page, 'signed_in', 'CTL-M-001', {})
  assert.equal(await page.evaluate(), 'journey-token')
  assert.equal(events[0], 'journey:goto:/auth/login')
  assert.equal(events.at(-1), 'journey:goto:/')
})

test('anonymous file selection reaches the visible gate, promotes the same Claim, then reselects once', async (t) => {
  const events = []
  seedApi(t, events)
  const page = loginPage(events, 'journey')
  page.getByText = () => ({ first: () => ({ waitFor: async () => events.push('visible:sign-in-required') }) })
  let resolutions = 0
  const resolveInput = async () => {
    resolutions += 1
    return { input: { setInputFiles: async (file) => events.push(`select:${resolutions}:${file}`) }, via: 'chat' }
  }
  const account = seedAccount('CTL-M-001', {})
  let promoted
  await selectClaimantFile(page, 'photo.jpg', resolveInput, async (trigger) => {
    assert.equal(trigger, 'upload')
    promoted = await signInAnonymousClaim(page, account, 'clm_abc123')
  })
  assert.equal(promoted.claim_id, 'clm_abc123')
  assert.equal(promoted.conversation_session_id, 'ses_original')
  assert.deepEqual(events.filter((event) => /^select:|^visible:/.test(event)), ['select:1:photo.jpg', 'visible:sign-in-required', 'select:2:photo.jpg'])
  assert.ok(events.indexOf('visible:sign-in-required') < events.indexOf('journey:login'))
  assert.ok(events.indexOf('api:GET:/api/v1/claims/clm_abc123:Bearer journey-token') < events.indexOf('select:2:photo.jpg'))
  assert.ok(events.includes('journey:open-login:button.intake-profile'))
  assert.ok(!events.some((event) => /:goto:|\/promote|\/messages|POST:\/api\/v1\/claims/.test(event)), 'no navigation reload, direct promotion, new Claim or resent conversation')
})

test('anonymous login or promotion failure prevents authenticated file selection', async (t) => {
  for (const boundary of ['login', 'ownership', 'identity', 'claim', 'route', 'missing_gate']) {
    await t.test(boundary, async (t) => {
      const events = []
      seedApi(t, events, { promotionStatus: boundary === 'ownership' ? 403 : 200, customerId: boundary === 'identity' ? 'cus_other' : 'cus_corpus_ctl_m_001', claimId: boundary === 'claim' ? 'clm_other' : 'clm_abc123' })
      const page = loginPage(events, 'journey', { loginError: boundary === 'login' ? 'Credentials were refused.' : null, claimId: boundary === 'route' ? 'clm_other' : 'clm_abc123' })
      page.getByText = () => ({ first: () => ({ waitFor: async () => { if (boundary === 'missing_gate') throw new Error('no visible sign-in gate') } }) })
      let selections = 0
      await assert.rejects(selectClaimantFile(page, 'photo.jpg', async () => ({ input: { setInputFiles: async () => { selections += 1 } }, via: 'chat' }), () => signInAnonymousClaim(page, seedAccount('CTL-M-001', {}), 'clm_abc123')))
      assert.equal(selections, 1, 'no file is selected again when the product did not complete promotion')
      assert.ok(!events.some((event) => /\/promote|\/messages|POST:\/api\/v1\/claims/.test(event)))
      if (boundary === 'missing_gate') assert.ok(!events.some((event) => event === 'journey:login'))
    })
  }
})

test('authenticated file selection does not trigger another sign-in', async () => {
  const selected = []
  const via = await selectClaimantFile({ getByText: () => assert.fail('no anonymous gate') }, 'quote.pdf', async () => ({ input: { setInputFiles: async (file) => selected.push(file) }, via: 'Still to send: Repair quote' }), null)
  assert.deepEqual(selected, ['quote.pdf'])
  assert.equal(via, 'Still to send: Repair quote')
})

test('a requested upload spot gone after sign-in stops the file instead of switching to the chat', async (t) => {
  const SPOT = 'Still to send: Repair quote'
  const cases = [
    { name: 'spot kept', after: SPOT, selected: ['spot', 'spot'], via: SPOT },
    { name: 'spot gone', after: 'chat', selected: ['spot'], error: /"Still to send: Repair quote" was not on the screen after sign-in/ },
    { name: 'chat first, spot after', before: 'chat', after: SPOT, selected: ['chat', 'spot'], via: SPOT },
  ]
  for (const item of cases) {
    await t.test(item.name, async () => {
      const selected = []
      const paths = [item.before || SPOT, item.after]
      const resolveInput = async () => {
        const via = paths.shift()
        return { input: { setInputFiles: async () => selected.push(via === 'chat' ? 'chat' : 'spot') }, via }
      }
      const page = { getByText: () => ({ first: () => ({ waitFor: async () => {} }) }) }
      const run = selectClaimantFile(page, 'quote.pdf', resolveInput, async () => {})
      if (item.error) await assert.rejects(run, item.error)
      else assert.equal(await run, item.via)
      assert.deepEqual(selected, item.selected)
    })
  }
})

test('a named upload spot missing from the screen stops the file, signed in or before sign-in', async (t) => {
  const SPOT = 'Still to send: Proof of ownership'
  assert.equal(uploadSpotIndex(['Still to send: Repair quote', SPOT], SPOT), 1)
  assert.equal(uploadSpotIndex([SPOT], ''), null, 'no spot named: the chat')
  assert.throws(() => uploadSpotIndex(['Still to send: Repair quote'], SPOT), /"Still to send: Proof of ownership" the claimant named is not on the screen/)
  // The runner resolves the input from what the page shows; here the requested spot is absent.
  const absent = async () => {
    const index = uploadSpotIndex([], SPOT)
    return { input: { setInputFiles: async () => assert.fail('no file may be selected') }, via: index === null ? 'chat' : SPOT }
  }
  await t.test('signed in', async () => {
    await assert.rejects(selectClaimantFile({ getByText: () => assert.fail('no anonymous gate') }, 'receipt.pdf', absent, null), /not on the screen/)
  })
  await t.test('anonymous, before sign-in', async () => {
    let signIns = 0
    await assert.rejects(selectClaimantFile({ getByText: () => assert.fail('the gate is never reached') }, 'receipt.pdf', absent, async () => { signIns += 1 }), /not on the screen/)
    assert.equal(signIns, 0)
  })
})

test('a refused action is one retry, and a second refusal of the same action ends the pack', () => {
  const ALERT = 'One or more fields cannot be confirmed.'
  // CTL-M-009 and CTL-M-032: refused once, then lodged. Nothing may read as stuck afterwards.
  const recovered = { retries: 0, outcome: null, stuck: null }
  assert.equal(recordRefusal(recovered, 'confirmation', 'runner', ALERT, 't1'), false)
  assert.equal(recovered.retries, 1)
  assert.deepEqual(recovered.retry_kinds, [`confirmation refused: ${ALERT}`])
  assert.equal(recovered.stuck, null)
  assert.equal(recovered.outcome, null)
  // The pilot CTL-M-001: the claimant model pressed "All correct" and was refused, then the fixed
  // rule was refused too. Both count, so the second refusal ends the pack.
  const twice = { retries: 0, outcome: null, stuck: null }
  assert.equal(recordRefusal(twice, 'confirmation', 'claimant', ALERT, 't1'), false)
  assert.equal(recordRefusal(twice, 'confirmation', 'runner', ALERT, 't2'), true)
  assert.equal(twice.outcome, 'stuck')
  assert.deepEqual(twice.stuck, { step: 'confirmation', reason: `confirmation refused 2 times: ${ALERT}` })
  assert.deepEqual(twice.confirmation_refusals.map((refusal) => refusal.by), ['claimant', 'runner'])
  assert.equal(twice.retries, 1)
  // Confirmation and the payout step are counted apart: one refusal of each is two recoveries.
  const apart = { retries: 0, outcome: null, stuck: null }
  assert.equal(recordRefusal(apart, 'confirmation', 'runner', ALERT, 't1'), false)
  assert.equal(recordRefusal(apart, 'payout', 'runner', 'Your report changed while this page was open.', 't2'), false)
  assert.equal(apart.outcome, null)
  assert.equal(apart.retries, 2)
  assert.equal(recordRefusal(apart, 'payout', 'runner', 'Your report changed while this page was open.', 't3'), true)
  assert.equal(apart.stuck.step, 'payout')
})

test('a payout form shown again selects the saved account only when none is selected', () => {
  assert.equal(payoutDestinationToSelect([{ checked: false, disabled: false }]), 0, 'CTL-C-013: the saved account listed but not selected')
  assert.equal(payoutDestinationToSelect([{ checked: true, disabled: false }, { checked: false, disabled: false }]), -1)
  assert.equal(payoutDestinationToSelect([{ checked: false, disabled: true }, { checked: false, disabled: false }]), 1)
  assert.equal(payoutDestinationToSelect([]), -1)
})

test('a file the product cannot process is recorded as not sent, and may be tried once more', () => {
  const usable = [{ material: { id: 'photo-watch', file: 'photo-watch.jpg' } }, { material: { id: 'receipt-watch', file: 'receipt-watch.pdf' } }]
  const sentVia = [{ material: 'photo-watch', via: 'chat' }, { material: 'receipt-watch', via: 'Still to send: Receipt' }]
  // The photo fails in this message; a quote failed earlier and is still in the tray.
  const marked = markProcessingFailed(usable, sentVia, ['quote-old.pdf'], ['quote-old.pdf', 'photo-watch.jpg'])
  assert.deepEqual(marked.failed, ['photo-watch'])
  assert.deepEqual(marked.sent, ['receipt-watch'])
  assert.deepEqual(marked.paths, [{ material: 'photo-watch', via: 'chat', processing: 'failed', sent: false }, { material: 'receipt-watch', via: 'Still to send: Receipt' }])
  assert.deepEqual(markProcessingFailed(usable, sentVia, [], []), { failed: [], sent: ['photo-watch', 'receipt-watch'], paths: sentVia })
  // Tried once more: the old failed entry keeps the same name in the tray. A second try that works
  // is sent; one that fails again is a new failed entry.
  const again = [{ material: { id: 'photo-watch', file: 'photo-watch.jpg' } }]
  const againVia = [{ material: 'photo-watch', via: 'chat' }]
  assert.deepEqual(markProcessingFailed(again, againVia, ['photo-watch.jpg'], ['photo-watch.jpg']).sent, ['photo-watch'])
  assert.deepEqual(markProcessingFailed(again, againVia, ['photo-watch.jpg'], ['photo-watch.jpg', 'photo-watch.jpg']).failed, ['photo-watch'])
  // Sending it again is a recovery; handing it over a third time is not allowed.
  const record = { retries: 0, uploads: ['receipt-watch'], processing_failed: ['photo-watch'] }
  assert.equal(mayHandOver(record, 'receipt-watch'), false, 'sent once already')
  assert.equal(mayHandOver(record, 'photo-watch'), true, 'failed once: one more try')
  recordFileRetries(record, ['photo-watch', 'repair-quote'])
  assert.equal(record.retries, 1)
  assert.deepEqual(record.retry_kinds, ['file sent again after processing failed: photo-watch'])
  record.processing_failed.push('photo-watch')
  assert.equal(mayHandOver(record, 'photo-watch'), false, 'failed twice: not sent again')
  assert.equal(mayHandOver(record, 'repair-quote'), true)
})

// A pressed confirmation button and the composer's error line, as the product renders them:
// the button is disabled while the request runs, then enabled again or gone, and the error (if
// any) appears when the answer arrives. `steps` lists the page state per poll.
function confirmationPage(steps) {
  let poll = 0
  const now = () => steps[Math.min(poll, steps.length - 1)]
  const page = {
    waitForTimeout: async () => { poll += 1 },
    locator: () => ({ first: () => ({ textContent: async () => { if (now().error) return now().error; throw new Error('no error line') } }) }),
  }
  const pressed = { count: async () => (now().button === 'gone' ? 0 : 1), isEnabled: async () => now().button === 'enabled' }
  return { page, pressed }
}

test('a confirmation is judged on the product answer, however slow', async () => {
  const REFUSAL = 'One or more fields cannot be confirmed.'
  // The refusal arrives three polls after the press, while the button is still disabled.
  const slow = confirmationPage([{ button: 'disabled' }, { button: 'disabled' }, { button: 'disabled' }, { button: 'enabled', error: REFUSAL }])
  assert.equal(await confirmationOutcome(slow.page, slow.pressed, { timeoutMs: 60000 }), REFUSAL)
  const accepted = confirmationPage([{ button: 'disabled' }, { button: 'gone' }])
  assert.equal(await confirmationOutcome(accepted.page, accepted.pressed, { timeoutMs: 60000 }), null)
  const enabledAgain = confirmationPage([{ button: 'disabled' }, { button: 'enabled' }])
  assert.equal(await confirmationOutcome(enabledAgain.page, enabledAgain.pressed, { timeoutMs: 60000 }), null)
})

// A double of the payout and contact panel (customer/src/components/PayoutContactPanel.jsx):
// while the saved accounts load it shows the loading status, lists no account and keeps
// "Continue to agreement" disabled; the button enables once an account and a contact method are
// selected. Each wait of the runner advances the load by one step, and real time passes so the
// step's clock limits apply.
function payoutPanel({ loadingSteps = 0, error = null, bankForm = false, accounts = [{ checked: false, disabled: false }], neverEnables = false, gone = false, remountAfterWaits = null } = {}) {
  const state = { loadingSteps, contact: null, clicks: 0, waits: 0, accounts: accounts.map((account) => ({ ...account })) }
  const loaded = () => state.loadingSteps === 0
  const page = {
    waitForTimeout: async (ms) => {
      state.waits += 1
      if (state.loadingSteps > 0) state.loadingSteps -= 1
      if (state.waits === remountAfterWaits) { state.contact = null; state.accounts.forEach((account) => { account.checked = false }) }
      await new Promise((resolve) => setTimeout(resolve, ms))
    },
    locator: (selector, options = {}) => {
      if (selector === '.payout-contact-panel') {
        return {
          locator: (inner, innerOptions = {}) => {
            if (inner === '.payout-contact-status' && /Loading saved payout accounts/.test(innerOptions.hasText)) return { isVisible: async () => !loaded() }
            if (inner === '.backend-status[role=alert]') return { first: () => ({ textContent: async () => { if (loaded() && state.error) return state.error; throw new Error('no alert') } }) }
            return assert.fail(`unexpected panel locator ${inner}`)
          },
        }
      }
      if (selector === '#payout-bank-name') return { isVisible: async () => loaded() && bankForm }
      if (selector === 'input[name=contact_preference]') return { evaluateAll: async (fn) => fn(loaded() ? ['in_app', 'email'].map((value) => ({ value, disabled: false, checked: state.contact === value })) : []) }
      if (selector.startsWith('input[name=contact_preference][value=')) return { check: async () => { state.contact = selector.match(/value="([^"]+)"/)[1] } }
      if (selector === 'input[name=payout_destination]') {
        return {
          evaluateAll: async (fn) => fn(loaded() ? state.accounts : []),
          nth: (index) => ({ check: async () => { state.accounts[index].checked = true } }),
        }
      }
      return assert.fail(`unexpected locator ${selector} ${JSON.stringify(options)}`)
    },
  }
  state.error = error
  const button = {
    count: async () => (gone ? 0 : 1),
    isEnabled: async () => !neverEnables && loaded() && Boolean(state.contact) && state.accounts.some((account) => account.checked),
    click: async () => { state.clicks += 1 },
  }
  return { page, button, state }
}

const PAYOUT_LIMITS = { settleMs: 200, enableMs: 200, pollMs: 5 }

test('the payout step waits for the saved accounts to load before choosing and continuing', async () => {
  const facts = { 'claimant.contact_preference': 'email' }
  // Loading to ready: the saved account appears unselected after three waits, as in CTL-C-013.
  const slow = payoutPanel({ loadingSteps: 3 })
  const record = { retries: 0 }
  assert.deepEqual(await payoutStep(slow.page, slow.button, facts, record, PAYOUT_LIMITS), { done: 'continued' })
  assert.equal(slow.state.clicks, 1)
  assert.equal(record.payout_loading_waits, 3)
  assert.equal(record.payout_reselected, 1)
  assert.equal(record.contact_preference, 'email')
  // An account already selected is left as it is.
  const preselected = payoutPanel({ accounts: [{ checked: true, disabled: false }] })
  const kept = { retries: 0 }
  assert.deepEqual(await payoutStep(preselected.page, preselected.button, facts, kept, PAYOUT_LIMITS), { done: 'continued' })
  assert.equal(kept.payout_reselected, undefined)
  // No saved account, also after a failed load: the new-account form, which has its own rule.
  const empty = payoutPanel({ bankForm: true, accounts: [], error: 'We could not load your saved payout accounts.' })
  assert.deepEqual(await payoutStep(empty.page, empty.button, facts, { retries: 0 }, PAYOUT_LIMITS), { done: 'form' })
  assert.equal(empty.state.clicks, 0)
  // The panel replaced, or "Saving…" shown instead of the button: the main loop reads again.
  const gone = payoutPanel({ gone: true })
  assert.deepEqual(await payoutStep(gone.page, gone.button, facts, { retries: 0 }, PAYOUT_LIMITS), { done: 'gone' })
})

test('the payout step chooses again after the panel is remounted, and retries a refused save once', async () => {
  const facts = { 'claimant.contact_preference': 'email' }
  // Loading starts again after the first choices and clears them: they are made again.
  const remounted = payoutPanel({ loadingSteps: 0, neverEnables: false, remountAfterWaits: 1 })
  remounted.state.loadingSteps = 0
  const original = remounted.button.isEnabled
  let firstCheck = true
  remounted.button.isEnabled = async () => { if (firstCheck) { firstCheck = false; return false } return original() }
  const record = { retries: 0 }
  assert.deepEqual(await payoutStep(remounted.page, remounted.button, facts, record, PAYOUT_LIMITS), { done: 'continued' })
  assert.equal(record.payout_reselected, 2)
  // An error beside an enabled button: the product refused the last attempt. One retry, then stuck.
  const refused = payoutPanel({ error: 'Your report changed while this page was open.' })
  const retried = { retries: 0, outcome: null, stuck: null }
  assert.deepEqual(await payoutStep(refused.page, refused.button, facts, retried, PAYOUT_LIMITS), { done: 'continued' })
  assert.equal(retried.retries, 1)
  const result = await payoutStep(refused.page, refused.button, facts, retried, PAYOUT_LIMITS)
  assert.equal(result.done, 'stuck')
  assert.match(result.reason, /payout step refused 2 times: Your report changed/)
  assert.equal(refused.state.clicks, 1)
})

test('the payout step stops on an endless load or a button that never enables, by clock time', async () => {
  const facts = {}
  const endless = payoutPanel({ loadingSteps: Infinity })
  const startedEndless = Date.now()
  const stuckLoading = await payoutStep(endless.page, endless.button, facts, { retries: 0 }, PAYOUT_LIMITS)
  assert.equal(stuckLoading.done, 'stuck')
  assert.match(stuckLoading.reason, /still loading/)
  assert.ok(Date.now() - startedEndless >= PAYOUT_LIMITS.settleMs)
  const disabled = payoutPanel({ neverEnables: true })
  const startedDisabled = Date.now()
  const stuckDisabled = await payoutStep(disabled.page, disabled.button, facts, { retries: 0 }, PAYOUT_LIMITS)
  assert.equal(stuckDisabled.done, 'stuck')
  assert.match(stuckDisabled.reason, /stayed disabled .* with the payout account and contact method chosen/)
  assert.ok(Date.now() - startedDisabled >= PAYOUT_LIMITS.enableMs)
  for (const panel of [endless, disabled]) assert.equal(panel.state.clicks, 0)
})

// The same loading-to-ready transition in a real browser, with the panel's markup and timing
// rebuilt as a static page. Runs where Playwright can be loaded (NODE_PATH), as for the runner.
test('in a real browser, the payout step waits through the loading panel and continues', async (t) => {
  let chromium
  try {
    ({ chromium } = require('playwright'))
  } catch {
    t.skip('Playwright is not installed here; set NODE_PATH to a folder with playwright')
    return
  }
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage()
    await page.setContent(`
      <section class="payout-contact-panel">
        <p class="payout-contact-status" role="status">Loading saved payout accounts…</p>
        <fieldset id="accounts"></fieldset>
        <fieldset>
          <label><input type="radio" name="contact_preference" value="in_app"> In-app</label>
          <label><input type="radio" name="contact_preference" value="email"> Email</label>
        </fieldset>
        <button class="primary-button" type="button" disabled>Continue to agreement</button>
      </section>
      <script>
        const button = document.querySelector('button')
        const update = () => {
          button.disabled = !(document.querySelector('input[name=payout_destination]:checked') && document.querySelector('input[name=contact_preference]:checked'))
        }
        document.addEventListener('change', update)
        button.addEventListener('click', () => { document.body.dataset.continued = 'yes' })
        setTimeout(() => {
          document.querySelector('.payout-contact-status').remove()
          document.querySelector('#accounts').innerHTML = '<label><input type="radio" name="payout_destination" value="pd_1"> cheque ****8300</label>'
        }, 1500)
      </script>`)
    const button = page.getByRole('button', { name: 'Continue to agreement' })
    const record = {}
    const result = await payoutStep(page, button, { 'claimant.contact_preference': 'email' }, record, { settleMs: 10000, enableMs: 5000, pollMs: 250 })
    assert.deepEqual(result, { done: 'continued' })
    assert.ok(record.payout_loading_waits > 0, 'the runner saw the panel loading')
    assert.equal(record.payout_reselected, 1)
    assert.equal(await page.evaluate(() => document.body.dataset.continued), 'yes')
  } finally {
    await browser.close()
  }
})

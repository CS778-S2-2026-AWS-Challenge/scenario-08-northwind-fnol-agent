// The runner recognises the same question asked again (#1222). Nothing here opens a browser.
// Run with: node --test tests/corpus/runner/runner.test.cjs
const assert = require('node:assert/strict')
const { test } = require('node:test')

const { questionSentences, trackQuestions, startClaimantSession, signInAnonymousClaim, selectClaimantFile, uploadSpotIndex, recordRefusal, pressOutcome, recordAnswer, claimantPressAnswered, submitClaim, payoutDestinationToSelect, markProcessingFailed, watchTray, mayHandOver, recordFileRetries, payoutStep, payoutAccountForm } = require('./runner.cjs')
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
  // A refused claim submission is its own action: one retry, then stuck at the agreement step.
  const SUBMIT = 'Northwind could not submit your claim.'
  const submitted = { retries: 0, outcome: null, stuck: null }
  assert.equal(recordRefusal(submitted, 'agreement', 'runner', SUBMIT, 't1'), false)
  assert.equal(submitted.retries, 1)
  assert.equal(recordRefusal(submitted, 'agreement', 'runner', SUBMIT, 't2'), true)
  assert.deepEqual(submitted.stuck, { step: 'agreement', reason: `claim submission refused 2 times: ${SUBMIT}` })
})

test('a press with no answer by its deadline ends the pack at its step, without a retry', () => {
  for (const [action, label, step] of [['confirmation', 'All correct', 'confirmation'], ['payout', 'Continue to agreement', 'payout'], ['payout', 'Save payout account', 'payout'], ['agreement', 'Submit claim', 'agreement']]) {
    const record = { retries: 0, outcome: null, stuck: null }
    assert.equal(recordAnswer(record, action, 'runner', label, { timedOut: true, waitedMs: 20000 }), true)
    assert.equal(record.outcome, 'stuck')
    assert.deepEqual(record.stuck, { step, reason: `no answer to "${label}" within 20 s` })
    // The outcome is unknown: it is neither a refusal nor a recovery.
    assert.equal(record.retries, 0)
    assert.equal(record.confirmation_refusals || record.payout_refusals || record.agreement_refusals, undefined)
  }
  // An answer is recorded as before: a refusal counts, an acceptance changes nothing.
  const answered = { retries: 0, outcome: null, stuck: null }
  assert.equal(recordAnswer(answered, 'confirmation', 'claimant', 'Looks right', { alert: null }), false)
  assert.deepEqual(answered, { retries: 0, outcome: null, stuck: null })
  assert.equal(recordAnswer(answered, 'confirmation', 'claimant', 'Looks right', { alert: 'One or more fields cannot be confirmed.' }), false)
  assert.equal(answered.retries, 1)
  assert.equal(answered.confirmation_refusals[0].by, 'claimant')
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
  // The photo fails in this message; a quote failed earlier stays in the tray but was not touched.
  const marked = markProcessingFailed(usable, sentVia, [{ name: 'photo-watch.jpg', label: 'Processing failed' }, { name: 'receipt-watch.pdf', label: 'Ready' }])
  assert.deepEqual(marked.failed, ['photo-watch'])
  assert.deepEqual(marked.sent, ['receipt-watch'])
  assert.deepEqual(marked.paths, [{ material: 'photo-watch', via: 'chat', processing: 'failed', sent: false }, { material: 'receipt-watch', via: 'Still to send: Receipt' }])
  assert.deepEqual(markProcessingFailed(usable, sentVia, [{ name: 'photo-watch.jpg', label: 'Ready' }, { name: 'receipt-watch.pdf', label: 'Ready' }]), { failed: [], sent: ['photo-watch', 'receipt-watch'], paths: sentVia })
  // Tried once more. Through the chat, a new entry is added next to the old failed one; through a
  // requested item's own upload (CTL-M-012), the old entry is reused. Only touched entries count.
  const again = [{ material: { id: 'quote-corrupt', file: 'quote-corrupt.pdf' } }]
  const againVia = [{ material: 'quote-corrupt', via: 'Supporting document' }]
  assert.deepEqual(markProcessingFailed(again, againVia, [{ name: 'quote-corrupt.pdf', label: 'Ready' }]).sent, ['quote-corrupt'], 'a second try that works')
  assert.deepEqual(markProcessingFailed(again, againVia, [{ name: 'quote-corrupt.pdf', label: 'Processing failed' }]).failed, ['quote-corrupt'], 'the reused entry failed again')
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

// The rail's "New chat" button, as the product renders it: present and disabled while a request
// runs (`busy`), absent when `busy` is undefined (no rail on the screen).
const APP_BUSY = '.intake-history .history-actions button[aria-label="New chat"], .intake-history .history-actions button[aria-label="Saving..."]'
const busySignal = (busy) => ({ first: () => ({ count: async () => (busy() === undefined ? 0 : 1), isEnabled: async () => !busy() }) })
// An error line: its text, or a read that times out when nothing is shown.
const errorLine = (text) => ({ first: () => ({ innerText: async () => { const value = text(); if (value) return value; throw new Error('no error line') } }) })

// A pressed confirmation button and the composer's error line, as the product renders them:
// the button is disabled while the request runs, then enabled again or gone, and the error (if
// any) appears when the answer arrives. `steps` lists the page state per poll.
function confirmationPage(steps) {
  let poll = 0
  const now = () => steps[Math.min(poll, steps.length - 1)]
  const page = {
    waitForTimeout: async (ms) => { poll += 1; await new Promise((resolve) => setTimeout(resolve, Math.min(ms, 5))) },
    locator: (selector) => {
      if (selector === APP_BUSY) return busySignal(() => now().busy)
      assert.equal(selector, 'form.workspace-composer .backend-status[role=alert]')
      return errorLine(() => now().error)
    },
  }
  const pressed = { count: async () => (now().button === 'gone' ? 0 : 1), isEnabled: async () => now().button === 'enabled' }
  return { page, pressed }
}

test('a confirmation is judged on the product answer, however slow, and no answer is not a success', async () => {
  const REFUSAL = 'One or more fields cannot be confirmed.'
  // The refusal arrives three polls after the press, while the button is still disabled.
  const slow = confirmationPage([{ button: 'disabled' }, { button: 'disabled' }, { button: 'disabled' }, { button: 'enabled', error: REFUSAL }])
  assert.deepEqual(await pressOutcome(slow.page, 'confirmation', slow.pressed, { timeoutMs: 60000 }), { alert: REFUSAL })
  const accepted = confirmationPage([{ button: 'disabled' }, { button: 'gone' }])
  assert.deepEqual(await pressOutcome(accepted.page, 'confirmation', accepted.pressed, { timeoutMs: 60000 }), { alert: null })
  const enabledAgain = confirmationPage([{ button: 'disabled' }, { button: 'enabled' }])
  assert.deepEqual(await pressOutcome(enabledAgain.page, 'confirmation', enabledAgain.pressed, { timeoutMs: 60000 }), { alert: null })
  // The request never finishes: the button stays disabled and no error shows. At the deadline the
  // outcome is unknown, so it is reported as such, not as an accepted confirmation.
  const pending = confirmationPage([{ button: 'disabled' }])
  const started = Date.now()
  assert.deepEqual(await pressOutcome(pending.page, 'confirmation', pending.pressed, { timeoutMs: 60, pollMs: 5 }), { timedOut: true, waitedMs: 60 })
  assert.ok(Date.now() - started >= 60)
  // The card is replaced while the request still runs (a live refresh): the button is gone, but
  // the product is still busy, so the runner waits for the answer.
  const replaced = confirmationPage([{ button: 'gone', busy: true }, { button: 'gone', busy: true }, { button: 'gone', busy: false, error: REFUSAL }])
  assert.deepEqual(await pressOutcome(replaced.page, 'confirmation', replaced.pressed, { timeoutMs: 60000 }), { alert: REFUSAL })
  const stillBusy = confirmationPage([{ button: 'gone', busy: true }])
  assert.deepEqual(await pressOutcome(stillBusy.page, 'confirmation', stillBusy.pressed, { timeoutMs: 60, pollMs: 5 }), { timedOut: true, waitedMs: 60 })
})

// A double of the payout and contact panel (customer/src/components/PayoutContactPanel.jsx):
// while the saved accounts load it shows the loading status, lists no account and keeps
// "Continue to agreement" disabled; the button enables once an account and a contact method are
// selected. Each wait of the runner advances the load by one step, and real time passes so the
// step's clock limits apply.
function payoutPanel({ loadingSteps = 0, error = null, bankForm = false, accounts = [{ checked: false, disabled: false }], neverEnables = false, gone = false, remountAfterWaits = null, refusals = [], neverAnswers = false } = {}) {
  const state = { loadingSteps, contact: null, clicks: 0, waits: 0, saving: false, accounts: accounts.map((account) => ({ ...account })) }
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
            return assert.fail(`unexpected panel locator ${inner}`)
          },
        }
      }
      if (selector === '.payout-contact-panel form.payout-contact-section .backend-status[role=alert]') return errorLine(() => loaded() && state.error)
      if (selector === APP_BUSY) return busySignal(() => undefined)
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
    getByRole: (role, { name }) => ({ count: async () => (name === 'Saving…' && state.saving ? 1 : 0) }),
  }
  state.error = error
  // A press clears the error line; the request then runs for ever, or is answered with the next
  // refusal in `refusals`, or accepted.
  const button = {
    count: async () => (gone ? 0 : 1),
    isEnabled: async () => !neverEnables && !state.saving && loaded() && Boolean(state.contact) && state.accounts.some((account) => account.checked),
    click: async () => {
      state.clicks += 1
      state.error = null
      if (neverAnswers) state.saving = true
      else state.error = refusals[state.clicks - 1] || null
    },
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
  // The product refuses the press and keeps the panel (its own revision check): read right after
  // the press, one retry, then stuck.
  const CONFLICT = 'The Claim changed before payout details could be saved. Reload and try again.'
  const refused = payoutPanel({ refusals: [CONFLICT, CONFLICT] })
  const retried = { retries: 0, outcome: null, stuck: null }
  assert.deepEqual(await payoutStep(refused.page, refused.button, facts, retried, PAYOUT_LIMITS), { done: 'continued' })
  assert.equal(retried.retries, 1)
  assert.deepEqual(retried.payout_refusals.map((refusal) => refusal.alert), [CONFLICT])
  const result = await payoutStep(refused.page, refused.button, facts, retried, PAYOUT_LIMITS)
  assert.equal(result.done, 'stuck')
  assert.match(result.reason, /payout step refused 2 times: The Claim changed/)
  assert.equal(refused.state.clicks, 2)
  // An error still shown from an earlier attempt is not this press's answer: the press clears it.
  const stale = payoutPanel({ error: CONFLICT })
  const accepted = { retries: 0, outcome: null, stuck: null }
  assert.deepEqual(await payoutStep(stale.page, stale.button, facts, accepted, PAYOUT_LIMITS), { done: 'continued' })
  assert.equal(accepted.retries, 0)
  assert.equal(accepted.payout_refusals, undefined)
})

test('a payout press that is never answered ends the pack at the payout step, by clock time', async () => {
  // "Saving…" stays on: the outcome is unknown. The step stops there and presses nothing more.
  const pending = payoutPanel({ neverAnswers: true })
  const record = { retries: 0, outcome: null, stuck: null }
  const started = Date.now()
  const result = await payoutStep(pending.page, pending.button, { 'claimant.contact_preference': 'email' }, record, { ...PAYOUT_LIMITS, answerMs: 1000 })
  assert.deepEqual(result, { done: 'stuck', reason: 'no answer to "Continue to agreement" within 1 s' })
  assert.deepEqual(record.stuck, { step: 'payout', reason: result.reason })
  assert.ok(Date.now() - started >= 1000)
  assert.equal(pending.state.clicks, 1)
  assert.equal(record.retries, 0)
  assert.equal(record.payout_refusals, undefined)
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
test('in a real browser, the payout step waits through the loading panel and for the answer to its press', async (t) => {
  let chromium
  try {
    ({ chromium } = require('playwright'))
  } catch {
    t.skip('Playwright is not installed here; set NODE_PATH to a folder with playwright')
    return
  }
  const browser = await chromium.launch()
  // The panel as the product renders it; a press shows "Saving…" until the answer, which here
  // replaces the panel after `answerAfterMs`, or never comes.
  const openPanel = async (answerAfterMs) => {
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
        button.addEventListener('click', () => {
          button.textContent = 'Saving…'
          button.disabled = true
          if (${answerAfterMs} >= 0) setTimeout(() => { document.querySelector('.payout-contact-panel').remove(); document.body.dataset.continued = 'yes' }, ${answerAfterMs})
        })
        setTimeout(() => {
          document.querySelector('.payout-contact-status').remove()
          document.querySelector('#accounts').innerHTML = '<label><input type="radio" name="payout_destination" value="pd_1"> cheque ****8300</label>'
        }, 1500)
      </script>`)
    return page
  }
  try {
    const page = await openPanel(800)
    const record = { retries: 0 }
    const result = await payoutStep(page, page.getByRole('button', { name: 'Continue to agreement' }), { 'claimant.contact_preference': 'email' }, record, { settleMs: 10000, enableMs: 5000, answerMs: 5000, pollMs: 250 })
    assert.deepEqual(result, { done: 'continued' })
    assert.ok(record.payout_loading_waits > 0, 'the runner saw the panel loading')
    assert.equal(record.payout_reselected, 1)
    assert.equal(await page.evaluate(() => document.body.dataset.continued), 'yes', 'the step returned only after the product answered')
    // "Saving…" never ends: stuck at the payout step once `answerMs` has passed.
    const pending = await openPanel(-1)
    const stuck = { retries: 0 }
    const started = Date.now()
    const stopped = await payoutStep(pending, pending.getByRole('button', { name: 'Continue to agreement' }), { 'claimant.contact_preference': 'email' }, stuck, { settleMs: 10000, enableMs: 5000, answerMs: 2000, pollMs: 250 })
    assert.deepEqual(stopped, { done: 'stuck', reason: 'no answer to "Continue to agreement" within 2 s' })
    assert.ok(Date.now() - started >= 2000)
    assert.equal(stuck.retries, 0)
  } finally {
    await browser.close()
  }
})

// A page whose request shows `busyLabel` on its button while it runs, and an error on one of
// `lines` when the product refuses. `steps` lists, per poll, whether the button shows it running,
// whether the product is busy, and the text on each error line (`errors`, by selector).
function requestPage(busyLabel, lines, steps) {
  let poll = 0
  const now = () => steps[Math.min(poll, steps.length - 1)]
  return {
    waitForTimeout: async (ms) => { poll += 1; await new Promise((resolve) => setTimeout(resolve, Math.min(ms, 5))) },
    getByRole: (role, { name }) => ({ count: async () => (name === busyLabel && now().running ? 1 : 0) }),
    locator: (selector) => {
      if (selector === APP_BUSY) return busySignal(() => now().busy)
      assert.ok(lines.includes(selector), `unexpected locator ${selector}`)
      return errorLine(() => (now().errors || {})[selector])
    },
  }
}
const PAYOUT_LINE = '.payout-contact-panel form.payout-contact-section .backend-status[role=alert]'
const SUBMISSION_CARD = '.agreement-submission-error[role=alert]'
const COMPOSER_LINE = 'form.workspace-composer .backend-status[role=alert]'

test('a payout save is judged after "Saving…" ends, from the form\'s own error line, and never by a timeout', async () => {
  // A failed load's error is elsewhere in the panel and never read here.
  const savePage = (steps) => requestPage('Saving…', [PAYOUT_LINE], steps)
  const REFUSED = 'Payout and contact details could not be saved.'
  // A slow save refused with the same text as before: it is read once "Saving…" is gone.
  assert.deepEqual(await pressOutcome(savePage([{ running: true }, { running: true }, { running: true }, { running: false, errors: { [PAYOUT_LINE]: REFUSED } }]), 'payout', null, { timeoutMs: 60000 }), { alert: REFUSED })
  assert.deepEqual(await pressOutcome(savePage([{ running: true }, { running: false }]), 'payout'), { alert: null })
  // "Saving…" never ends: the outcome is unknown at the deadline.
  assert.deepEqual(await pressOutcome(savePage([{ running: true }]), 'payout', null, { timeoutMs: 60, pollMs: 5 }), { timedOut: true, waitedMs: 60 })
})

// The new-account form (customer/src/components/PayoutContactPanel.jsx): "Save payout account"
// shows "Saving…" while the save runs; a refusal leaves the form with the error on the contact
// form's line, an accepted save replaces the form. `answers` lists each save's answer: 'saved',
// an error text, or 'never'.
function accountForm(answers) {
  const state = { saves: 0, saving: false, error: null, form: true, filled: [] }
  const page = {
    waitForTimeout: async (ms) => { await new Promise((resolve) => setTimeout(resolve, Math.min(ms, 5))) },
    fill: async (selector) => { state.filled.push(selector) },
    getByRole: (role, { name }) => {
      if (name === 'Save payout account') {
        return {
          click: async () => {
            const answer = answers[state.saves]
            state.saves += 1
            state.error = null
            if (answer === 'never') state.saving = true
            else if (answer === 'saved') state.form = false
            else state.error = answer
          },
        }
      }
      return { count: async () => (name === 'Saving…' && state.saving ? 1 : 0) }
    },
    locator: (selector) => {
      if (selector === '#payout-bank-name') return { isVisible: async () => state.form }
      if (selector === '.payout-contact-panel .payout-contact-status') return { isVisible: async () => false }
      if (selector === PAYOUT_LINE) return errorLine(() => state.error)
      if (selector === APP_BUSY) return busySignal(() => undefined)
      return assert.fail(`unexpected locator ${selector}`)
    },
  }
  return { page, state }
}

const FORM_LIMITS = { settleMs: 1, answerMs: 1000, pollMs: 5 }

test('a new payout account save waits for its answer: accepted, refused once then stuck, or never answered', async () => {
  const facts = { 'policyholder.name': 'Corpus Claimant' }
  const accepted = accountForm(['saved'])
  const record = { retries: 0, outcome: null, stuck: null }
  assert.equal(await payoutAccountForm(accepted.page, facts, record, FORM_LIMITS), false)
  assert.deepEqual(record, { retries: 0, outcome: null, stuck: null, payout_account_saves: 1 })
  // Refused twice, with the same text: one retry, then stuck at the payout step.
  const REFUSED = 'The payout account could not be saved.'
  const refused = accountForm([REFUSED, REFUSED])
  const retried = { retries: 0, outcome: null, stuck: null }
  assert.equal(await payoutAccountForm(refused.page, facts, retried, FORM_LIMITS), false)
  assert.equal(retried.retries, 1)
  assert.equal(await payoutAccountForm(refused.page, facts, retried, FORM_LIMITS), true)
  assert.deepEqual(retried.stuck, { step: 'payout', reason: `payout step refused 2 times: ${REFUSED}` })
  // "Saving…" never ends: stuck at the payout step at the deadline, with nothing more pressed.
  const pending = accountForm(['never'])
  const stuck = { retries: 0, outcome: null, stuck: null }
  const started = Date.now()
  assert.equal(await payoutAccountForm(pending.page, facts, stuck, FORM_LIMITS), true)
  assert.ok(Date.now() - started >= FORM_LIMITS.answerMs)
  assert.equal(stuck.outcome, 'stuck')
  assert.deepEqual(stuck.stuck, { step: 'payout', reason: 'no answer to "Save payout account" within 1 s' })
  assert.equal(stuck.retries, 0)
  assert.equal(pending.state.saves, 1)
})

test('a claim submission is judged after "Submitting…" ends, from the submission error, and never by a timeout', async () => {
  const submitPage = (steps) => requestPage('Submitting…', [SUBMISSION_CARD, COMPOSER_LINE], steps)
  // The card's heading and message (customer/src/claimSubmissionFeedback.js), read as one line.
  const CARD = "Your claim wasn't accepted\nThe Claim changed before it could be submitted. Please check your details and try again."
  const READ = "Your claim wasn't accepted The Claim changed before it could be submitted. Please check your details and try again."
  assert.deepEqual(await pressOutcome(submitPage([{ running: true }, { running: true }, { running: false }]), 'agreement'), { alert: null })
  assert.deepEqual(await pressOutcome(submitPage([{ running: true }, { running: false, errors: { [SUBMISSION_CARD]: CARD } }]), 'agreement'), { alert: READ })
  // The read-back moved the claim on and the panel, with its card, is gone: the composer's line
  // still carries the error, so the refusal is not taken for an acceptance.
  const COMPOSER = "We're not sure your claim went through. Try again — it won't create a duplicate."
  assert.deepEqual(await pressOutcome(submitPage([{ running: true, busy: true }, { running: false, busy: true }, { running: false, busy: false, errors: { [COMPOSER_LINE]: COMPOSER } }]), 'agreement', null, { timeoutMs: 60000 }), { alert: COMPOSER })
  assert.deepEqual(await pressOutcome(submitPage([{ running: true }]), 'agreement', null, { timeoutMs: 60, pollMs: 5 }), { timedOut: true, waitedMs: 60 })
})

// The agreement panel (customer/src/components/AgreementConfirmationPanel.jsx): its confirmation
// boxes, and a submit button that shows "Submitting…" until the answer. `answers` lists each
// submission's answer: 'lodged', an error text for the card, or 'never'.
function agreementPanel(answers) {
  const state = { submissions: 0, running: false, error: null, boxes: [false, false], shots: [] }
  const page = {
    waitForTimeout: async (ms) => { await new Promise((resolve) => setTimeout(resolve, Math.min(ms, 5))) },
    getByRole: (role, { name }) => ({ count: async () => (name === 'Submitting…' && state.running ? 1 : 0) }),
    locator: (selector) => {
      if (selector === '.agreement-confirmation-option input[type=checkbox]') {
        return { all: async () => state.boxes.map((checked, index) => ({ isChecked: async () => state.boxes[index], check: async () => { state.boxes[index] = true } })) }
      }
      if (selector === 'button.agreement-submit') {
        return {
          innerText: async () => (state.submissions && state.error ? 'Retry claim submission' : 'Submit claim'),
          click: async () => {
            assert.ok(state.boxes.every(Boolean), 'every confirmation box is ticked before the press')
            const answer = answers[state.submissions]
            state.submissions += 1
            state.error = null
            if (answer === 'never') state.running = true
            else if (answer !== 'lodged') state.error = answer
          },
        }
      }
      if (selector === SUBMISSION_CARD) return errorLine(() => state.error)
      if (selector === COMPOSER_LINE) return errorLine(() => null)
      if (selector === APP_BUSY) return busySignal(() => state.running)
      return assert.fail(`unexpected locator ${selector}`)
    },
  }
  return { page, state, shot: async (name) => { state.shots.push(name) } }
}

test('the claim submission waits for its answer: lodged, refused once then stuck, or never answered', async () => {
  const LIMITS = { answerMs: 1000, pollMs: 5, settleMs: 1 }
  const lodged = agreementPanel(['lodged'])
  const record = { retries: 0, outcome: null, stuck: null }
  assert.equal(await submitClaim(lodged.page, record, lodged.shot, LIMITS), false)
  assert.deepEqual(record, { retries: 0, outcome: null, stuck: null })
  assert.deepEqual(lodged.state.shots, ['agreement'])
  const REFUSED = "Your claim wasn't accepted"
  const refused = agreementPanel([REFUSED, REFUSED])
  const retried = { retries: 0, outcome: null, stuck: null }
  assert.equal(await submitClaim(refused.page, retried, refused.shot, LIMITS), false)
  assert.equal(retried.retries, 1)
  assert.equal(await submitClaim(refused.page, retried, refused.shot, LIMITS), true)
  assert.deepEqual(retried.stuck, { step: 'agreement', reason: `claim submission refused 2 times: ${REFUSED}` })
  // "Submitting…" never ends: stuck at the agreement step, nothing pressed again.
  const pending = agreementPanel(['never'])
  const stuck = { retries: 0, outcome: null, stuck: null }
  const started = Date.now()
  assert.equal(await submitClaim(pending.page, stuck, pending.shot, LIMITS), true)
  assert.ok(Date.now() - started >= LIMITS.answerMs)
  assert.deepEqual(stuck.stuck, { step: 'agreement', reason: 'no answer to "Submit claim" within 1 s' })
  assert.equal(stuck.retries, 0)
  assert.equal(pending.state.submissions, 1)
})

test('a claimant press waits for the request it started: at its step for confirmations and submissions, as a press otherwise', async () => {
  // `steps`: per poll, whether the pressed button is disabled, whether the product is busy, and the
  // composer's error. The pressed button is the one the runner tagged for the claimant.
  const pressPage = (steps) => {
    let poll = 0
    const now = () => steps[Math.min(poll, steps.length - 1)]
    const page = {
      waitForTimeout: async (ms) => { poll += 1; await new Promise((resolve) => setTimeout(resolve, Math.min(ms, 5))) },
      getByRole: (role, { name }) => ({ count: async () => (name === 'Submitting…' && now().running ? 1 : 0) }),
      locator: (selector) => {
        if (selector === APP_BUSY) return busySignal(() => now().busy)
        if (selector === COMPOSER_LINE) return errorLine(() => now().error)
        if (selector === SUBMISSION_CARD) return errorLine(() => null)
        return assert.fail(`unexpected locator ${selector}`)
      },
    }
    const pressed = { count: async () => 1, isEnabled: async () => !now().disabled }
    return { page, pressed }
  }
  const LIMITS = { timeoutMs: 1000, pollMs: 5 }
  // The side panel's "Right" confirms a detail: its refusal counts as a confirmation refusal.
  const REFUSAL = 'One or more fields cannot be confirmed.'
  const right = pressPage([{ disabled: true, busy: true }, { disabled: false, busy: false, error: REFUSAL }])
  const confirmed = { retries: 0, outcome: null, stuck: null }
  assert.equal(await claimantPressAnswered(right.page, confirmed, 'Right', right.pressed, LIMITS), false)
  assert.deepEqual(confirmed.confirmation_refusals.map((refusal) => [refusal.by, refusal.alert]), [['claimant', REFUSAL]])
  // A submission the claimant pressed that is never answered: stuck at the agreement step.
  const submit = pressPage([{ running: true, busy: true }])
  const submitted = { retries: 0, outcome: null, stuck: null }
  assert.equal(await claimantPressAnswered(submit.page, submitted, 'Retry claim submission', submit.pressed, LIMITS), true)
  assert.deepEqual(submitted.stuck, { step: 'agreement', reason: 'no answer to "Retry claim submission" within 1 s' })
  // A service card's request that never ends: stuck at the press, not read as done.
  const service = pressPage([{ disabled: true, busy: true }])
  const agreed = { retries: 0, outcome: null, stuck: null }
  assert.equal(await claimantPressAnswered(service.page, agreed, 'Agree and continue', service.pressed, LIMITS), true)
  assert.deepEqual(agreed.stuck, { step: 'press', reason: 'no answer to "Agree and continue" within 1 s' })
  // A press that starts no request (navigation) is done at once, and its screen is the claimant's
  // to read: an error shown there is not counted by the runner.
  const navigation = pressPage([{ disabled: false, busy: false, error: 'Something the claimant reads.' }])
  const moved = { retries: 0, outcome: null, stuck: null }
  assert.equal(await claimantPressAnswered(navigation.page, moved, 'Review and agree ›', navigation.pressed, LIMITS), false)
  assert.deepEqual(moved, { retries: 0, outcome: null, stuck: null })
})

// The tray in a real browser: an entry left from an earlier message, an entry reused by a file sent
// again through a requested item (its label goes back through "Processing"), and a new entry.
test('in a real browser, only tray entries the uploads add or reuse are judged', async (t) => {
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
      <form class="workspace-composer"><ul id="tray">
        <li><span class="composer-file-copy"><strong>old-photo.jpg</strong><small>Processing failed</small></span></li>
        <li><span class="composer-file-copy" id="quote"><strong>quote-corrupt.pdf</strong><small>Processing failed</small></span></li>
      </ul></form>`)
    const touched = await watchTray(page)
    await page.evaluate(async () => {
      const pause = () => new Promise((resolve) => setTimeout(resolve, 100))
      const label = document.querySelector('#quote small')
      label.textContent = 'Processing'
      await pause()
      label.textContent = 'Processing failed'
      document.querySelector('#tray').insertAdjacentHTML('beforeend', '<li><span class="composer-file-copy"><strong>photo-new.jpg</strong><small>Ready</small></span></li>')
      await pause()
    })
    const entries = await touched()
    assert.deepEqual(entries.map((entry) => `${entry.name}: ${entry.label}`).sort(), ['photo-new.jpg: Ready', 'quote-corrupt.pdf: Processing failed'])
    // An anonymous sign-in replaces the workspace and its composer while the first file uploads.
    await page.setContent('<main id="workspace"><form class="workspace-composer"><ul id="tray"></ul></form></main>')
    const afterSignIn = await watchTray(page)
    await page.evaluate(() => {
      document.querySelector('#workspace').outerHTML = '<main id="login"><form class="login-form"><input></form></main>'
      document.querySelector('#login').outerHTML = '<main id="workspace"><form class="workspace-composer"><ul><li><span class="composer-file-copy"><strong>quote-corrupt.pdf</strong><small>Processing failed</small></span></li></ul></form></main>'
    })
    assert.deepEqual(await afterSignIn(), [{ name: 'quote-corrupt.pdf', label: 'Processing failed' }])
    const usable = [{ material: { id: 'quote-corrupt', file: 'quote-corrupt.pdf' } }, { material: { id: 'photo-new', file: 'photo-new.jpg' } }]
    const result = markProcessingFailed(usable, [{ material: 'quote-corrupt', via: 'Supporting document' }, { material: 'photo-new', via: 'chat' }], entries)
    assert.deepEqual(result.failed, ['quote-corrupt'])
    assert.deepEqual(result.sent, ['photo-new'])
  } finally {
    await browser.close()
  }
})

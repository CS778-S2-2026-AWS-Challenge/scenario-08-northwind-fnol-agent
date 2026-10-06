// The runner recognises the same question asked again (#1222). Nothing here opens a browser.
// Run with: node --test tests/corpus/runner/runner.test.cjs
const assert = require('node:assert/strict')
const { test } = require('node:test')

const { questionSentences, trackQuestions, startClaimantSession, signInAnonymousClaim, selectClaimantFile } = require('./runner.cjs')
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
    return { setInputFiles: async (file) => events.push(`select:${resolutions}:${file}`) }
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
      await assert.rejects(selectClaimantFile(page, 'photo.jpg', async () => ({ setInputFiles: async () => { selections += 1 } }), () => signInAnonymousClaim(page, seedAccount('CTL-M-001', {}), 'clm_abc123')))
      assert.equal(selections, 1, 'no file is selected again when the product did not complete promotion')
      assert.ok(!events.some((event) => /\/promote|\/messages|POST:\/api\/v1\/claims/.test(event)))
      if (boundary === 'missing_gate') assert.ok(!events.some((event) => event === 'journey:login'))
    })
  }
})

test('authenticated file selection does not trigger another sign-in', async () => {
  const selected = []
  await selectClaimantFile({ getByText: () => assert.fail('no anonymous gate') }, 'quote.pdf', async () => ({ setInputFiles: async (file) => selected.push(file) }), null)
  assert.deepEqual(selected, ['quote.pdf'])
})

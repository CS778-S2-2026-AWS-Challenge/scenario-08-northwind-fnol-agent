const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const CUSTOMER = process.env.NORTHWIND_CUSTOMER_URL || 'http://127.0.0.1:8001'
const WORKBENCH = process.env.NORTHWIND_WORKBENCH_URL || 'http://127.0.0.1:8002'
const HEAD = process.env.PR_HEAD_SHA || 'unknown'
const ARTIFACT_DIR = path.resolve(process.env.BROWSER_EVIDENCE_DIR || 'browser-evidence')
fs.mkdirSync(ARTIFACT_DIR, { recursive: true })

const STAFF_EMAIL = 'staff.one@example.invalid'
const STAFF_PASSWORD = 'northwind-demo-staff'
const STAFF_MESSAGE = 'We have accepted your assistance request and are continuing the review.'
const RESOLUTION_INTERNAL = 'Staff support completed after reviewing the claimant context.'
const RESOLUTION_CLAIMANT = 'Your staff handoff is resolved and your claim can continue.'

const result = {
  head: HEAD,
  browser: 'Playwright Chromium',
  contexts: {
    claimant: 'independent browser context',
    workbench: 'independent browser context',
  },
  claim_id: null,
  session_id: null,
  display_reference: null,
  claimant_request_counts: {
    create_claim: 0,
    create_session: 0,
    support_request: 0,
  },
  recovery_events: [],
  recovery_business_posts: [],
  checks: {},
}

function pathOf(url) {
  return new URL(url).pathname
}

function classifyRecoveryPath(pathname) {
  if (pathname === '/api/v1/realtime/events') return 'replacement_realtime'
  if (result.claim_id && pathname === `/api/v1/claims/${result.claim_id}`) {
    return 'authoritative_claim'
  }
  if (
    result.claim_id
    && result.session_id
    && pathname === `/api/v1/claims/${result.claim_id}/sessions/${result.session_id}/messages`
  ) {
    return 'authoritative_messages'
  }
  return null
}

function firstEvent(phase, type) {
  return result.recovery_events.find((event) => event.phase === phase && event.type === type)
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function screenshot(page, name) {
  await page.screenshot({
    path: path.join(ARTIFACT_DIR, `${name}.png`),
    fullPage: true,
  })
}

async function maybeCloseCapabilities(page) {
  const close = page.getByRole('button', { name: 'Close third-party services' })
  try {
    await close.waitFor({ state: 'visible', timeout: 5000 })
    await close.click()
    await close.waitFor({ state: 'hidden', timeout: 10000 })
  } catch {
    // The dialog is optional; continue when it was never opened.
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true })
  const claimantContext = await browser.newContext()
  const staffContext = await browser.newContext()
  const claimant = await claimantContext.newPage()
  const staff = await staffContext.newPage()

  let recoveryActive = false
  let sequence = 0

  claimant.on('request', (request) => {
    const method = request.method()
    const pathname = pathOf(request.url())

    if (method === 'POST' && pathname === '/api/v1/claims') {
      result.claimant_request_counts.create_claim += 1
    } else if (method === 'POST' && /^\/api\/v1\/claims\/[^/]+\/sessions$/.test(pathname)) {
      result.claimant_request_counts.create_session += 1
    } else if (
      method === 'POST'
      && /^\/api\/v1\/claims\/[^/]+\/support-requests$/.test(pathname)
    ) {
      result.claimant_request_counts.support_request += 1
    }

    if (!recoveryActive) return

    if (method === 'POST' && pathname.startsWith('/api/v1/claims/')) {
      result.recovery_business_posts.push({ method, path: pathname })
    }

    const type = classifyRecoveryPath(pathname)
    if (method === 'GET' && type) {
      result.recovery_events.push({
        sequence: ++sequence,
        phase: 'request',
        type,
        path: pathname,
      })
    }
  })

  claimant.on('response', (response) => {
    if (!recoveryActive) return
    const request = response.request()
    const pathname = pathOf(response.url())
    const type = classifyRecoveryPath(pathname)
    if (request.method() === 'GET' && type) {
      result.recovery_events.push({
        sequence: ++sequence,
        phase: 'response',
        type,
        path: pathname,
        status: response.status(),
      })
    }
  })

  try {
    console.log('[1/8] Open claimant in its own browser context')
    await claimant.goto(CUSTOMER, { waitUntil: 'domcontentloaded' })
    const incident = claimant.getByLabel('Incident description')
    await incident.waitFor({ state: 'visible', timeout: 30000 })

    console.log('[2/8] Create one Claim and request staff assistance')
    await incident.fill(
      'A pipe burst in the kitchen. Nobody is injured and there is no continuing danger.',
    )
    const createResponsePromise = claimant.waitForResponse(
      (response) => (
        response.request().method() === 'POST'
        && pathOf(response.url()) === '/api/v1/claims'
        && response.status() === 201
      ),
      { timeout: 60000 },
    )
    await claimant.getByRole('button', { name: 'Start claim', exact: true }).click()
    const createResponse = await createResponsePromise
    const created = await createResponse.json()
    const claim = created.claim || {}
    const session = created.session || {}

    result.claim_id = claim.claim_id || null
    result.session_id = session.session_id || null
    result.display_reference = claim.display_reference || null

    assert(result.claim_id, 'Claim creation did not return claim_id.')
    assert(result.session_id, 'Claim creation did not return session_id.')

    const support = claimant.getByRole('button', { name: 'Staff assistance', exact: true })
    await support.waitFor({ state: 'visible', timeout: 60000 })
    await maybeCloseCapabilities(claimant)

    const supportResponsePromise = claimant.waitForResponse(
      (response) => (
        response.request().method() === 'POST'
        && pathOf(response.url()) === `/api/v1/claims/${result.claim_id}/support-requests`
        && response.status() >= 200
        && response.status() < 300
      ),
      { timeout: 30000 },
    )
    await support.click()
    await supportResponsePromise

    await claimant.getByText('Waiting for staff', { exact: true }).first()
      .waitFor({ state: 'visible', timeout: 30000 })
    await screenshot(claimant, '01-claimant-waiting-for-staff')

    console.log(`[2/8] Claim=${result.claim_id} Session=${result.session_id}`)

    console.log('[3/8] Interrupt claimant transport without refreshing the page')
    await claimantContext.setOffline(true)

    console.log('[4/8] Open Workbench in an independent browser context')
    await staff.goto(`${WORKBENCH}/workbench/`, { waitUntil: 'domcontentloaded' })
    await staff.waitForURL(
      (url) => url.pathname === '/workbench/login',
      { timeout: 30000 },
    )
    await staff.getByLabel('Work email').fill(STAFF_EMAIL)
    await staff.getByLabel('Password').fill(STAFF_PASSWORD)
    await staff.getByRole('button', { name: 'Sign in', exact: true }).click()
    await staff.waitForURL(
      (url) => !url.pathname.includes('/workbench/login'),
      { timeout: 30000 },
    )

    const conversationsLink = staff.getByRole('link', { name: 'Claim conversations', exact: true })
    await conversationsLink.waitFor({ state: 'visible', timeout: 30000 })
    await conversationsLink.click()
    await staff.getByRole('tab', { name: /Action needed, \d+ conversations/ })
      .waitFor({ state: 'visible', timeout: 30000 })

    const cardLabel = result.display_reference || result.claim_id
    const card = staff.locator('article.conversation-queue-row').filter({ hasText: cardLabel })
    await card.waitFor({ state: 'visible', timeout: 30000 })
    await screenshot(staff, '02-workbench-queued-same-claim')

    await card.getByRole('button', { name: 'Take over', exact: true }).click()
    const confirm = card.getByRole('button', { name: 'Confirm take over', exact: true })
    await confirm.waitFor({ state: 'visible', timeout: 10000 })
    await confirm.click()

    await staff.waitForURL(
      (url) => (
        url.pathname === `/workbench/conversations/${result.session_id}`
      ),
      { timeout: 30000 },
    )

    console.log('[5/8] Message claimant while claimant remains offline')
    const composer = staff.getByLabel('Message to claimant')
    await composer.waitFor({ state: 'visible', timeout: 30000 })
    await composer.fill(STAFF_MESSAGE)
    await staff.getByRole('button', { name: 'Send message', exact: true }).click()
    await staff.getByText(STAFF_MESSAGE, { exact: true }).first()
      .waitFor({ state: 'visible', timeout: 30000 })
    await screenshot(staff, '03-workbench-accepted-and-message-sent')

    const warning = claimant.getByText(
      /Live updates (?:are reconnecting|need to be resynchronised)\. Some claim information may be out of date/i,
    ).first()
    await warning.waitFor({ state: 'visible', timeout: 45000 })
    result.reconnect_notice = (await warning.textContent())?.trim() || null
    await screenshot(claimant, '04-claimant-reconnecting-stale')

    console.log('[6/8] Restore claimant transport and prove replacement-stream/readback recovery')
    recoveryActive = true
    await claimantContext.setOffline(false)

    await claimant.getByText(STAFF_MESSAGE, { exact: true }).first()
      .waitFor({ state: 'visible', timeout: 45000 })
    await warning.waitFor({ state: 'hidden', timeout: 45000 })

    const realtimeRequest = firstEvent('request', 'replacement_realtime')
    const claimRequest = firstEvent('request', 'authoritative_claim')
    const messagesRequest = firstEvent('request', 'authoritative_messages')
    const realtimeResponse = firstEvent('response', 'replacement_realtime')
    const claimResponse = firstEvent('response', 'authoritative_claim')
    const messagesResponse = firstEvent('response', 'authoritative_messages')

    assert(
      realtimeRequest && claimRequest && messagesRequest
      && realtimeResponse && claimResponse && messagesResponse,
      `Recovery traffic was incomplete: ${JSON.stringify(result.recovery_events)}`,
    )
    assert(
      realtimeRequest.sequence < claimRequest.sequence
      && realtimeRequest.sequence < messagesRequest.sequence,
      `Recovery reads started before replacement realtime: ${JSON.stringify(result.recovery_events)}`,
    )
    assert(realtimeResponse.status === 200, 'Replacement realtime subscription did not return 200.')
    assert(claimResponse.status === 200, 'Authoritative Claim read did not return 200.')
    assert(messagesResponse.status === 200, 'Authoritative messages read did not return 200.')

    assert(
      result.claimant_request_counts.create_claim === 1,
      `Expected one Claim creation, observed ${result.claimant_request_counts.create_claim}.`,
    )
    assert(
      result.claimant_request_counts.create_session === 0,
      `Unexpected separate session creation: ${result.claimant_request_counts.create_session}.`,
    )
    assert(
      result.claimant_request_counts.support_request === 1,
      `Expected one support request, observed ${result.claimant_request_counts.support_request}.`,
    )
    assert(
      result.recovery_business_posts.length === 0,
      `Recovery replayed business POSTs: ${JSON.stringify(result.recovery_business_posts)}`,
    )

    result.checks = {
      two_independent_browser_contexts: true,
      same_claim_progressed_by_workbench_while_claimant_offline: true,
      reconnecting_or_stale_visible_without_refresh: true,
      replacement_realtime_requested_before_authoritative_claim_read: true,
      replacement_realtime_requested_before_authoritative_message_read: true,
      authoritative_claim_read_succeeded: true,
      authoritative_current_session_messages_read_succeeded: true,
      staff_message_visible_after_recovery: true,
      degraded_notice_cleared_after_recovery: true,
      exactly_one_claim_created: true,
      no_second_session_created: true,
      exactly_one_support_request: true,
      no_claimant_business_post_replayed_during_recovery: true,
    }
    recoveryActive = false
    await screenshot(claimant, '05-claimant-recovered-same-claim')

    console.log('[7/8] Resolve the same handoff and verify claimant completion')
    const complete = staff.getByRole('button', { name: 'Complete assistance', exact: true })
    await complete.waitFor({ state: 'visible', timeout: 30000 })
    await complete.click()
    await staff.getByLabel('Internal result summary').fill(RESOLUTION_INTERNAL)
    await staff.getByLabel('Claimant update').fill(RESOLUTION_CLAIMANT)
    await staff.getByRole('button', { name: 'Confirm completion', exact: true }).click()

    await claimant.getByRole('status', { name: /Staff assistance completed/i }).first()
      .waitFor({ state: 'visible', timeout: 45000 })
    result.checks.same_claim_receives_resolved_handoff = true
    await screenshot(staff, '06-workbench-resolved')
    await screenshot(claimant, '07-claimant-resolved-same-claim')

    console.log('[8/8] Browser evidence passed')
    result.status = 'PASS'
    fs.writeFileSync(
      path.join(ARTIFACT_DIR, 'pr981-browser-evidence-PASS.json'),
      JSON.stringify(result, null, 2),
      'utf8',
    )

    console.log('PR981_BROWSER_EVIDENCE_OK')
    console.log(`HEAD=${HEAD}`)
    console.log(`CLAIM_ID=${result.claim_id}`)
    console.log(`SESSION_ID=${result.session_id}`)
    console.log(`RECOVERY=${JSON.stringify(result.recovery_events)}`)
  } catch (error) {
    result.status = 'FAIL'
    result.error = error?.stack || String(error)
    for (const [page, name] of [[claimant, 'FAIL-claimant'], [staff, 'FAIL-workbench']]) {
      try {
        await screenshot(page, name)
      } catch {
        // Preserve the primary failure.
      }
    }
    fs.writeFileSync(
      path.join(ARTIFACT_DIR, 'pr981-browser-evidence-FAIL.json'),
      JSON.stringify(result, null, 2),
      'utf8',
    )
    throw error
  } finally {
    try {
      await claimantContext.setOffline(false)
    } catch {
      // Best-effort cleanup.
    }
    await browser.close()
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})

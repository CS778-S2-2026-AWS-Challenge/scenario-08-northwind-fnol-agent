const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')
const { STAFF_EMAIL, STAFF_PASSWORD } = require('./p12_3_claimant_workbench_recovery.cjs')

const WORKBENCH = process.env.NORTHWIND_WORKBENCH_URL || 'http://127.0.0.1:8002'
const HEAD = process.env.PR_HEAD_SHA || 'unknown'
const ARTIFACT_DIR = path.resolve(process.env.BROWSER_EVIDENCE_DIR || 'browser-evidence')
fs.mkdirSync(ARTIFACT_DIR, { recursive: true })

const AT02 = 'clm_fixture_at02'
const AT10 = 'clm_fixture_at10'

const DIAGNOSTIC_STATUS_CONTEXT = 'ci/pr1170-browser-detail'
let currentStep = 'startup'

async function reportGitHubStatus(state, description) {
  const token = process.env.GITHUB_TOKEN
  const owner = process.env.CIRCLE_PROJECT_USERNAME
  const repo = process.env.CIRCLE_PROJECT_REPONAME
  if (!token || !owner || !repo || HEAD === 'unknown') return
  const payload = {
    state,
    context: DIAGNOSTIC_STATUS_CONTEXT,
    description: String(description).replace(/\\s+/g, ' ').slice(0, 140),
  }
  if (process.env.CIRCLE_BUILD_URL) payload.target_url = process.env.CIRCLE_BUILD_URL
  try {
    await fetch(`https://api.github.com/repos/${owner}/${repo}/statuses/${HEAD}`, {
      method: 'POST',
      headers: {
        Accept: 'application/vnd.github+json',
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        'X-GitHub-Api-Version': '2022-11-28',
      },
      body: JSON.stringify(payload),
    })
  } catch {
    // Diagnostic reporting must never replace the browser result.
  }
}

const result = {
  head: HEAD,
  browser: 'Playwright Chromium',
  environment: {
    desktop: '1440x900',
    phone: '390x844',
    data_runtime: process.env.DATA_RUNTIME_PROFILE || 'unknown',
    agent_runtime: process.env.AGENT_RUNTIME_PROFILE || 'unknown',
    identity_mode: process.env.NORTHWIND_IDENTITY_MODE || 'unknown',
  },
  checks: {},
  surfaces: {},
  mutations: {},
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

function pathOf(url) {
  return new URL(url).pathname
}

async function screenshot(page, name) {
  await page.screenshot({
    path: path.join(ARTIFACT_DIR, `pr1170-${name}.png`),
    fullPage: true,
  })
}

async function api(page, apiPath, { method = 'GET', body } = {}) {
  return page.evaluate(async ({ apiPath, method, body }) => {
    const session = JSON.parse(localStorage.getItem('northwind.workbench.session') || 'null')
    if (!session?.access_token) throw new Error('Workbench session token is unavailable.')
    const response = await fetch(apiPath, {
      method,
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${session.access_token}`,
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
    let payload = null
    try {
      payload = await response.json()
    } catch {
      payload = null
    }
    return { status: response.status, payload }
  }, { apiPath, method, body })
}

async function captureSurface(page, name) {
  const controls = await page.locator(
    'button:visible, a[href]:visible, input:visible, select:visible, textarea:visible, [role="tab"]:visible, [role="menuitem"]:visible',
  ).evaluateAll((nodes) => nodes.map((node) => {
    const labelledBy = node.getAttribute('aria-labelledby')
    const labelledByText = labelledBy
      ? labelledBy.split(/\s+/).map((id) => document.getElementById(id)?.textContent || '').join(' ')
      : ''
    const labelText = node.labels?.length
      ? Array.from(node.labels).map((label) => label.textContent || '').join(' ')
      : ''
    const name = (
      node.getAttribute('aria-label')
      || labelledByText
      || labelText
      || node.textContent
      || node.getAttribute('title')
      || node.getAttribute('placeholder')
      || ''
    ).replace(/\s+/g, ' ').trim()
    return {
      tag: node.tagName.toLowerCase(),
      role: node.getAttribute('role'),
      type: node.getAttribute('type'),
      name,
      disabled: Boolean(node.disabled) || node.getAttribute('aria-disabled') === 'true',
      expanded: node.getAttribute('aria-expanded'),
    }
  }))
  result.surfaces[name] = controls
  const unnamedActions = controls.filter((item) => ['button', 'a'].includes(item.tag) && !item.name)
  assert(unnamedActions.length === 0, `${name} contains unnamed visible buttons/links.`)
  return controls
}

async function waitForNodeCondition(check, message, timeoutMs = 15000) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    if (check()) return
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error(message)
}

async function main() {
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()

  const presencePatches = []
  const agentSessionPosts = []
  page.on('request', (request) => {
    const pathname = pathOf(request.url())
    if (request.method() === 'PATCH' && pathname === '/api/v1/workbench/staff/presence') {
      presencePatches.push({ path: pathname, body: request.postData() || null })
    }
    if (
      request.method() === 'POST'
      && (
        pathname === '/api/v1/workbench/agent/sessions'
        || /^\/api\/v1\/workbench\/agent\/sessions\/[^/]+\/messages$/.test(pathname)
      )
    ) {
      agentSessionPosts.push(pathname)
    }
  })

  try {
    currentStep = 'sign-in/presence heartbeat'\n    console.log('[1/10] Sign in and verify presence renewal')
    await page.goto(`${WORKBENCH}/workbench/login`, { waitUntil: 'domcontentloaded' })
    await page.getByLabel('Work email').waitFor({ state: 'visible', timeout: 30000 })
    await captureSurface(page, 'sign-in')
    await page.getByLabel('Work email').fill(STAFF_EMAIL)
    await page.getByLabel('Password').fill(STAFF_PASSWORD)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await page.waitForURL((url) => !url.pathname.includes('/workbench/login'), { timeout: 30000 })
    await waitForNodeCondition(
      () => presencePatches.length > 0,
      'No staff-presence PATCH was observed after sign-in.',
      30000,
    )
    result.checks.presence_heartbeat_after_login = true

    currentStep = 'demo seed'\n    console.log('[2/10] Seed the bounded Workbench scenarios')
    const seeded = await api(page, '/api/v1/workbench/demo/seed-scenarios', { method: 'POST' })
    assert(seeded.status === 200, `Demo seed failed with ${seeded.status}: ${JSON.stringify(seeded.payload)}`)
    assert(seeded.payload?.claim_ids?.includes(AT02), 'AT-02 is missing from the seed response.')
    assert(seeded.payload?.claim_ids?.includes(AT10), 'AT-10 is missing from the seed response.')
    result.checks.demo_seed_loaded = true

    currentStep = 'desktop shell/queue'\n    console.log('[3/10] Enumerate the desktop shell and queue')
    await page.goto(`${WORKBENCH}/workbench`, { waitUntil: 'domcontentloaded' })
    await page.getByLabel('Search claims').waitFor({ state: 'visible', timeout: 30000 })
    const queueControls = await captureSurface(page, 'desktop-claim-queue')
    assert(queueControls.some((item) => /Workbench/i.test(item.name)), 'Workbench navigation is missing.')
    assert(queueControls.some((item) => /Draft claims/i.test(item.name)), 'Draft claims navigation is missing.')
    assert(queueControls.some((item) => /Claim conversations/i.test(item.name)), 'Claim conversations navigation is missing.')
    assert(queueControls.some((item) => /Staff Agent/i.test(item.name)), 'Staff Agent navigation is missing.')
    await screenshot(page, '01-desktop-queue')

    const accountMenu = page.getByRole('button', { name: /Account menu for/i })
    await accountMenu.click()
    await page.getByRole('menu').waitFor({ state: 'visible', timeout: 10000 })
    await captureSurface(page, 'account-menu')
    await page.keyboard.press('Escape')

    await page.goto(`${WORKBENCH}/workbench/drafts`, { waitUntil: 'domcontentloaded' })
    await page.locator('.workbench-stage').waitFor({ state: 'visible', timeout: 30000 })
    await page.waitForTimeout(200)
    await captureSurface(page, 'draft-claims')

    await page.goto(`${WORKBENCH}/workbench/conversations`, { waitUntil: 'domcontentloaded' })
    await page.locator('.workbench-stage').waitFor({ state: 'visible', timeout: 30000 })
    await page.waitForTimeout(200)
    await captureSurface(page, 'conversations-page')

    currentStep = 'AT-02 Claim surfaces'\n    console.log('[4/10] Enumerate representative Claim surfaces on AT-02')
    const claimSections = [
      ['summary', 'claim-overview'],
      ['fields', 'claim-information'],
      ['evidence', 'claim-evidence'],
      ['references', 'claim-reference-checks'],
      ['external-services', 'claim-external-services'],
      ['signals', 'claim-signals'],
      ['activity', 'claim-activity'],
      ['conversation', 'claim-conversation'],
    ]
    for (const [section, name] of claimSections) {
      await page.goto(`${WORKBENCH}/workbench/claims/${AT02}/${section}`, { waitUntil: 'domcontentloaded' })
      await page.locator('.workbench-stage').waitFor({ state: 'visible', timeout: 30000 })
      await page.waitForTimeout(250)
      await captureSurface(page, name)
    }
    await screenshot(page, '02-at02-conversation')

    currentStep = 'AT-02 own/foreign realtime revisions'\n    console.log('[5/10] Verify own versus foreign realtime revision notices in two Workbench pages')
    await page.goto(`${WORKBENCH}/workbench/claims/${AT02}/summary`, { waitUntil: 'domcontentloaded' })
    const reviewAcceptance = page.getByRole('button', { name: 'Review acceptance', exact: true })
    await reviewAcceptance.waitFor({ state: 'visible', timeout: 30000 })
    await reviewAcceptance.click()
    const confirmAccept = page.getByRole('button', { name: /Confirm Accept Claim/i })
    await confirmAccept.waitFor({ state: 'visible', timeout: 10000 })
    await confirmAccept.click()

    // Follow the same authoritative journey as the Workbench handoff tests:
    // wait for the accepted projection before leaving the summary surface.
    const openConversation = page.getByRole('button', { name: 'Open conversation', exact: true })
    await openConversation.waitFor({ state: 'visible', timeout: 30000 })
    await openConversation.click()
    await page.waitForURL(
      (url) => url.pathname === `/workbench/claims/${AT02}/conversation`,
      { timeout: 30000 },
    )
    const composer = page.getByLabel('Message to claimant')
    await composer.waitFor({ state: 'visible', timeout: 30000 })
    const ownMessage = 'Exact-head own mutation check.'
    await composer.fill(ownMessage)
    await page.getByRole('button', { name: 'Send message', exact: true }).click()
    await page.getByText(ownMessage, { exact: true }).waitFor({ state: 'visible', timeout: 30000 })
    await page.waitForTimeout(500)
    assert(
      await page.getByText(/changed in another session/i).count() === 0,
      'The current page announced its own successful mutation as an external change.',
    )

    const otherPage = await context.newPage()
    await otherPage.goto(`${WORKBENCH}/workbench/claims/${AT02}/conversation`, { waitUntil: 'domcontentloaded' })
    const otherComposer = otherPage.getByLabel('Message to claimant')
    await otherComposer.waitFor({ state: 'visible', timeout: 30000 })
    const foreignMessage = 'Exact-head second-session mutation check.'
    await otherComposer.fill(foreignMessage)
    await otherPage.getByRole('button', { name: 'Send message', exact: true }).click()
    await otherPage.getByText(foreignMessage, { exact: true }).waitFor({ state: 'visible', timeout: 30000 })
    await page.getByText(/changed in another session/i).waitFor({ state: 'visible', timeout: 30000 })
    result.checks.own_mutation_notice_suppressed = true
    result.checks.foreign_mutation_notice_visible = true
    await otherPage.close()

    currentStep = 'AT-10 presence/Take Claim/decision'\n    console.log('[6/10] Exercise presence failure, Take Claim, and Claim decision on AT-10')
    await page.goto(`${WORKBENCH}/workbench/claims/${AT10}/summary`, { waitUntil: 'domcontentloaded' })
    const reviewOwnership = page.getByRole('button', { name: 'Review ownership', exact: true })
    await reviewOwnership.waitFor({ state: 'visible', timeout: 30000 })

    const unavailable = await api(page, '/api/v1/workbench/staff/presence', {
      method: 'PATCH',
      body: { available: false, lease_seconds: 300 },
    })
    assert(unavailable.status === 200, `Setting staff unavailable failed: ${unavailable.status}`)

    await reviewOwnership.click()
    const takeClaim = page.getByRole('button', { name: 'Take Claim', exact: true })
    await takeClaim.waitFor({ state: 'visible', timeout: 10000 })
    await takeClaim.click()
    await page.getByText(/staff presence is not currently available for new work/i)
      .waitFor({ state: 'visible', timeout: 30000 })
    result.mutations.take_claim_unavailable = 'explicit STAFF_NOT_AVAILABLE guidance rendered'

    const available = await api(page, '/api/v1/workbench/staff/presence', {
      method: 'PATCH',
      body: { available: true, lease_seconds: 300 },
    })
    assert(available.status === 200, `Restoring staff availability failed: ${available.status}`)

    // The failed mutation correctly refreshes the Claim and removes the action while
    // staff presence is unavailable. Re-read the authoritative projection after
    // restoring availability instead of reusing the now-stale dialog control.
    await page.goto(`${WORKBENCH}/workbench/claims/${AT10}/summary`, { waitUntil: 'domcontentloaded' })
    const refreshedReviewOwnership = page.getByRole('button', { name: 'Review ownership', exact: true })
    await refreshedReviewOwnership.waitFor({ state: 'visible', timeout: 30000 })
    await refreshedReviewOwnership.click()
    const retryTakeClaim = page.getByRole('button', { name: 'Take Claim', exact: true })
    await retryTakeClaim.waitFor({ state: 'visible', timeout: 10000 })
    await retryTakeClaim.click()
    await page.getByText('Claim assigned to you. Review started.', { exact: true })
      .waitFor({ state: 'visible', timeout: 30000 })
    result.mutations.take_claim_success = true

    const continueReview = page.getByRole('button', { name: 'Continue review', exact: true })
    await continueReview.waitFor({ state: 'visible', timeout: 30000 })
    await continueReview.click()
    const approveClaim = page.getByRole('button', { name: 'Approve Claim', exact: true }).first()
    const rejectClaim = page.getByRole('button', { name: 'Reject Claim', exact: true }).first()
    await approveClaim.waitFor({ state: 'visible', timeout: 10000 })
    assert(await rejectClaim.isVisible(), 'Reject Claim is not visible after taking AT-10.')
    await approveClaim.click()
    await page.getByLabel('Public approval explanation (optional)')
      .fill('Approved during exact-head Workbench browser inventory.')
    await page.getByRole('button', { name: 'Approve Claim', exact: true }).last().click()
    await page.getByRole('heading', { name: 'Claim approved', exact: true })
      .waitFor({ state: 'visible', timeout: 30000 })
    result.mutations.claim_decision = 'approved and authoritative success rendered'
    await captureSurface(page, 'at10-after-decision')
    await screenshot(page, '03-at10-approved')

    currentStep = 'Staff Agent fail-closed'\n    console.log('[7/10] Verify Staff Agent fail-closed behavior')
    await page.goto(`${WORKBENCH}/workbench`, { waitUntil: 'domcontentloaded' })
    const openAgent = page.getByRole('button', { name: 'Staff Agent', exact: true }).first()
    await openAgent.waitFor({ state: 'visible', timeout: 30000 })
    await openAgent.click()
    await page.getByRole('heading', { name: 'Staff Agent', exact: true })
      .waitFor({ state: 'visible', timeout: 10000 })
    await page.getByText('Staff Agent cannot answer right now', { exact: true })
      .waitFor({ state: 'visible', timeout: 10000 })
    const agentInput = page.getByLabel('Message Staff Agent')
    await agentInput.fill('Can this unavailable model send?')
    const agentSend = page.getByRole('button', { name: 'Send to Staff Agent', exact: true })
    assert(await agentSend.isDisabled(), 'Staff Agent send is enabled without a published model.')
    await agentInput.press('Enter')
    await page.waitForTimeout(300)
    assert(agentSessionPosts.length === 0, `Staff Agent sent while unavailable: ${JSON.stringify(agentSessionPosts)}`)
    result.checks.staff_agent_no_model_fail_closed = true
    await captureSurface(page, 'staff-agent-desktop')
    await screenshot(page, '04-staff-agent-unavailable')
    await page.getByRole('button', { name: 'Close Staff Agent', exact: true }).click()

    currentStep = 'staff-scoped tab persistence'\n    console.log('[8/10] Verify staff-scoped Claim-tab persistence')
    const tabKeys = await page.evaluate(() => (
      Object.keys(localStorage).filter((key) => key.startsWith('northwind.workbench.tabs.v1'))
    ))
    assert(!tabKeys.includes('northwind.workbench.tabs.v1'), 'Legacy unscoped Workbench tab key still exists.')
    assert(tabKeys.some((key) => key.startsWith('northwind.workbench.tabs.v1:')), `No staff-scoped tab key found: ${JSON.stringify(tabKeys)}`)
    result.checks.staff_scoped_tab_storage = tabKeys

    currentStep = 'settings/phone layout'\n    console.log('[9/10] Enumerate settings and phone-width behavior')
    for (const section of ['profile', 'security', 'notifications', 'appearance', 'help']) {
      await page.goto(`${WORKBENCH}/workbench/settings/${section}`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading').first().waitFor({ state: 'visible', timeout: 30000 })
      await page.waitForTimeout(150)
      await captureSurface(page, `settings-${section}`)
    }

    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(`${WORKBENCH}/workbench/claims/${AT02}/summary`, { waitUntil: 'domcontentloaded' })
    const showQueue = page.getByRole('button', { name: 'Show Claim queue', exact: true })
    await showQueue.waitFor({ state: 'visible', timeout: 30000 })
    assert(await showQueue.getAttribute('aria-expanded') === 'false', 'Phone queue toggle has the wrong aria-expanded state.')
    await showQueue.click()
    await page.waitForURL((url) => url.pathname === '/workbench', { timeout: 30000 })
    await page.getByLabel('Search claims').waitFor({ state: 'visible', timeout: 10000 })
    result.checks.phone_queue_return = true

    const phoneAgent = page.getByRole('button', { name: 'Staff Agent', exact: true }).first()
    await phoneAgent.click()
    await page.getByLabel('Message Staff Agent').waitFor({ state: 'visible', timeout: 10000 })
    result.checks.phone_staff_agent_panel = true
    await captureSurface(page, 'phone-workbench-agent')
    await screenshot(page, '05-phone-agent')

    currentStep = 'complete'\n    console.log('[10/10] Exact-head Workbench inventory evidence passed')
    result.status = 'PASS'
    fs.writeFileSync(
      path.join(ARTIFACT_DIR, 'pr1170-workbench-inventory-PASS.json'),
      JSON.stringify(result, null, 2),
      'utf8',
    )
    console.log('PR1170_WORKBENCH_INVENTORY_OK')
    console.log(`HEAD=${HEAD}`)
    console.log(`SURFACES=${Object.keys(result.surfaces).length}`)
    await reportGitHubStatus('success', 'Exact-head Workbench inventory passed')
  } catch (error) {
    result.status = 'FAIL'
    result.error = error?.stack || String(error)
    try {
      await screenshot(page, 'FAIL-workbench-inventory')
    } catch {
      // Preserve the primary failure.
    }
    fs.writeFileSync(
      path.join(ARTIFACT_DIR, 'pr1170-workbench-inventory-FAIL.json'),
      JSON.stringify(result, null, 2),
      'utf8',
    )
    await reportGitHubStatus(
      'failure',
      `${currentStep}: ${error?.message || String(error)}`,
    )
    throw error
  } finally {
    await browser.close()
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})

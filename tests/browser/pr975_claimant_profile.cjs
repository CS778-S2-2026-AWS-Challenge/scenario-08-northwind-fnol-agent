const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const CUSTOMER = process.env.NORTHWIND_CUSTOMER_URL || 'http://127.0.0.1:8001'
const HEAD = process.env.PR_HEAD_SHA || 'unknown'
const ARTIFACT_DIR = path.resolve(process.env.BROWSER_EVIDENCE_DIR || 'browser-evidence')
fs.mkdirSync(ARTIFACT_DIR, { recursive: true })

const result = {
  head: HEAD,
  browser: 'Playwright Chromium',
  checks: {},
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

async function hasNoHorizontalOverflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)
}

async function login(page) {
  await page.goto(`${CUSTOMER}/auth/login`, { waitUntil: 'domcontentloaded' })
  await page.getByLabel('Email address').fill('claimant.one@example.invalid')
  await page.getByLabel('Password').fill('northwind-demo-one')
  await page.locator('.login-form').getByRole('button', { name: 'Log in', exact: true }).click()
  await page.getByPlaceholder('Tell us what happened…').waitFor({ state: 'visible', timeout: 30000 })
}

async function main() {
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()

  try {
    console.log('[1/6] Sign in and recover the legacy Policies deep link')
    await login(page)
    await page.goto(`${CUSTOMER}/profile/policies`, { waitUntil: 'domcontentloaded' })
    await page.getByRole('heading', { name: 'Personal information', exact: true }).waitFor({ state: 'visible', timeout: 30000 })
    assert(new URL(page.url()).pathname === '/profile/personal-details', 'Legacy Policies deep link did not recover to Personal details.')
    assert(await page.getByRole('button', { name: 'Policies', exact: true }).count() === 0, 'Removed Policies navigation is still visible.')
    await page.locator('.profile-header-meta').getByText('Policy number', { exact: true }).waitFor({ state: 'visible' })
    await page.locator('.profile-policy-disclosure').waitFor({ state: 'visible' })
    assert(await hasNoHorizontalOverflow(page), 'Desktop Personal details page has horizontal overflow.')
    result.checks.legacy_policies_deep_link_recovers = true
    result.checks.desktop_policy_number_visible = true
    result.checks.desktop_no_horizontal_overflow = true
    await screenshot(page, 'pr1024-01-desktop-personal-details')

    console.log('[2/6] Refresh the recovered route and verify browser Back navigation')
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.getByRole('heading', { name: 'Personal information', exact: true }).waitFor({ state: 'visible' })
    assert(new URL(page.url()).pathname === '/profile/personal-details', 'Recovered Personal details route did not survive refresh.')
    await page.locator('.profile-sidebar').getByRole('button', { name: 'Insured assets', exact: true }).click()
    await page.getByRole('heading', { name: 'Insured assets', exact: true }).waitFor({ state: 'visible' })
    await page.goBack()
    await page.getByRole('heading', { name: 'Personal information', exact: true }).waitFor({ state: 'visible' })
    assert(new URL(page.url()).pathname === '/profile/personal-details', 'Browser Back did not restore Personal details.')
    result.checks.refresh_preserves_recovered_route = true
    result.checks.browser_back_restores_personal_details = true

    console.log('[3/6] Verify preferred-name save focus and restore the fixture value')
    const editProfile = page.getByRole('button', { name: 'Edit profile', exact: true })
    await editProfile.click()
    const preferredName = page.getByLabel('Preferred name', { exact: true })
    await preferredName.waitFor({ state: 'visible' })
    assert(await preferredName.evaluate((element) => element === document.activeElement), 'Preferred name did not receive focus.')
    const originalPreferredName = await preferredName.inputValue()
    const evidencePreferredName = `${originalPreferredName || 'Claimant'} browser check`
    await preferredName.fill(evidencePreferredName)
    await page.getByRole('button', { name: 'Save profile', exact: true }).click()
    await page.getByText('Profile information was updated in your saved Northwind account.', { exact: true })
      .waitFor({ state: 'visible', timeout: 30000 })
    assert(await editProfile.evaluate((element) => element === document.activeElement), 'Focus did not return to Edit profile after save.')

    await editProfile.click()
    await page.getByLabel('Preferred name', { exact: true }).fill(originalPreferredName)
    await page.getByRole('button', { name: 'Save profile', exact: true }).click()
    await editProfile.waitFor({ state: 'visible', timeout: 30000 })
    result.checks.preferred_name_editor_receives_focus = true
    result.checks.preferred_name_save_returns_focus = true
    result.checks.preferred_name_fixture_restored = true
    await screenshot(page, 'pr1024-02-desktop-personal-details')

    console.log('[4/6] Verify payment capabilities are rendered from the supported projection')
    await page.locator('.profile-sidebar').getByRole('button', { name: 'Payment details', exact: true }).click()
    await page.getByRole('heading', { name: 'Payment details', exact: true }).waitFor({ state: 'visible' })
    await page.getByText('Adding or changing payment details remains unavailable in this Profile delivery.', { exact: true })
      .waitFor({ state: 'visible', timeout: 30000 })
    assert(await page.getByRole('button', { name: /add payment/i }).count() === 0, 'Unsupported payment mutation control is visible.')
    result.checks.payment_read_projection_visible = true
    result.checks.payment_mutation_controls_gated = true

    console.log('[5/6] Verify the mobile category index, category Back action, and overflow')
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(`${CUSTOMER}/profile`, { waitUntil: 'domcontentloaded' })
    const mobileIndex = page.locator('.profile-mobile-index')
    await mobileIndex.getByRole('button', { name: 'Personal details', exact: true }).waitFor({ state: 'visible', timeout: 30000 })
    assert(await mobileIndex.getByRole('button', { name: 'Policies', exact: true }).count() === 0, 'Removed Policies category is visible in the mobile index.')
    assert(await hasNoHorizontalOverflow(page), 'Mobile Profile index has horizontal overflow.')
    await screenshot(page, 'pr1024-03-mobile-category-index')

    await mobileIndex.getByRole('button', { name: 'Personal details', exact: true }).click()
    await page.getByRole('heading', { name: 'Personal information', exact: true }).waitFor({ state: 'visible' })
    await page.locator('.profile-header-meta').getByText('Policy number', { exact: true }).waitFor({ state: 'visible' })
    await page.locator('.profile-policy-disclosure').waitFor({ state: 'visible' })
    assert(new URL(page.url()).pathname === '/profile/personal-details', 'Mobile Personal details route did not open.')
    assert(await hasNoHorizontalOverflow(page), 'Mobile Personal details page has horizontal overflow.')
    await screenshot(page, 'pr1024-04-mobile-personal-details')

    await page.getByRole('button', { name: 'Back to profile', exact: true }).click()
    await mobileIndex.getByRole('button', { name: 'Personal details', exact: true }).waitFor({ state: 'visible' })
    assert(new URL(page.url()).pathname === '/profile', 'Mobile Back did not restore the category index.')
    result.checks.mobile_category_index_visible = true
    result.checks.mobile_policy_number_visible = true
    result.checks.mobile_category_back_restores_index = true
    result.checks.mobile_no_horizontal_overflow = true

    console.log('[6/6] Profile browser evidence passed')
    result.status = 'PASS'
    fs.writeFileSync(
      path.join(ARTIFACT_DIR, 'pr975-claimant-profile-PASS.json'),
      JSON.stringify(result, null, 2),
      'utf8',
    )
    console.log('PR975_CLAIMANT_PROFILE_BROWSER_EVIDENCE_OK')
    console.log(`HEAD=${HEAD}`)
  } catch (error) {
    result.status = 'FAIL'
    result.error = error?.stack || String(error)
    try {
      await screenshot(page, 'pr975-FAIL-claimant-profile')
    } catch {
      // Preserve the primary failure.
    }
    fs.writeFileSync(
      path.join(ARTIFACT_DIR, 'pr975-claimant-profile-FAIL.json'),
      JSON.stringify(result, null, 2),
      'utf8',
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

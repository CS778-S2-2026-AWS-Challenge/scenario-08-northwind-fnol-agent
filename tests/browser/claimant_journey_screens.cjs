// Claimant journey screens: screenshots of one real Claim, taken from the running app.
//
// The Claim is driven end to end on start-dev with the real model, by a person or by a corpus
// run. This script only opens its pages and records what it captured. It never sets Claim state,
// injects data or stubs a request. The one thing it does is sign in, by storing the claimant's
// session token where the app keeps it, so it sees exactly what that claimant sees. Run it at
// each stage you want on record (first reply, document request, review, lodged, ...).
//
//   NORTHWIND_CLAIMANT_TOKEN=<session token>   the signed-in claimant who owns the Claim
//   NORTHWIND_CLAIM_ID=clm_...                 the Claim to capture
//   CORPUS_CASE_ID=CTL-M-002                   optional: the controlled-corpus pack it came from
//   node tests/browser/claimant_journey_screens.cjs <label> [view ...]
//
// Views: entry-anonymous, entry, conversation, case-panel, my-claims, claim-details.
// Default views: conversation and case-panel. SCREEN_WIDTHS defaults to 1440,390.
// Output: BROWSER_EVIDENCE_DIR/claimant-journey-screens/<label>-<view>-<width>.png, plus one
// JSON line per screenshot in index.jsonl (head, case, Claim, view, width, identity, time,
// and any alert text on the page). The token is never written to disk or printed.
const fs = require('node:fs')
const path = require('node:path')
const { execSync } = require('node:child_process')
const { chromium } = require('playwright')

const CUSTOMER = process.env.NORTHWIND_CUSTOMER_URL || 'http://127.0.0.1:5173'
const TOKEN = process.env.NORTHWIND_CLAIMANT_TOKEN || ''
const CLAIM_ID = process.env.NORTHWIND_CLAIM_ID || ''
const CASE_ID = process.env.CORPUS_CASE_ID || null
const WIDTHS = (process.env.SCREEN_WIDTHS || '1440,390').split(',').map(Number)
const ARTIFACT_DIR = path.resolve(process.env.BROWSER_EVIDENCE_DIR || 'browser-evidence', 'claimant-journey-screens')
const HEAD = process.env.PR_HEAD_SHA || gitHead()
const BUSY = /Checking your account|Opening the conversation|Loading your/

const VIEWS = {
  'entry-anonymous': { route: () => '/', signedIn: false, text: 'Start your insurance claim' },
  entry: { route: () => '/', signedIn: true, text: 'Start your insurance claim' },
  conversation: { route: () => `/claims/${CLAIM_ID}`, signedIn: true, claim: true, text: 'Claims assistant' },
  'case-panel': { route: () => `/claims/${CLAIM_ID}`, signedIn: true, claim: true, text: 'Claims assistant', panel: true },
  'my-claims': { route: () => '/account/claims', signedIn: true, selector: '#claim-history-in-progress-title, #claim-history-past-title' },
  'claim-details': { route: () => `/account/claims/${CLAIM_ID}`, signedIn: true, claim: true, selector: '#claim-features-title' },
}

function gitHead() {
  try {
    return execSync('git rev-parse --short HEAD').toString().trim()
  } catch {
    return 'unknown'
  }
}

function fail(message) {
  console.error(message)
  process.exit(2)
}

async function capture(browser, label, view, width) {
  const spec = VIEWS[view]
  const context = await browser.newContext({ viewport: { width, height: width < 768 ? 844 : 900 }, isMobile: width < 768 })
  if (spec.signedIn) await context.addInitScript((token) => localStorage.setItem('northwind.claimantToken', token), TOKEN)
  const page = await context.newPage()
  const file = path.join(ARTIFACT_DIR, `${label}-${view}-${width}.png`)
  try {
    await page.goto(CUSTOMER + spec.route(), { waitUntil: 'domcontentloaded' })
    if (spec.selector) await page.waitForSelector(spec.selector, { timeout: 45000 })
    if (spec.text) await page.getByText(spec.text).first().waitFor({ timeout: 45000 })
    await page.waitForFunction((pattern) => !new RegExp(pattern).test(document.body.innerText), BUSY.source, { timeout: 45000 })
    if (spec.panel) {
      // The panel may already be open on its own; only open it when it is closed.
      const toggle = page.locator('button.case-status')
      if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click()
      await page.getByText('Your claim').first().waitFor({ timeout: 15000 })
    }
    await page.waitForTimeout(1000)
    const alerts = (await page.locator('[role=alert]').allInnerTexts()).map((text) => text.trim()).filter(Boolean)
    await page.screenshot({ path: file })
    return { label, view, width, file: path.basename(file), head: HEAD, case_id: CASE_ID, claim_id: spec.claim ? CLAIM_ID : null, signed_in: spec.signedIn, url: new URL(page.url()).pathname, captured_at: new Date().toISOString(), alerts }
  } finally {
    await context.close()
  }
}

async function main() {
  const [label, ...requested] = process.argv.slice(2)
  if (!label || !/^[A-Za-z0-9_-]+$/.test(label)) fail('Usage: node tests/browser/claimant_journey_screens.cjs <label> [view ...]')
  const views = requested.length ? requested : ['conversation', 'case-panel']
  const unknown = views.filter((view) => !VIEWS[view])
  if (unknown.length) fail(`Unknown view(s): ${unknown.join(', ')}. Views: ${Object.keys(VIEWS).join(', ')}`)
  if (views.some((view) => VIEWS[view].signedIn) && !TOKEN) fail('NORTHWIND_CLAIMANT_TOKEN is required for signed-in views.')
  if (views.some((view) => VIEWS[view].claim) && !/^clm_[a-z0-9]+$/.test(CLAIM_ID)) fail('NORTHWIND_CLAIM_ID must be a clm_ id.')

  fs.mkdirSync(ARTIFACT_DIR, { recursive: true })
  const browser = await chromium.launch()
  const failures = []
  try {
    for (const width of WIDTHS) {
      for (const view of views) {
        try {
          const record = await capture(browser, label, view, width)
          fs.appendFileSync(path.join(ARTIFACT_DIR, 'index.jsonl'), `${JSON.stringify(record)}\n`)
          console.log(`${record.alerts.length ? 'ALERT' : 'OK'} ${record.file}${record.alerts.length ? ` ${record.alerts.join(' / ')}` : ''}`)
        } catch (error) {
          failures.push(`${view} at ${width}px: ${error.message.split('\n')[0]}`)
          console.log(`FAIL ${label}-${view}-${width}: ${error.message.split('\n')[0]}`)
        }
      }
    }
  } finally {
    await browser.close()
  }
  if (failures.length) {
    console.error(`${failures.length} screen(s) not captured`)
    process.exit(1)
  }
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})

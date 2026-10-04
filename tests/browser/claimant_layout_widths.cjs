// Claimant layout evidence (#1184): one conversation at the five design widths,
// with the case panel closed and open. Fails on horizontal overflow, or when the
// composer is not on screen on a phone. Screenshots go to BROWSER_EVIDENCE_DIR.
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const CUSTOMER = process.env.NORTHWIND_CUSTOMER_URL || 'http://127.0.0.1:8001'
const HEAD = process.env.PR_HEAD_SHA || 'unknown'
const ARTIFACT_DIR = path.resolve(process.env.BROWSER_EVIDENCE_DIR || 'browser-evidence', 'claimant-widths')
fs.mkdirSync(ARTIFACT_DIR, { recursive: true })

const WIDTHS = [1440, 1366, 980, 640, 390]
const PHONE_WIDTH = 640
const MESSAGE = 'Someone rear-ended me at the lights on Dominion Road. Nobody is hurt and my car still drives.'

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function overflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
}

async function composerOnScreen(page) {
  return page.evaluate(() => {
    const composer = document.querySelector('.workspace-composer')
    if (!composer) return false
    const box = composer.getBoundingClientRect()
    return box.top >= 0 && box.bottom <= window.innerHeight + 1
  })
}

async function main() {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const results = []
  try {
    await page.goto(CUSTOMER, { waitUntil: 'domcontentloaded' })
    await page.getByPlaceholder('Tell us what happened…').fill(MESSAGE)
    await page.getByRole('button', { name: 'Start claim', exact: true }).click()
    await page.locator('.msg-agent .agent-text').first().waitFor({ state: 'visible', timeout: 60000 })
    const status = page.locator('.case-status')
    await status.waitFor({ state: 'visible', timeout: 30000 })

    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width <= PHONE_WIDTH ? 844 : 900 })
      await page.waitForTimeout(400)
      if ((await status.getAttribute('aria-expanded')) === 'true') {
        await page.getByRole('button', { name: 'Close panel' }).click()
        await page.waitForTimeout(400)
      }
      await page.screenshot({ path: path.join(ARTIFACT_DIR, `w${width}-panel-closed.png`) })
      const closedOverflow = await overflow(page)
      const composerVisible = width <= PHONE_WIDTH ? await composerOnScreen(page) : true

      await status.click()
      await page.locator('.intake-details-panel.is-open').waitFor({ state: 'visible', timeout: 10000 })
      await page.waitForTimeout(600)
      await page.screenshot({ path: path.join(ARTIFACT_DIR, `w${width}-panel-open.png`) })
      const openOverflow = await overflow(page)

      results.push({ width, closedOverflow, openOverflow, composerVisible })
      assert(closedOverflow <= 0 && openOverflow <= 0, `Horizontal overflow at ${width}px: ${JSON.stringify(results.at(-1))}`)
      assert(composerVisible, `Composer is off screen at ${width}px.`)
    }
    console.log('CLAIMANT_LAYOUT_WIDTHS_OK')
  } finally {
    fs.writeFileSync(path.join(ARTIFACT_DIR, 'result.json'), JSON.stringify({ head: HEAD, results }, null, 2))
    console.log(`HEAD=${HEAD}`)
    console.log(`RESULTS=${JSON.stringify(results)}`)
    await browser.close()
  }
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})

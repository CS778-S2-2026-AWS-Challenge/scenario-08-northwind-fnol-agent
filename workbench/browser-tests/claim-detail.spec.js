import { expect, test } from '@playwright/test'

for (const viewport of [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
]) {
  test(`long Claim detail remains operable at the ${viewport.name} viewport`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await page.goto('/workbench/browser-acceptance.html')

    await expect(page.getByRole('heading', { name: 'Request cowork access' })).toHaveCount(1)
    await expect(page.getByText('Missing item 6', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('Missing item 8', { exact: true }).first()).toBeHidden()

    const showAll = page.locator('.missing-information__all > button')
    await expect(showAll).toHaveAccessibleName('Show all missing information')
    await showAll.focus()
    await page.keyboard.press('Enter')
    await expect(showAll).toHaveAttribute('aria-expanded', 'true')
    await expect(page.getByText('Missing item 8', { exact: true }).first()).toBeVisible()
    await expect(page.getByText(/msg_8, field:item_8/)).toBeVisible()
    await expect(page.getByText('Human Resolve Handoff', { exact: true })).toBeVisible()

    for (const label of ['Ownership and handoff actions', 'Supporting Claim context', 'Signals and classification']) {
      const disclosure = page.getByText(label, { exact: true })
      await disclosure.focus()
      await page.keyboard.press('Enter')
    }

    const panel = page.locator('.browser-acceptance-panel')
    const dimensions = await panel.evaluate((element) => ({
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }))
    expect(dimensions.scrollHeight).toBeGreaterThan(dimensions.clientHeight)
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width)

    await panel.hover()
    await page.mouse.wheel(0, 20_000)
    await expect.poll(() => panel.evaluate((element) => Math.round(element.scrollTop + element.clientHeight - element.scrollHeight))).toBeGreaterThanOrEqual(-1)

    const minimumFontSize = await page.locator('main').evaluate((main) => Math.min(
      ...[...main.querySelectorAll('*')]
        .filter((element) => element.textContent.trim() && getComputedStyle(element).display !== 'none')
        .map((element) => Number(getComputedStyle(element).fontSize.replace('px', ''))),
    ))
    expect(minimumFontSize).toBeGreaterThanOrEqual(14)
  })
}

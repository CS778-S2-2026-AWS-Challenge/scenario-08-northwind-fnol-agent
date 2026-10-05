import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// jsdom does no layout, so the one-line rule is checked on the stylesheet itself.
const styles = readFileSync('src/styles/case-panel.css', 'utf8')
const tidyStyles = readFileSync('src/styles/claimant-tidy.css', 'utf8')

function rule(selector) {
  const start = styles.indexOf(`${selector} {`)
  return start < 0 ? '' : styles.slice(start, styles.indexOf('}', start))
}

describe('case panel text that must stay on one line', () => {
  it.each(['.open-items-bar-text', '.turn-receipt-text'])('%s is cut with an ellipsis, never wrapped', (selector) => {
    const body = rule(selector)
    expect(body).toMatch(/min-width: 0/)
    expect(body).toMatch(/overflow: hidden/)
    expect(body).toMatch(/text-overflow: ellipsis/)
    expect(body).toMatch(/white-space: nowrap/)
  })
})

describe('case panel layout', () => {
  it('reserves a grid column for the open panel when the conversation can adapt', () => {
    expect(tidyStyles).toContain('@media (max-width: 1439px) and (min-width: 981px)')
    expect(tidyStyles).toContain('.intake-page.details-open')
    expect(tidyStyles).toContain('grid-template-columns: var(--claimant-rail-width) minmax(0, 1fr) var(--claimant-details-panel-width);')
    expect(tidyStyles).toContain('position: relative;')
    expect(tidyStyles).toContain('width: 100%;')
  })
})

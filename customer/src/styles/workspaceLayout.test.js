import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const styles = readFileSync('src/styles/claimant-tidy.css', 'utf8')

describe('desktop claimant workspace height', () => {
  it('allocates the visible header before the workspace fills the viewport', () => {
    const shellSelector = '.customer-app.workspace-shell'
    const shellStart = styles.indexOf(`${shellSelector} {`)
    const shellBody = styles.slice(shellStart, styles.indexOf('}', shellStart))
    const pageSelector = '.customer-app.workspace-shell > .intake-page'
    const pageStart = styles.indexOf(`${pageSelector} {`)
    const pageBody = styles.slice(pageStart, styles.indexOf('}', pageStart))

    expect(styles).toContain('@media (min-width: 641px)')
    expect(shellStart).toBeGreaterThan(-1)
    expect(shellBody).toContain('display: grid;')
    expect(shellBody).toContain('min-height: 100dvh;')
    expect(shellBody).toContain('height: 100dvh;')
    expect(shellBody).toContain('grid-template-rows: auto minmax(0, 1fr);')
    expect(shellBody).toContain('overflow: hidden;')
    expect(pageStart).toBeGreaterThan(-1)
    // Anchoring both block edges prevents focusing the composer from scrolling
    // the workspace above the viewport and exposing the shell background.
    expect(pageBody).toContain('position: fixed;')
    expect(pageBody).toContain('inset-block: var(--size-header-compact) 0;')
    expect(pageBody).toContain('inset-inline: 0;')
    expect(pageBody).toContain('width: 100%;')
    expect(pageBody).toContain('min-height: 0;')
    expect(pageBody).toContain('height: auto;')
    expect(pageBody).toContain('overflow: hidden;')
    // Without an explicit row track the conversation column collapses to its
    // content height and the workspace background shows under the composer.
    expect(pageBody).toContain('grid-template-rows: minmax(0, 1fr);')
    expect(styles).toContain('.intake-page.details-closed { grid-template-columns: var(--claimant-rail-width) minmax(0, 1fr) 0; }')
  })
})

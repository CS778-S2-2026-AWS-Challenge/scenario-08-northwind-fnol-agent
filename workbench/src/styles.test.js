import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('Workbench density tokens', () => {
  it('does not bypass the 14px Workbench minimum for visible text', () => {
    const styles = readFileSync('src/styles.css', 'utf8')

    expect(styles).not.toMatch(/font-size:\s*(?:1[0-3]|[0-9])px/)
    expect(styles).toContain('font-size: var(--workbench-font-meta)')
  })

  it('bounds the conversation queue and gives compact viewports a list-to-detail flow', () => {
    const styles = readFileSync('src/styles.css', 'utf8')

    expect(styles).toMatch(/\.conversation-workspace \{[^}]*grid-template-columns: minmax\(var\(--density-workbench-conversation-queue-min-width\), var\(--density-workbench-conversation-queue-width\)\) minmax\(0, 1fr\);/)
    expect(styles).toMatch(/\.conversations-page\.is-queue-collapsed \.conversation-workspace \{[^}]*grid-template-columns: minmax\(0, 1fr\);/)
    expect(styles).toMatch(/\.conversations-page\.is-queue-collapsed \.conversation-queue \{ display: none; \}/)
    expect(styles).toMatch(/\.conversation-queue__list \{[^}]*overflow-y: auto;/)
    expect(styles).toMatch(/@media \(max-width: 800px\) \{[\s\S]*\.conversation-workspace \{ display: block;/)
    expect(styles).toMatch(/@media \(max-width: 800px\) \{[\s\S]*\.conversation-queue-toggle \{ display: none; \}/)
    expect(styles).toMatch(/@media \(max-width: 800px\) \{[\s\S]*\.conversations-page\.is-queue-collapsed \.conversation-queue \{ display: block; \}/)
    expect(styles).toMatch(/@media \(max-width: 800px\) \{[\s\S]*\.conversations-page\.is-detail-open \.conversation-queue \{ display: none; \}/)
    expect(styles).toMatch(/@media \(max-width: 800px\) \{[\s\S]*\.conversations-page\.is-detail-open \.conversation-detail \{ display: flex; \}/)
  })

  it('keeps the employee composer compact with four keyboard-sized controls', () => {
    const styles = readFileSync('src/styles.css', 'utf8')

    expect(styles).toMatch(/\.compact-composer__input \{[^}]*min-height: var\(--size-header-compact\);/)
    expect(styles).toMatch(/\.staff-composer__input \{[^}]*grid-template-columns: var\(--space-10\) var\(--space-10\) minmax\(0, 1fr\) var\(--space-10\);/)
    expect(styles).not.toContain('.staff-composer__input--voice')
    expect(styles).toMatch(/\.compact-composer__textarea \{[^}]*max-height: calc\(var\(--space-6\) \* 4\);/)
    expect(styles).toMatch(/\.compact-composer__send \{[^}]*width: var\(--space-10\);[^}]*height: var\(--space-10\);/)
    expect(styles).toContain('.workbench-app:has(.conversation-detail .staff-composer) > .staff-agent:not(.is-open)')
  })

  it('separates the Claim title, conversation state, and supporting metadata', () => {
    const styles = readFileSync('src/styles.css', 'utf8')

    expect(styles).toMatch(/\.claim-heading__summary \{[^}]*margin: var\(--space-2\) 0 0;/)
    expect(styles).toMatch(/\.claim-heading__turn \{[^}]*margin: var\(--space-4\) 0 0;/)
    expect(styles).toMatch(/\.claim-heading__meta \{[^}]*margin-top: var\(--space-6\);/)
    expect(styles).toMatch(/\.claim-heading__references \{[^}]*margin-top: var\(--space-3\);/)
  })

  it('separates the Work summary heading from its projected incident summary', () => {
    const styles = readFileSync('src/styles.css', 'utf8')

    expect(styles).toMatch(/\.work-summary > \.record-summary \{[^}]*margin-top: var\(--space-4\);/)
  })

  it('keeps the Work summary inside the narrow-screen viewport', () => {
    const styles = readFileSync('src/styles.css', 'utf8')

    expect(styles).toMatch(/\.claim-content, \.resource-view, \.conversation-view \{[^}]*min-width: 0;/)
    expect(styles).toMatch(/\.work-summary, \.detail-section \{[^}]*min-width: 0;/)
    expect(styles).toMatch(/@media \(max-width: 480px\) \{[\s\S]*\.work-summary > \.section-heading \{[^}]*flex-direction: column;/)
    expect(styles).toMatch(/@media \(max-width: 480px\) \{[\s\S]*\.work-summary > \.section-heading > \* \{[^}]*max-width: 100%;/)
  })

  it('uses a compact token-based and borderless shared resource empty state', () => {
    const styles = readFileSync('src/styles.css', 'utf8')
    const emptyRule = styles.match(/\.resource-empty-state \{([^}]*)\}/)?.[1]

    expect(emptyRule).toContain('min-height: calc(var(--space-16) * 3)')
    expect(emptyRule).toContain('background: var(--color-surface)')
    expect(emptyRule).not.toMatch(/(?:^|;)\s*border:/)
    expect(styles).toMatch(/\.resource-empty-state__icon \{[^}]*color: var\(--color-text-faint\);/)
  })

  it('distinguishes superseded Claim fields with existing danger tokens', () => {
    const styles = readFileSync('src/styles.css', 'utf8')

    expect(styles).toMatch(/\.claim-field__status--superseded[^{]*\{[^}]*color: var\(--color-danger\);/)
    expect(styles).toMatch(/\.claim-field-popover__guidance--superseded[^{]*\{[^}]*background: var\(--color-danger-soft\);/)
  })

  it('keeps the draggable Staff Agent trigger visible in dark mode', () => {
    const styles = readFileSync('src/styles.css', 'utf8')
    const tokens = readFileSync('../frontend/shared/design-tokens.css', 'utf8')

    expect(styles).toMatch(/\.staff-agent__bubble \{[^}]*background: var\(--color-workbench-nav\);[^}]*color: var\(--color-workbench-nav-active\);/)
    expect(tokens).toContain('--color-workbench-nav-active: var(--color-workbench-dark-text-primary);')
  })
})

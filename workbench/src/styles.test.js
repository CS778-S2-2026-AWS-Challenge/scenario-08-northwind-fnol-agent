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
    expect(styles).toMatch(/\.staff-composer__input--voice \{[^}]*grid-template-columns: var\(--space-10\) var\(--space-10\) minmax\(0, 1fr\) var\(--space-10\);/)
    expect(styles).toMatch(/\.compact-composer__textarea \{[^}]*max-height: calc\(var\(--space-6\) \* 4\);/)
    expect(styles).toMatch(/\.compact-composer__send \{[^}]*width: var\(--space-10\);[^}]*height: var\(--space-10\);/)
    expect(styles).toContain('.workbench-app:has(.conversation-detail .staff-composer) > .staff-agent:not(.is-open)')
  })
})

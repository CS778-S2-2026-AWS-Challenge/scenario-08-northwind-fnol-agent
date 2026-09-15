import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('Workbench density tokens', () => {
  it('does not bypass the 14px Workbench minimum for visible text', () => {
    const styles = readFileSync('src/styles.css', 'utf8')

    expect(styles).not.toMatch(/font-size:\s*(?:1[0-3]|[0-9])px/)
    expect(styles).toContain('font-size: var(--workbench-font-meta)')
  })

  it('bounds Staff Agent conversation history and gives compact viewports a single-column flow', () => {
    const styles = readFileSync('src/styles.css', 'utf8')

    expect(styles).toMatch(/\.staff-agent-conversations__groups \{[^}]*max-height: var\(--density-workbench-list-max-height\);[^}]*overflow-y: auto;/)
    expect(styles).toMatch(/@media \(max-width: 800px\) \{[\s\S]*\.staff-agent-conversations__tools \{ align-items: stretch; flex-direction: column; \}/)
    expect(styles).toMatch(/@media \(max-width: 800px\) \{[\s\S]*\.staff-agent-conversations__pagination \{ align-items: stretch; flex-direction: column; \}/)
    expect(styles).toMatch(/@media \(max-width: 480px\) \{[\s\S]*\.staff-agent-conversations__meta \{[^}]*grid-column: 2;/)
  })
})

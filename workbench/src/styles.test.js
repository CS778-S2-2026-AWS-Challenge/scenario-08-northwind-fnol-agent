import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('Workbench density tokens', () => {
  it('does not bypass the 14px Workbench minimum for visible text', () => {
    const styles = readFileSync('src/styles.css', 'utf8')

    expect(styles).not.toMatch(/font-size:\s*(?:1[0-3]|[0-9])px/)
    expect(styles).toContain('font-size: var(--workbench-font-meta)')
  })
})

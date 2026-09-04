import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('claim detail scrolling', () => {
  it('uses the constrained open Claim panel as the vertical scroll container', () => {
    const styles = readFileSync('src/styles.css', 'utf8')

    expect(styles).toMatch(/\.open-claim-panel\s*\{[^}]*overflow-x:\s*hidden;[^}]*overflow-y:\s*auto;/)
    expect(styles).toMatch(/\.claim-workspace\s*\{[^}]*overflow:\s*visible;/)
  })
})

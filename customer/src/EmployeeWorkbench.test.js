import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const here = dirname(fileURLToPath(import.meta.url))
const employeeEntry = readFileSync(join(here, '../../employee/index.html'), 'utf8')

describe('legacy employee entry isolation', () => {
  it('contains only a migration notice and points staff to the componentised Workbench', () => {
    expect(employeeEntry).toContain('Workbench has moved')
    expect(employeeEntry).toContain('../workbench/')
    expect(employeeEntry).not.toContain('id="claimList"')
    expect(employeeEntry).not.toContain('employee/app.js')
  })

  it('does not reintroduce the retired static Workbench controls', () => {
    for (const legacyId of ['sidebarToggle', 'refreshClaims', 'customerChatNav', 'completeActionSelect']) {
      expect(employeeEntry).not.toContain(`id="${legacyId}"`)
    }
  })
})

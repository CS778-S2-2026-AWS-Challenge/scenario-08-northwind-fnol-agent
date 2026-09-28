import { describe, expect, it } from 'vitest'

import { resolveWorkbenchUrl } from './runtimeConfig.js'

describe('Workbench runtime URL', () => {
  it('uses a deployment-safe same-origin path when no URL is configured', () => {
    expect(resolveWorkbenchUrl()).toBe('/workbench/')
  })

  it('accepts explicit relative and HTTPS deployment targets', () => {
    expect(resolveWorkbenchUrl('/staff/workbench/')).toBe('/staff/workbench/')
    expect(resolveWorkbenchUrl('https://staff.northwind.example/workbench/'))
      .toBe('https://staff.northwind.example/workbench/')
  })

  it('rejects protocol-relative and executable URL schemes', () => {
    expect(resolveWorkbenchUrl('//malicious.example/workbench/')).toBe('/workbench/')
    expect(resolveWorkbenchUrl('javascript:alert(1)')).toBe('/workbench/')
  })
})

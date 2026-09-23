import { describe, expect, it } from 'vitest'

import { maskPolicyNumber } from './policyNumber.js'

describe('maskPolicyNumber', () => {
  it.each([
    ['7', '••••'],
    ['1234', '••••'],
    [' 12 34 ', '••••'],
    ['NTH-1234', '••••1234'],
  ])('conceals the API-valid value %j', (value, expected) => {
    expect(maskPolicyNumber(value)).toBe(expected)
  })

  it('keeps an absent value distinct from a concealed value', () => {
    expect(maskPolicyNumber('   ')).toBe('Not provided')
  })
})

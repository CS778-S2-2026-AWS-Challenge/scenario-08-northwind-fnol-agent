import { describe, expect, it } from 'vitest'
import { assertWorkbenchFixtureContract } from './browser-acceptance-fixture.js'

function fixtureWith({ priority = 'high', missingAttention = 'required_now', riskAttention = 'review_required' } = {}) {
  return {
    priority_projection: { level: priority },
    work_summary: {
      missing_information: [{ attention: missingAttention }],
      risk_signals: [{ attention_level: riskAttention }],
    },
  }
}

describe('browser acceptance fixture contract', () => {
  it('accepts canonical Workbench projection enum values', () => {
    expect(assertWorkbenchFixtureContract(fixtureWith())).toEqual(fixtureWith())
  })

  it.each([
    ['priority projection', { priority: 'elevated' }, 'priority_projection.level'],
    ['missing-information attention', { missingAttention: 'blocking' }, 'missing_information[0].attention'],
    ['risk attention', { riskAttention: 'review' }, 'risk_signals[0].attention_level'],
  ])('rejects invented %s values', (_label, overrides, field) => {
    expect(() => assertWorkbenchFixtureContract(fixtureWith(overrides))).toThrow(field)
  })
})

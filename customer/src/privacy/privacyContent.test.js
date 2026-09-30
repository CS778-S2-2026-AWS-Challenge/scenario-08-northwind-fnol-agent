import { describe, expect, it } from 'vitest'
import {
  privacyContent,
  productPrivacySections,
  readPrivacyConfiguration,
  requiredProductionConfiguration,
  TO_BE_CONFIRMED,
  unresolvedPrivacyConfiguration,
} from './privacyContent.js'

describe('privacy content configuration', () => {
  it('keeps every release dependency unresolved and renders the approved placeholder', () => {
    expect(unresolvedPrivacyConfiguration()).toEqual(requiredProductionConfiguration)
    requiredProductionConfiguration.forEach((path) => {
      expect(readPrivacyConfiguration(path)).toBe(TO_BE_CONFIRMED)
    })
    expect(privacyContent.lastUpdated.prototype).toBe('29 September 2026')
    expect(privacyContent.lastUpdated.production).toBeNull()
  })

  it('contains the complete approved product-specific lists', () => {
    expect(privacyContent.motor.items).toHaveLength(13)
    expect(privacyContent.homeContents.items).toHaveLength(13)
    expect(privacyContent.motor.items).toContain(
      'Telematics, GPS or connected-vehicle information only where it is relevant, lawfully available and clearly disclosed.',
    )
    expect(privacyContent.homeContents.items).toContain(
      'Information needed to arrange repairs, replacement items, emergency work or settlement.',
    )
  })

  it('orders only the current claim family first and otherwise gives both equal prominence', () => {
    expect(productPrivacySections('motor').map(({ id, relevance }) => [id, relevance])).toEqual([
      ['information-collected-motor', 'current'],
      ['information-collected-home-contents', 'other'],
    ])
    expect(productPrivacySections('homeContents').map(({ id, relevance }) => [id, relevance])).toEqual([
      ['information-collected-home-contents', 'current'],
      ['information-collected-motor', 'other'],
    ])
    expect(productPrivacySections(null).map(({ id, relevance }) => [id, relevance])).toEqual([
      ['information-collected-motor', 'equal'],
      ['information-collected-home-contents', 'equal'],
    ])
  })
})

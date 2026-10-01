import { describe, expect, it } from 'vitest'

import { fieldValueText, reportedTimeText } from './claimFieldPresentation.js'

// 2026-10-01 17:40 in Auckland.
const NOW = new Date('2026-10-01T04:40:00Z')

describe('reported incident time', () => {
  it.each([
    ['2026-10-01T17:20+13:00', 'approximate', 'Today, about 5:20 pm'],
    ['2026-10-01T09:05+13:00', 'exact', 'Today, 9:05 am'],
    ['2026-09-30T23:00+13:00', 'exact', 'Yesterday, 11:00 pm'],
    ['2026-09-28T12:30+13:00', 'approximate', 'Mon 28 Sep, about 12:30 pm'],
    ['2026-10-01 morning', 'approximate', 'This morning'],
    ['2026-09-30 night', 'approximate', 'Last night'],
    ['2026-09-30 evening', 'approximate', 'Yesterday evening'],
    ['2026-09-30', 'exact', 'Yesterday'],
  ])('shows %s as %s', (value, precision, expected) => {
    expect(reportedTimeText(value, precision, NOW)).toBe(expected)
  })

  it('leaves other text alone', () => {
    expect(reportedTimeText('sometime last week', 'approximate', NOW)).toBeNull()
    expect(fieldValueText({ value: 'Queen Street', status: 'confirmed' })).toBe('Queen Street')
  })
})

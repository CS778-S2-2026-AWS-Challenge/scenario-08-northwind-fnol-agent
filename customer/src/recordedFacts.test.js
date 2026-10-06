import { describe, expect, it } from 'vitest'

import {
  choiceLabel,
  factCardsByAgentMessage,
  fieldDraftValue,
  fieldInputChoices,
  fieldInputValue,
  parseRegisteredNumber,
  fileReadings,
  notedProgress,
  progressLabel,
} from './recordedFacts.js'

const reply = (id, recorded = [], fileReads = []) => ({
  message_id: id,
  actor: 'agent',
  content: {
    type: 'text',
    text: 'Thanks.',
    turn_record: {
      recorded_facts: recorded.map((code) => ({ field_code: code })),
      file_reads: fileReads,
    },
  },
})

const field = (value, status = 'proposed') => ({ value, status })
const codes = (cards, id) => (cards.get(id) || []).map((fact) => fact.fieldCode)

describe('Just noted cards', () => {
  it('lists the facts each turn recorded, with their current value', () => {
    const messages = [
      { message_id: 'm1', actor: 'claimant' },
      reply('a1', ['incident.location']),
      { message_id: 'm2', actor: 'claimant' },
      reply('a2', ['incident.occurred_at']),
    ]
    const cards = factCardsByAgentMessage(messages, {
      'incident.location': field('Queen St'),
      'incident.occurred_at': field('8pm', 'confirmed'),
    })

    expect(codes(cards, 'a1')).toEqual(['incident.location'])
    expect(codes(cards, 'a2')).toEqual(['incident.occurred_at'])
    expect(cards.get('a2')[0].toCheck).toBe(false)
  })

  it('shows a field recorded twice only under the later reply', () => {
    const cards = factCardsByAgentMessage(
      [reply('a1', ['incident.location']), reply('a2', ['incident.location'])],
      { 'incident.location': field('Queen Street') },
    )

    expect(cards.has('a1')).toBe(false)
    expect(codes(cards, 'a2')).toEqual(['incident.location'])
    expect(cards.get('a2')[0].value).toBe('Queen Street')
  })

  it('omits a derived loss description that repeats the vehicle damage', () => {
    const form = {
      'vehicle.damage_description': field('The rear bumper is dented'),
      'loss.description': field('The rear bumper is dented'),
    }
    const cards = factCardsByAgentMessage(
      [reply('a1', ['vehicle.damage_description', 'loss.description'])],
      form,
    )

    expect(codes(cards, 'a1')).toEqual(['vehicle.damage_description'])

    form['loss.description'] = field('The rear bumper is dented and the tail light is cracked')
    const distinctCards = factCardsByAgentMessage(
      [reply('a1', ['vehicle.damage_description', 'loss.description'])],
      form,
    )
    expect(codes(distinctCards, 'a1')).toEqual(['vehicle.damage_description', 'loss.description'])
  })

  it('leaves out conflicting, empty and superseded facts, and replies with no record', () => {
    const cards = factCardsByAgentMessage(
      [
        reply('a1', ['incident.occurred_at', 'incident.description', 'incident.location']),
        { message_id: 'a0', actor: 'agent', content: { type: 'text', text: 'Hi' } },
      ],
      {
        'incident.occurred_at': field('Monday', 'disputed'),
        'incident.description': field(''),
        'incident.location': field('Queen St', 'superseded'),
      },
    )

    expect(cards.size).toBe(0)
  })
})

describe('file readings', () => {
  it('keeps the latest reading of each file', () => {
    const readings = fileReadings([
      reply('a1', [], [{ evidence_id: 'e1', kind: 'other_document' }]),
      reply('a2', [], [{ evidence_id: 'e1', kind: 'incident_photo' }]),
    ])

    expect(readings.get('e1')).toBe('incident_photo')
  })
})

describe('noted progress', () => {
  it('counts given details, checked or not, against the details this step needs', () => {
    const progress = notedProgress({
      requirements: {
        current_action_total: 7,
        missing_required_now: ['a', 'b'],
        by_state: { proposed: ['c', 'd'], disputed: [] },
      },
    })

    expect(progress).toEqual({ noted: 5, total: 7, toCheck: 2 })
    expect(progressLabel(progress)).toBe('5 of 7 noted · 2 to check')
    expect(progressLabel({ noted: 7, total: 7, toCheck: 0 })).toBe('7 of 7 noted')
    expect(notedProgress(null)).toBeNull()
  })

  it('names enum values in plain words', () => {
    expect(choiceLabel('other_party_accepts')).toBe('Other party accepts')
  })

  it('normalises correction drafts to registered field values', () => {
    expect(fieldDraftValue(false, { value_type: 'boolean' })).toBe('false')
    expect(fieldInputValue('false', { value_type: 'boolean' })).toBe(false)
    expect(fieldInputValue('wall, roof', { value_type: 'text_list' })).toEqual(['wall', 'roof'])
    expect(fieldInputValue('active_leak', {
      value_type: 'enum',
      allowed_values: ['none', 'active_leak'],
    })).toBe('active_leak')
    expect(fieldInputChoices({
      value_type: 'enum',
      allowed_values: ['active_leak'],
    })).toEqual([['active_leak', 'Active leak']])
  })

  it('accepts the registered non-negative amount format and rejects invalid numbers', () => {
    expect(parseRegisteredNumber('$1,850.50')).toBe(1850.5)
    expect(parseRegisteredNumber('NZ$1850')).toBe(1850)
    expect(fieldInputValue('0', { value_type: 'number' })).toBe(0)
    for (const draft of ['abc', '-1', 'Infinity', '1.234']) {
      expect(parseRegisteredNumber(draft)).toBeNull()
      expect(fieldInputValue(draft, { value_type: 'number' })).toBeNull()
    }
  })
})

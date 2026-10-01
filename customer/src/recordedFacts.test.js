import { describe, expect, it } from 'vitest'

import { choiceLabel, factCardsByAgentMessage, notedProgress, progressLabel } from './recordedFacts.js'

const messages = [
  { message_id: 'm1', actor: 'claimant' },
  { message_id: 'a1', actor: 'agent', in_reply_to: 'm1' },
  { message_id: 'm2', actor: 'claimant' },
  { message_id: 'a2-retry', actor: 'agent', in_reply_to: 'm2' },
  { message_id: 'a2', actor: 'agent', in_reply_to: 'm2' },
]

const said = (value, refs, status = 'proposed', assertionRefs = []) => ({
  value,
  status,
  source_refs: refs,
  assertions: assertionRefs.map((sourceRefs) => ({ source_refs: sourceRefs })),
})

const codes = (cards, id) => (cards.get(id) || []).map((fact) => fact.fieldCode)

describe('Just noted cards', () => {
  it('puts each fact under the reply to the message that last stated it', () => {
    const cards = factCardsByAgentMessage(messages, {
      'incident.location': said('Queen St', ['m1']),
      'incident.occurred_at': said('8pm', ['m2'], 'confirmed', [['m1'], ['m2']]),
    })

    expect(codes(cards, 'a1')).toEqual(['incident.location'])
    expect(codes(cards, 'a2')).toEqual(['incident.occurred_at'])
    expect(cards.has('a2-retry')).toBe(false)
    expect(cards.get('a2')[0].toCheck).toBe(false)
  })

  it('keeps a corrected fact on its original card', () => {
    const cards = factCardsByAgentMessage(messages, {
      'vehicle.drivable': said(true, ['claim:c:revision:4:field:vehicle.drivable'], 'confirmed', [['m1']]),
    })

    expect(codes(cards, 'a1')).toEqual(['vehicle.drivable'])
  })

  it('keeps a fact where its value was stated when a later "yes" or repeat adds sources', () => {
    const cards = factCardsByAgentMessage(messages, {
      'incident.location': {
        value: 'Queen St',
        status: 'confirmed',
        source_refs: ['m1', 'm2'],
        current_assertion_id: 'as1',
        assertions: [
          { assertion_id: 'as1', source_refs: ['m1'] },
          { assertion_id: 'as2', source_refs: ['m2'] },
        ],
      },
    })

    expect(codes(cards, 'a1')).toEqual(['incident.location'])
    expect(cards.has('a2')).toBe(false)
  })

  it('leaves a fact with conflicting answers off the cards', () => {
    const cards = factCardsByAgentMessage(messages, {
      'incident.occurred_at': said('Monday', ['m1', 'm2'], 'disputed', [['m1'], ['m2']]),
    })

    expect(cards.size).toBe(0)
  })

  it('leaves out hidden, empty and unsourced fields', () => {
    const cards = factCardsByAgentMessage(messages, {
      'claimant.client_number': said('C-1', ['m1']),
      'incident.description': said('', ['m1']),
      'policy.number': said('P-1', ['policy:1']),
      'incident.location': { value: 'Queen St', status: 'superseded', source_refs: ['m1'] },
    })

    expect(cards.size).toBe(0)
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
})

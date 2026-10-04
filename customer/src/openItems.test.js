import { describe, expect, it } from 'vitest'

import {
  claimantOwedItems,
  openItemGroups,
  openItemStatusText,
  openItemsBarText,
  receiptText,
  receiptsByMessage,
} from './openItems.js'

const quote = {
  item_id: 'evd_1',
  kind: 'document',
  owner: 'claimant',
  state: 'open',
  subject: 'repair_quote',
  opened_in_message_id: 'a1',
}
const hireCar = {
  item_id: 'nwq_1',
  kind: 'question',
  owner: 'northwind',
  state: 'open',
  subject: 'Is my hire car covered?',
  opened_in_message_id: 'a2',
}

describe('open items', () => {
  it('words what the claimant still owes and what Northwind is answering', () => {
    expect(openItemsBarText([quote, hireCar])).toBe(
      'Still to send: Repair quote · Waiting on Northwind: Is my hire car covered?',
    )
    expect(openItemsBarText([{ ...quote, state: 'done' }])).toBeNull()
    expect(claimantOwedItems([quote, hireCar])).toEqual([quote])
  })

  it('groups items by who owes them', () => {
    const groups = openItemGroups([quote, hireCar])
    expect(groups.map((group) => group.key)).toEqual(['claimant', 'northwind'])
  })

  it('puts a receipt under the reply that opened each item', () => {
    const receipts = receiptsByMessage([quote, hireCar])
    expect(receipts.get('a1')).toEqual([quote])
    expect(receiptText(quote)).toBe('To do: Repair quote')
    expect(receiptText(hireCar)).toBe('For the claims team: Is my hire car covered?')
    expect(receiptText({ ...hireCar, state: 'done', answer: 'Yes, up to 14 days.' })).toBe(
      'Northwind answered: Yes, up to 14 days.',
    )
  })
})

describe('waiting-list items', () => {
  it('words questions and contact requests for after submission', () => {
    const question = { item_id: 'q', kind: 'question', owner: 'northwind', state: 'open', subject: 'Will you pay for a hire car?' }
    const contact = { item_id: 'c', kind: 'contact_request', owner: 'northwind', state: 'open', subject: 'Please call me' }
    expect(openItemStatusText(question)).toBe('The claims team will answer after you submit')
    expect(openItemStatusText(contact)).toBe('The claims team will contact you after you submit')
    expect(receiptText(contact)).toBe('For the claims team: Please call me')
    expect(receiptText({ ...question, state: 'declined', answer: 'We will explain on the phone.' }))
      .toBe('Northwind replied: We will explain on the phone.')
    expect(receiptText({ ...contact, state: 'done' })).toBe('Northwind contacted you: Please call me')
    expect(openItemStatusText({ ...contact, state: 'done' })).toBe('Northwind contacted you')
  })
})

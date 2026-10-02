import { describe, expect, it } from 'vitest'

import {
  claimantOwedItems,
  openItemGroups,
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
    expect(receiptText(quote)).toBe('Added to your to-do: Repair quote')
    expect(receiptText(hireCar)).toBe('Passed to the claims team: Is my hire car covered?')
    expect(receiptText({ ...hireCar, state: 'done', answer: 'Yes, up to 14 days.' })).toBe(
      'Northwind answered: Yes, up to 14 days.',
    )
  })
})

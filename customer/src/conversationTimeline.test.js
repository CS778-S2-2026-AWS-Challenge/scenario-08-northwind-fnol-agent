import { describe, expect, it } from 'vitest'

import { buildConversationTimeline, mergeMessagesById, orderMessages } from './conversationTimeline.js'

function message(message_id, created_at, extra = {}) {
  return { message_id, actor: 'claimant', created_at, content: { type: 'text', text: message_id }, ...extra }
}

const ids = (items) => items.map((item) => item.message_id)

function permutations(items) {
  if (items.length <= 1) return [items]
  return items.flatMap((item, index) => permutations([
    ...items.slice(0, index),
    ...items.slice(index + 1),
  ]).map((rest) => [item, ...rest]))
}

describe('orderMessages', () => {
  it('orders independent messages newest-last by created_at, then message_id for equal times', () => {
    const early = message('msg_b', '2026-09-22T01:00:00Z')
    const tieLow = message('msg_c', '2026-09-22T01:00:05Z')
    const tieHigh = message('msg_d', '2026-09-22T01:00:05Z')
    const late = message('msg_a', '2026-09-22T01:00:09Z')

    for (const input of permutations([late, tieHigh, early, tieLow])) {
      expect(ids(orderMessages(input))).toEqual(['msg_b', 'msg_c', 'msg_d', 'msg_a'])
    }
  })

  it('places a reply after its persisted target even when its timestamp or identifier sorts earlier', () => {
    const target = message('msg_z_target', '2026-09-22T01:00:05Z')
    const reply = message('msg_a_reply', '2026-09-22T01:00:04Z', { actor: 'agent', in_reply_to: 'msg_z_target' })
    const independent = message('msg_m', '2026-09-22T01:00:06Z')

    for (const input of permutations([reply, independent, target])) {
      expect(ids(orderMessages(input))).toEqual(['msg_z_target', 'msg_a_reply', 'msg_m'])
    }
  })

  it('keeps a reply to a message outside the list in timestamp order and never drops malformed cycles', () => {
    const orphanReply = message('msg_orphan', '2026-09-22T01:00:02Z', { in_reply_to: 'msg_elsewhere' })
    const cycleA = message('msg_cycle_a', '2026-09-22T01:00:03Z', { in_reply_to: 'msg_cycle_b' })
    const cycleB = message('msg_cycle_b', '2026-09-22T01:00:01Z', { in_reply_to: 'msg_cycle_a' })

    expect(ids(orderMessages([cycleA, orphanReply, cycleB])))
      .toEqual(['msg_orphan', 'msg_cycle_b', 'msg_cycle_a'])
  })
})

describe('mergeMessagesById', () => {
  it('places a late-arriving earlier message by order instead of appending it', () => {
    const current = [
      message('msg_agent_old', '2026-09-22T01:00:10Z', { actor: 'agent' }),
    ]
    const merged = mergeMessagesById(current, [message('msg_hi', '2026-09-22T01:00:05Z')])
    expect(ids(merged)).toEqual(['msg_hi', 'msg_agent_old'])
  })

  it('replaces an existing record in place and never duplicates it', () => {
    const original = message('msg_hi', '2026-09-22T01:00:05Z', { recovery: { rule_id: 'x' } })
    const later = message('msg_later', '2026-09-22T01:00:09Z')
    const delivered = message('msg_hi', '2026-09-22T01:00:05Z')

    const merged = mergeMessagesById([original, later], [delivered])
    expect(ids(merged)).toEqual(['msg_hi', 'msg_later'])
    expect(merged[0]).toBe(delivered)
  })

  it('produces the same order whatever order submission and readback results arrive in', () => {
    const hi = message('msg_hi', '2026-09-22T01:00:05Z')
    const reply = message('msg_reply', '2026-09-22T01:00:06Z', { actor: 'agent', in_reply_to: 'msg_hi' })
    const staff = message('msg_staff', '2026-09-22T01:00:06Z', { actor: 'staff' })
    const batches = [[hi, reply], [staff], [hi]]

    for (const order of permutations(batches)) {
      const merged = order.reduce((current, batch) => mergeMessagesById(current, batch), [])
      expect(ids(merged)).toEqual(['msg_hi', 'msg_reply', 'msg_staff'])
    }
  })
})

describe('buildConversationTimeline', () => {
  const resumeContext = {
    resumed_at: '2026-09-16T01:06:00Z',
    resumed_after_message_id: 'msg_before_2',
    has_resume_boundary: true,
  }
  const kinds = (timeline) => timeline.map((item) => (item.kind === 'message' ? item.message.message_id : item.title))

  it('keeps messages at or before the resume anchor above Claim resumed and later ones below it', () => {
    const messages = orderMessages([
      message('msg_before_1', '2026-09-16T01:00:00Z'),
      message('msg_before_2', '2026-09-16T01:01:00Z', { actor: 'agent' }),
      message('msg_after', '2026-09-16T01:07:00Z'),
    ])
    expect(kinds(buildConversationTimeline(messages, resumeContext)))
      .toEqual(['msg_before_1', 'msg_before_2', 'Claim resumed', 'msg_after'])
  })

  it('keeps a message accepted before the anchor above Claim resumed when it arrives after the resume readback', () => {
    const afterResumeReadback = mergeMessagesById(
      [message('msg_before_2', '2026-09-16T01:01:00Z', { actor: 'agent' })],
      [message('msg_hi', '2026-09-16T01:00:30Z')],
    )
    expect(kinds(buildConversationTimeline(afterResumeReadback, resumeContext)))
      .toEqual(['msg_hi', 'msg_before_2', 'Claim resumed'])
  })
})

// Client copy of the Message API ordering rule (docs/api.md "Message lists use persisted
// in_reply_to edges..."; backend/domain/message.py::order_messages): a reply follows its
// target, and independent messages are newest-last by (created_at, message_id). Applying it
// on every commit keeps the conversation independent of which request finished first.

function timestamp(message) {
  const value = Date.parse(message.created_at || '')
  return Number.isFinite(value) ? value : Number.POSITIVE_INFINITY
}

function compareMessages(left, right) {
  const byTime = timestamp(left) - timestamp(right)
  if (byTime !== 0 && !Number.isNaN(byTime)) return byTime
  if (left.message_id === right.message_id) return 0
  return left.message_id < right.message_id ? -1 : 1
}

export function orderMessages(messages) {
  const byId = new Map(messages.map((message) => [message.message_id, message]))
  const replies = new Map()
  const waiting = new Map(messages.map((message) => [message.message_id, 0]))
  for (const message of messages) {
    const target = message.in_reply_to
    if (!target || target === message.message_id || !byId.has(target)) continue
    replies.set(target, [...(replies.get(target) || []), message])
    waiting.set(message.message_id, waiting.get(message.message_id) + 1)
  }

  const ordered = []
  const available = messages.filter((message) => waiting.get(message.message_id) === 0)
  while (available.length) {
    available.sort(compareMessages)
    const next = available.shift()
    ordered.push(next)
    for (const reply of replies.get(next.message_id) || []) {
      waiting.set(reply.message_id, waiting.get(reply.message_id) - 1)
      if (waiting.get(reply.message_id) === 0) available.push(reply)
    }
  }

  // Persisted validation rejects reply cycles; keep malformed data visible and deterministic
  // rather than dropping it, as the server does.
  const placed = new Set(ordered.map((message) => message.message_id))
  return [
    ...ordered,
    ...messages.filter((message) => !placed.has(message.message_id)).sort(compareMessages),
  ]
}

export function mergeMessagesById(current, incoming) {
  const merged = new Map(current.map((message) => [message.message_id, message]))
  for (const message of incoming) {
    if (message?.message_id) merged.set(message.message_id, message)
  }
  return orderMessages([...merged.values()])
}

export function buildConversationTimeline(messages, resumeContext) {
  const timeline = messages.map((message) => ({
    key: message.message_id,
    kind: 'message',
    message,
  }))
  if (resumeContext) {
    // The anchor is the last message of the ordered resume readback. Resume may return the
    // existing active session, whose started_at predates its messages, so the anchor, not the
    // session time, is the boundary; ordering places late arrivals on the correct side of it.
    const boundaryMessageIndex = resumeContext.resumed_after_message_id
      ? timeline.findIndex((item) => item.message?.message_id === resumeContext.resumed_after_message_id)
      : -1
    const resumedAt = Date.parse(resumeContext.resumed_at || '')
    const firstMessageAfterResume = boundaryMessageIndex < 0 && Number.isFinite(resumedAt)
      ? timeline.findIndex((item) => (
          item.message && Date.parse(item.message.created_at || '') >= resumedAt
        ))
      : -1
    const insertAt = boundaryMessageIndex >= 0
      ? boundaryMessageIndex + 1
      : firstMessageAfterResume >= 0
        ? firstMessageAfterResume
        : resumeContext.has_resume_boundary
          ? 0
          : timeline.length
    timeline.splice(insertAt, 0, {
      key: `claim-resumed-${resumeContext.resumed_at || 'current'}`,
      kind: 'conversation-event',
      title: 'Claim resumed',
      detail: 'Continuing from your previous conversation',
    })
  }
  return timeline
}

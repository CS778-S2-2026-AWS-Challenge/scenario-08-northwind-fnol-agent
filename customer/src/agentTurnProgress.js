export const AGENT_TURN_STAGE_COPY = {
  'turn.accepted': 'Message received',
  'context.loading': 'Reviewing your claim details',
  'knowledge.querying': 'Checking relevant policy information',
  'tool.running': 'Retrieving the information you requested',
  'model.waiting': 'Preparing a response',
  'offer.preparing': 'Preparing available support options',
  'turn.validating': 'Checking the proposed update',
  'turn.committing': 'Saving your progress',
  'turn.completed': 'Completed',
  'turn.failed': 'Could not complete this request',
}

const TERMINAL_STAGES = new Set(['turn.completed', 'turn.failed'])

export function reduceTurnProgress(current, event, expectedTurnId) {
  if (!event || event.event_type !== 'agent.turn.progress') return current
  if (expectedTurnId && event.turn_id !== expectedTurnId) return current
  if (current && event.turn_id !== current.turnId) return current
  if (current && TERMINAL_STAGES.has(current.stage)) return current
  if (current && Number(event.ordinal) <= current.ordinal) return current
  const activity = {
    stage: event.stage,
    label: AGENT_TURN_STAGE_COPY[event.stage] || 'Working on your request',
  }
  const activities = current?.activities || []
  return {
    turnId: event.turn_id,
    stage: event.stage,
    state: event.state,
    ordinal: Number(event.ordinal),
    retryable: event.retryable ?? null,
    activities: activities.some((item) => item.stage === activity.stage)
      ? activities
      : [...activities, activity],
  }
}

export function completeTurnProgress(current, turnId) {
  const base = current?.turnId === turnId
    ? current
    : { turnId, ordinal: 0, activities: [] }
  return {
    ...base,
    stage: 'turn.completed',
    state: 'completed',
    activities: base.activities.filter((item) => !TERMINAL_STAGES.has(item.stage)),
  }
}

export function completedTurnSummary(progress) {
  const stages = new Set(progress?.activities?.map((item) => item.stage))
  if (stages.has('offer.preparing')) return 'Prepared available support options'
  if (stages.has('knowledge.querying')) return 'Checked relevant policy information'
  if (stages.has('tool.running')) return 'Retrieved requested claim information'
  return 'Reviewed information for this request'
}

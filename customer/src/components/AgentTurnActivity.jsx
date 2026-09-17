import { useId, useState } from 'react'

import {
  AGENT_TURN_STAGE_COPY,
  completedTurnSummary,
} from '../agentTurnProgress.js'

export function AgentTurnPlaceholder({ progress, turnId }) {
  const text = progress ? AGENT_TURN_STAGE_COPY[progress.stage] : 'Sending your message'
  return (
    <article
      className="msg-agent agent-turn-placeholder"
      aria-label="Claims assistant is working"
      data-turn-id={turnId}
    >
      <div className="agent-bar" />
      <div className="agent-body">
        <div className="agent-label">Claims assistant</div>
        <p className="agent-turn-current" role="status">
          <span className="agent-turn-pulse" aria-hidden="true" />
          {text}
        </p>
      </div>
    </article>
  )
}

export function AgentTurnDisclosure({ progress }) {
  const [expanded, setExpanded] = useState(false)
  const panelId = useId()
  if (!progress) return null
  return (
    <div className="agent-turn-activity">
      <button
        className="agent-turn-summary"
        type="button"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={() => setExpanded((current) => !current)}
      >
        <span>{completedTurnSummary(progress)}</span>
        <span className="agent-turn-chevron" aria-hidden="true">›</span>
      </button>
      <div id={panelId} className="agent-turn-details" hidden={!expanded}>
        <ol>
          {progress.activities.map((activity) => (
            <li key={activity.stage}>{activity.label}</li>
          ))}
        </ol>
      </div>
    </div>
  )
}

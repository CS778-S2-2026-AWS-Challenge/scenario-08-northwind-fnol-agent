const labels = {
  draft: 'Draft',
  validation: 'Validation',
  awaiting_approval: 'Awaiting approval',
  published: 'Published',
  withdrawn: 'Withdrawn',
  superseded: 'Superseded',
  indexed: 'Indexed',
  failed: 'Failed',
  succeeded: 'Succeeded',
  running: 'Running',
  queued: 'Queued',
  unavailable: 'Unavailable',
  using_fixture: 'Using fixture',
}

export default function StatusBadge({ value }) {
  const text = labels[value] || value || 'Unknown'
  return <span className={`status status-${value || 'unknown'}`}>{text}</span>
}

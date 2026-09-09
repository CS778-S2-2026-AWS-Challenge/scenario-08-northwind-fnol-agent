import { ChevronDown } from 'lucide-react'

const CATEGORY_LABELS = {
  claim_type: 'Claim type',
  incident: 'Incident',
  people_safety: 'People and safety',
  stakeholder: 'Stakeholders',
  impact: 'Impact',
  evidence: 'Evidence',
  progress: 'Progress',
  attention: 'Needs attention',
}

export function TagList({ tags = [], limit, grouped = false }) {
  if (!tags.length) return <p className="empty-note">No source-backed tags are available yet.</p>
  const visible = typeof limit === 'number' ? tags.slice(0, limit) : tags

  if (!grouped) {
    return (
      <div className="tag-list" aria-label="Claim tags">
        {visible.map((tag) => <Tag key={tag.tag_instance_id} tag={tag} />)}
        {visible.length < tags.length && <span className="tag-more">+{tags.length - visible.length} more</span>}
      </div>
    )
  }

  const groups = Object.entries(
    visible.reduce((result, tag) => {
      result[tag.category] ||= []
      result[tag.category].push(tag)
      return result
    }, {}),
  )
  return (
    <div className="tag-groups">
      {groups.map(([category, values]) => (
        <section className="tag-group" key={category}>
          <h4>{CATEGORY_LABELS[category] || category}</h4>
          <div className="tag-list">
            {values.map((tag) => <Tag key={tag.tag_instance_id} tag={tag} expanded />)}
          </div>
        </section>
      ))}
    </div>
  )
}

function Tag({ tag, expanded = false }) {
  return (
    <details className={`tag-disclosure tag-disclosure--${tag.category}`} open={expanded}>
      <summary className={`tag tag--${tag.category}`}>
        <span>{tag.label}</span>
        {tag.attention_level && <span className="tag__attention">{tag.attention_level}</span>}
        <ChevronDown className="tag__chevron" size={13} aria-hidden="true" />
      </summary>
      <div className="tag-details">
        <p>{tag.description}</p>
        <dl>
          <div><dt>Basis</dt><dd>{tag.basis}</dd></div>
          <div><dt>Source actor</dt><dd>{tag.source_actor || 'system'}</dd></div>
          <div><dt>Freshness</dt><dd>{tag.freshness || 'current'}</dd></div>
          <div><dt>Status</dt><dd>{tag.status}</dd></div>
          {tag.attention_level && <div><dt>Attention</dt><dd>{tag.attention_level}</dd></div>}
          <div><dt>Activated</dt><dd>{tag.activated_at}</dd></div>
          <div><dt>Sources</dt><dd>{tag.source_refs.join(', ')}</dd></div>
        </dl>
      </div>
    </details>
  )
}

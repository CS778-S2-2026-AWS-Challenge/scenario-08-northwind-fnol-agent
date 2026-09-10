import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TagList } from './TagList.jsx'

const backendTag = {
  tag_instance_id: 'clm_1:impact.vehicle_not_drivable',
  code: 'impact.vehicle_not_drivable',
  registry_version: '0.3',
  label: 'Vehicle not drivable',
  description: 'Summarises the reported practical impact.',
  category: 'impact',
  status: 'active',
  visibility: 'staff_only',
  basis: 'reported',
  source_actor: 'claimant',
  freshness: 'current',
  projection_mode: 'deterministic',
  attention_level: null,
  source_refs: ['field:vehicle.drivable'],
  activated_at: '2026-09-03T01:00:00Z',
  display_weight: 30,
}

describe('TagList', () => {
  it('renders the backend-projected staff label and preserves source context', () => {
    render(<TagList tags={[backendTag]} grouped />)

    expect(screen.getByText('Vehicle not drivable')).toBeInTheDocument()
    expect(screen.queryByText('impact.vehicle_not_drivable')).not.toBeInTheDocument()
    expect(screen.getByText('Basis')).toBeInTheDocument()
    expect(screen.getByText('claimant')).toBeInTheDocument()
    expect(screen.getByText('field:vehicle.drivable')).toBeInTheDocument()
  })

  it('does not create a tag when the backend projection is empty', () => {
    render(<TagList tags={[]} />)

    expect(screen.getByText('No source-backed tags are available yet.')).toBeInTheDocument()
  })
})

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import ReferenceRecords from './ReferenceRecords.jsx'

const policy = {
  retrieval_id: 'ret_policy_1',
  claim_id: 'clm_1',
  kind: 'policy',
  source: { system: 'policy-fixture', reference: 'POL-1042', retrieved_at: '2026-09-03T01:00:00Z' },
  facts: { policy_reference: 'POL-1042', product: 'Motor', status: 'active', coverage_sections: ['vehicle damage'] },
  uncertainty: [],
}

const history = {
  retrieval_id: 'ret_history_1',
  claim_id: 'clm_1',
  kind: 'claim_history',
  source: { system: 'claims-history-fixture', reference: 'HIS-1042', retrieved_at: '2026-09-03T01:05:00Z' },
  facts: { history_reference: 'HIS-1042', incident_type: 'motor', status: 'open' },
  uncertainty: [{ code: 'stale_record', detail: 'The previous outcome has not been reconciled.' }],
}

describe('ReferenceRecords', () => {
  it('keeps policy and history separate and reveals provenance on demand', async () => {
    const user = userEvent.setup()
    render(<ReferenceRecords records={[policy, history]} />)

    expect(screen.getByText('Policy records')).toBeInTheDocument()
    expect(screen.getByText('Claim history')).toBeInTheDocument()
    expect(screen.queryByText('Coverage sections')).not.toBeInTheDocument()

    await user.click(screen.getAllByText('POL-1042')[0])
    const openPolicy = document.querySelector('details[open]')
    expect(openPolicy).not.toBeNull()
    expect(within(openPolicy).getByText('Retrieved')).toBeVisible()
    expect(within(openPolicy).getByText('Active')).toBeVisible()

    await user.click(screen.getAllByText('HIS-1042')[0])
    expect(screen.getByText('Uncertainty requiring judgement')).toBeVisible()
    expect(screen.getByText('The previous outcome has not been reconciled.')).toBeVisible()
  })
})

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import EvidenceRecords from './EvidenceRecords.jsx'

const evidence = {
  evidence_id: 'evd_1',
  kind: 'incident_photo',
  original_filename: 'rear-damage.png',
  media_type: 'image/png',
  status: 'received',
  file_status: 'ready',
  source: 'claimant',
  responsible_party: 'claimant',
  needed_for: ['assessment'],
  related_fields: ['vehicle.damage'],
  updated_at: '2026-09-03T01:00:00Z',
}

describe('EvidenceRecords', () => {
  it('loads protected evidence only after an explicit staff action', async () => {
    const onLoadEvidence = vi.fn().mockResolvedValue({
      filename: 'rear-damage.png',
      media_type: 'image/png',
      base64_data: 'cG5n',
    })
    const user = userEvent.setup()
    render(<EvidenceRecords claimId="clm_1" records={[evidence]} onLoadEvidence={onLoadEvidence} />)

    expect(onLoadEvidence).not.toHaveBeenCalled()
    await user.click(screen.getByText('rear-damage.png'))
    await user.click(screen.getByRole('button', { name: 'View file' }))

    expect(onLoadEvidence).toHaveBeenCalledWith('evd_1')
    expect(await screen.findByAltText('Evidence preview: rear-damage.png')).toHaveAttribute(
      'src',
      'data:image/png;base64,cG5n',
    )
  })

  it('does not offer a file viewer for pending documentary evidence', async () => {
    const user = userEvent.setup()
    const onLoadEvidence = vi.fn()
    render(<EvidenceRecords claimId="clm_1" records={[{ ...evidence, media_type: null, file_status: 'not_available' }]} onLoadEvidence={onLoadEvidence} />)

    await user.click(screen.getByText('rear-damage.png'))
    expect(screen.getByRole('button', { name: 'View file' })).toBeDisabled()
    expect(screen.getByText('No uploaded file is available for this evidence record.')).toBeVisible()
  })
})

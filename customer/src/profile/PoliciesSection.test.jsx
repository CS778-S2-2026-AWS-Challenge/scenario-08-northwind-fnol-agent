import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import PoliciesSection from './PoliciesSection.jsx'

const motorPolicy = {
  policy_id: 'pol_11111111111111111111',
  policy_number: 'MOTOR-1234',
  revision: 1,
}

const homePolicy = {
  policy_id: 'pol_22222222222222222222',
  policy_number: 'HOME-5678',
  revision: 2,
}

function PoliciesHarness({ initialPolicies = [], onCreate = vi.fn(), onUpdate = vi.fn() }) {
  const [policies, setPolicies] = useState(initialPolicies)
  return (
    <PoliciesSection
      resource={{ items: policies, error: '', loading: false, stale: false }}
      pending={{}}
      onBeginCreate={() => 'policy-attempt-1'}
      onAbandonCreate={vi.fn()}
      onCreate={async (request) => {
        const saved = await onCreate(request)
        setPolicies((current) => [saved, ...current])
        return saved
      }}
      onReload={vi.fn()}
      onUpdate={async (...args) => {
        const saved = await onUpdate(...args)
        setPolicies((current) => current.map((policy) => policy.policy_id === saved.policy_id ? saved : policy))
        return saved
      }}
    />
  )
}

describe('PoliciesSection', () => {
  it('lists multiple policy numbers and updates the selected record with its revision', async () => {
    const user = userEvent.setup()
    const updated = { ...homePolicy, policy_number: 'CONTENTS-9012', revision: 3 }
    const onUpdate = vi.fn().mockResolvedValue(updated)
    render(<PoliciesHarness initialPolicies={[motorPolicy, homePolicy]} onUpdate={onUpdate} />)

    expect(screen.getByText('••••1234')).toBeInTheDocument()
    expect(screen.getByText('••••5678')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Edit policy number ••••5678' }))
    expect(screen.getByLabelText('Policy number')).toHaveFocus()
    expect(screen.getByLabelText('Policy number')).toHaveValue('HOME-5678')
    await user.clear(screen.getByLabelText('Policy number'))
    await user.type(screen.getByLabelText('Policy number'), 'CONTENTS-9012')
    await user.click(screen.getByRole('button', { name: 'Save policy number' }))

    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(homePolicy.policy_id, 2, 'CONTENTS-9012'))
    expect(await screen.findByText('••••9012')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit policy number ••••9012' })).toHaveFocus()
  })

  it('adds another policy with one stable create attempt', async () => {
    const user = userEvent.setup()
    const onCreate = vi.fn().mockResolvedValue(homePolicy)
    render(<PoliciesHarness initialPolicies={[motorPolicy]} onCreate={onCreate} />)

    await user.click(screen.getByRole('button', { name: 'Add policy number' }))
    expect(screen.getByLabelText('Policy number')).toHaveFocus()
    await user.type(screen.getByLabelText('Policy number'), 'HOME-5678')
    await user.click(screen.getByRole('button', { name: 'Save policy number' }))

    await waitFor(() => expect(onCreate).toHaveBeenCalledWith({
      policyNumber: 'HOME-5678',
      attemptId: 'policy-attempt-1',
    }))
    expect(await screen.findByText('••••5678')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Edit policy number/ })).toHaveLength(2)
  })
})

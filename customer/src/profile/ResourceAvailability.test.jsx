import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import IdentityDocuments from '../components/IdentityDocuments.jsx'
import PaymentDetailsSection from './PaymentDetailsSection.jsx'
import PoliciesSection from './PoliciesSection.jsx'

const policy = {
  policy_id: 'pol_11111111111111111111',
  policy_number: 'NTH-1234',
  revision: 1,
}

const identity = {
  identity_id: 'idn_11111111111111111111',
  document_type: 'driver_licence',
  masked_document_number: '****1234',
  revision: 1,
}

const payment = {
  payment_destination_id: 'pay_11111111111111111111',
  account_type: 'everyday',
  masked_account_number: '•••• 4321',
  revision: 1,
}

const commonProps = {
  pending: {},
  onBeginCreate: vi.fn(),
  onAbandonCreate: vi.fn(),
  onCreate: vi.fn(),
  onReload: vi.fn(),
  onUpdate: vi.fn(),
}

const resourceCases = [
  {
    label: 'Policies',
    records: [policy],
    emptyText: 'No policy numbers saved.',
    retainedText: '••••1234',
    renderSection: (resource) => render(<PoliciesSection {...commonProps} resource={resource} />),
    assertNoMutationControls: () => {
      expect(screen.queryByRole('button', { name: 'Add policy number' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Edit policy number/ })).not.toBeInTheDocument()
    },
  },
  {
    label: 'Identity',
    records: [identity],
    emptyText: 'No identity documents saved.',
    retainedText: '****1234',
    renderSection: (resource) => render(<IdentityDocuments {...commonProps} resource={resource} />),
    assertNoMutationControls: () => {
      expect(screen.queryByRole('button', { name: 'Add identity document' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Edit Driver licence/ })).not.toBeInTheDocument()
    },
  },
  {
    label: 'Payment',
    records: [payment],
    emptyText: 'No payment details saved.',
    retainedText: '•••• 4321',
    renderSection: (resource) => render(<PaymentDetailsSection {...commonProps} resource={resource} />),
    assertNoMutationControls: () => {
      expect(screen.queryByText('Saved accounts')).not.toBeInTheDocument()
    },
  },
]

describe.each(resourceCases)('$label resource availability', ({ assertNoMutationControls, emptyText, records, renderSection, retainedText }) => {
  it('does not present an initial load failure as a confirmed empty result', () => {
    renderSection({
      items: null,
      error: 'Northwind could not load this saved information.',
      loading: false,
      stale: false,
    })

    expect(screen.getByRole('alert')).toHaveTextContent('could not load')
    expect(screen.queryByText(emptyText)).not.toBeInTheDocument()
    assertNoMutationControls()
  })

  it('labels retained records stale and withholds current-data controls after a failed reload', () => {
    renderSection({
      items: records,
      error: 'Northwind could not refresh this saved information.',
      loading: false,
      stale: true,
    })

    expect(screen.getByRole('alert')).toHaveTextContent(/previously loaded .* may be out of date/i)
    expect(screen.getByText(retainedText)).toBeInTheDocument()
    expect(screen.queryByText(emptyText)).not.toBeInTheDocument()
    if (records.length > 0 && emptyText === 'No payment details saved.') {
      expect(screen.getByText('Saved accounts').nextSibling).toHaveTextContent('1')
    } else {
      assertNoMutationControls()
    }
  })
})

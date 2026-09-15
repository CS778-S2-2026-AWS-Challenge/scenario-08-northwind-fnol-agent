import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ExternalServiceRecords, { ExternalServiceSummary } from './ExternalServiceRecords.jsx'

const request = {
  task: {
    task_id: 'tsk_1',
    claim_id: 'clm_1',
    service_identity: 'vehicle damage assessor',
    requested_action: 'vehicle damage assessment',
    integration_source: 'fixture',
    status: 'unknown_outcome',
    delivery: 'submitted',
    delivery_evidence: 'provider-receipt-1',
    failure_code: 'timeout',
    provider_reference: 'provider-acknowledgement-1',
    created_at: '2026-09-03T01:00:00Z',
    updated_at: '2026-09-03T01:10:00Z',
  },
  request: {
    task_id: 'tsk_1',
    claim_id: 'clm_1',
    purpose: 'Assess the vehicle damage.',
    disclosed_fields: ['claim_id', 'location.region'],
    authorisation: {
      northwind_authority_ref: 'AUTH-1',
      claimant_consent_ref: 'CONSENT-1',
      authorised_revision: 4,
    },
    prepared_at: '2026-09-03T00:59:00Z',
    sent_at: '2026-09-03T01:00:00Z',
    operation_id: 'op_1',
  },
  lifecycle: {
    stakeholder: 'external_party',
    service: 'vehicle damage assessor',
    request_type: 'vehicle damage assessment',
    authority_state: 'recorded',
    consent_state: 'recorded',
    delivery_state: 'submitted',
    verification_state: 'reconciliation_required',
    pending_owner: 'claims_professional',
    status_label: 'Outcome not confirmed',
    status_detail: 'Submission may have occurred; the result remains unknown.',
    provider_reference: 'provider-acknowledgement-1',
    result: null,
    result_source: null,
    result_verification_state: null,
    result_received_at: null,
    result_verified_at: null,
    result_verified_against_revision: null,
    result_evidence_ids: [],
    result_evidence: [],
    limitation: 'Synthetic fixture record; no production provider completion is verified.',
    next_action: 'Reconcile by operation or provider reference before any retry.',
    needs_attention: true,
  },
}

describe('ExternalServiceRecords', () => {
  it('shows authority and requires reconciliation for an unknown outcome', async () => {
    const user = userEvent.setup()
    render(<ExternalServiceRecords records={[request]} />)

    await user.click(screen.getByText('Vehicle Damage Assessor'))
    expect(screen.getByText('Recorded · consent Recorded')).toBeVisible()
    expect(screen.getAllByText('Reconcile by operation or provider reference before any retry.')[0]).toBeVisible()
    expect(screen.getByText('AUTH-1')).toBeVisible()
    expect(screen.getByText('CONSENT-1')).toBeVisible()
    expect(screen.getByText('Submission')).toBeVisible()
    expect(screen.getByText('Submitted')).toBeVisible()
    expect(screen.getByText(/Synthetic fixture record; no production provider completion is verified/)).toBeVisible()
  })

  it('states when no request has been prepared', async () => {
    const user = userEvent.setup()
    render(<ExternalServiceRecords records={[{ ...request, request: null, task: { ...request.task, status: 'prepared', delivery: 'not_submitted', failure_code: null }, lifecycle: { ...request.lifecycle, authority_state: 'not_recorded', consent_state: 'not_recorded', delivery_state: 'not_submitted', verification_state: 'not_started', status_label: 'Pending', status_detail: 'The request is prepared and has not been submitted.', next_action: 'Review the projected request before submission.', needs_attention: false } }]} />)

    await user.click(screen.getByText('Vehicle Damage Assessor'))
    expect(screen.getByText('Request details have not been prepared.')).toBeVisible()
    expect(screen.getByText('No disclosure manifest recorded')).toBeVisible()
  })

  it('does not infer completion from an accepted fixture task', () => {
    render(<ExternalServiceSummary resource={{
      status: 'available',
      items: [{ ...request, task: { ...request.task, status: 'accepted', failure_code: null }, lifecycle: { ...request.lifecycle, status_label: 'Completion not confirmed', status_detail: 'The provider acknowledged the request; no verified completed result is recorded.', verification_state: 'pending_verification', pending_owner: 'external_party', needs_attention: false } }],
    }} />)

    expect(screen.getByText(/Completion not confirmed/)).toBeInTheDocument()
    expect(screen.getByText(/Synthetic fixture record; no production provider completion is verified/)).toBeInTheDocument()
    expect(screen.queryByText(/complete$/i)).not.toBeInTheDocument()
  })

  it('shows an accepted provider acknowledgement separately from an absent result', async () => {
    const user = userEvent.setup()
    render(<ExternalServiceRecords records={[{
      ...request,
      task: { ...request.task, status: 'accepted', failure_code: null },
      lifecycle: { ...request.lifecycle, status_label: 'Completion not confirmed', verification_state: 'pending_verification', pending_owner: 'external_party', needs_attention: false },
    }]} />)

    await user.click(screen.getByText('Vehicle Damage Assessor'))
    expect(screen.getByText('provider-acknowledgement-1')).toBeVisible()
    expect(screen.getByText('No verified result recorded')).toBeVisible()
    expect(screen.getByText('No result to verify')).toBeVisible()
  })

  it('shows an unverified returned result with provenance and evidence status', async () => {
    const user = userEvent.setup()
    render(<ExternalServiceRecords records={[{
      ...request,
      task: { ...request.task, status: 'accepted', failure_code: null },
      lifecycle: {
        ...request.lifecycle,
        status_label: 'Result awaiting verification',
        status_detail: 'A provider result is recorded but has not been checked against the Claim.',
        verification_state: 'unverified',
        pending_owner: 'claims_professional',
        result: 'The assessor returned a repairability report.',
        result_source: { system: 'controlled_assessment_fixture', reference: 'report/assessment-002', retrieved_at: '2026-09-03T01:11:00Z' },
        result_verification_state: 'unverified',
        result_received_at: '2026-09-03T01:11:00Z',
        result_evidence_ids: ['evd_1'],
        result_evidence: [{ evidence_id: 'evd_1', status: 'received', file_status: 'ready' }],
        next_action: 'Verify the returned result against its evidence and the current Claim.',
      },
    }]} />)

    await user.click(screen.getByText('Vehicle Damage Assessor'))
    expect(screen.getByText('The assessor returned a repairability report.')).toBeVisible()
    expect(screen.getByText('Controlled Assessment Fixture · report/assessment-002')).toBeVisible()
    expect(screen.getAllByText('Unverified')).toHaveLength(2)
    expect(screen.getByText('evd_1 — Received / Ready')).toBeVisible()
    expect(screen.getByText('Not verified')).toBeVisible()
  })

  it.each([
    ['review_required', 'Result requires review', 'Review Required'],
    ['inconsistent', 'Result conflicts with Claim', 'Inconsistent'],
  ])('shows a %s result as pending professional work', async (verification, label, verificationLabel) => {
    const user = userEvent.setup()
    render(<ExternalServiceRecords records={[{
      ...request,
      task: { ...request.task, status: 'accepted', failure_code: null },
      lifecycle: {
        ...request.lifecycle,
        status_label: label,
        verification_state: verification,
        result: 'The assessor returned a checked report.',
        result_source: { system: 'controlled_assessment_fixture', reference: 'report/checked', retrieved_at: '2026-09-03T01:11:00Z' },
        result_verification_state: verification,
        result_received_at: '2026-09-03T01:11:00Z',
        result_verified_at: '2026-09-03T01:12:00Z',
        result_verified_against_revision: 4,
        next_action: 'Review the returned result before continuing.',
        needs_attention: true,
      },
    }]} />)

    await user.click(screen.getByText('Vehicle Damage Assessor'))
    expect(screen.getAllByText(verificationLabel)).toHaveLength(2)
    expect(screen.getByText('4')).toBeVisible()
    expect(screen.getByText('The assessor returned a checked report.')).toBeVisible()
  })

  it.each([
    ['prepared', 'Pending'],
    ['retryable_failure', 'Failed'],
    ['terminal_failure', 'Failed'],
    ['unknown_outcome', 'Outcome not confirmed'],
  ])('renders %s with truthful summary status %s', (status, label) => {
    render(<ExternalServiceSummary resource={{
      status: 'available',
      items: [{ ...request, task: { ...request.task, status }, lifecycle: { ...request.lifecycle, status_label: label } }],
    }} />)

    expect(screen.getByText(new RegExp(label))).toBeInTheDocument()
  })

  it('preserves unavailable and empty third-party states', () => {
    const { rerender } = render(<ExternalServiceSummary resource={{
      status: 'unavailable',
      limitation: 'External-service records are temporarily unavailable.',
      items: [],
    }} />)
    expect(screen.getByText('External-service records are temporarily unavailable.')).toBeInTheDocument()

    rerender(<ExternalServiceSummary resource={{ status: 'available', items: [] }} />)
    expect(screen.getByText('No third-party task is recorded for this Claim.')).toBeInTheDocument()
  })

  it('preserves the loading state', () => {
    render(<ExternalServiceSummary resource={{ loading: true, items: [] }} />)

    expect(screen.getByText('Loading third-party tasks...')).toBeInTheDocument()
  })
  it('renders and submits only the exact external-task action for the current Claim revision', async () => {
    const user = userEvent.setup()
    const onAction = vi.fn().mockResolvedValue(undefined)
    const projected = {
      registry_version: '2026-09-15.1',
      action_code: 'external.accept_review',
      target_type: 'external_task',
      target_ref: 'tsk_1',
      label: 'Accept external-service review',
      purpose: 'Take responsibility for reviewing this exact external-service record.',
      availability: 'confirmation_required',
      blocked_reason: null,
      confirmation: {
        level: 'explicit',
        message: 'Accepting this review assigns the Claim and records staff work for this task.',
      },
      expected_effects: ['ownership.assign', 'work_item.create', 'claim.revision.advance'],
      source_refs: ['tsk_1'],
      inputs: [],
      payload_defaults: {},
      result_state: 'not_started',
      based_on_revision: 7,
    }
    render(<ExternalServiceRecords
      records={[request]}
      allowedActions={[
        projected,
        { ...projected, target_ref: 'tsk_other', label: 'Wrong target' },
        { ...projected, based_on_revision: 6, label: 'Stale action' },
      ]}
      claimRevision={7}
      onAction={onAction}
    />)

    await user.click(screen.getByText('Vehicle Damage Assessor'))
    const panel = screen.getByRole('heading', { name: 'Accept external-service review' }).closest('section')
    expect(within(panel).getByText(projected.purpose)).toBeVisible()
    expect(within(panel).getByText(/tsk_1.*Claim revision 7/)).toBeVisible()
    expect(screen.queryByText('Wrong target')).not.toBeInTheDocument()
    expect(screen.queryByText('Stale action')).not.toBeInTheDocument()

    await user.click(within(panel).getByRole('button', { name: 'Review Accept external-service review' }))
    expect(within(panel).getByText(projected.confirmation.message)).toBeVisible()
    await user.click(within(panel).getByRole('button', { name: 'Accept external-service review' }))

    await waitFor(() => expect(onAction).toHaveBeenCalledWith(projected, {}))
  })

  it('keeps a server-blocked external-task action non-executable and shows its reason', async () => {
    const user = userEvent.setup()
    const onAction = vi.fn()
    const blocked = {
      action_code: 'external.accept_review',
      target_type: 'external_task',
      target_ref: 'tsk_1',
      label: 'Accept external-service review',
      purpose: 'Review this exact task.',
      availability: 'blocked',
      blocked_reason: 'Another staff member already owns this Claim.',
      confirmation: { level: 'explicit', message: 'Confirm.' },
      expected_effects: [],
      source_refs: [],
      inputs: [],
      result_state: 'not_started',
      based_on_revision: 7,
    }
    render(<ExternalServiceRecords
      records={[request]}
      allowedActions={[blocked]}
      claimRevision={7}
      onAction={onAction}
    />)

    await user.click(screen.getByText('Vehicle Damage Assessor'))
    expect(screen.getAllByText('Another staff member already owns this Claim.')[0]).toBeVisible()
    expect(screen.queryByRole('button', { name: /Review Accept external-service review/ })).not.toBeInTheDocument()
    expect(onAction).not.toHaveBeenCalled()
  })

  it('does not invent an action from lifecycle attention without an exact projection', async () => {
    const user = userEvent.setup()
    render(<ExternalServiceRecords
      records={[request]}
      allowedActions={[]}
      claimRevision={7}
      onAction={vi.fn()}
    />)

    await user.click(screen.getByText('Vehicle Damage Assessor'))
    expect(screen.getAllByText('Reconcile by operation or provider reference before any retry.')[0]).toBeVisible()
    expect(screen.queryByText('Projected staff action')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /external-service review/i })).not.toBeInTheDocument()
  })

})

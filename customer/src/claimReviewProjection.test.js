import { describe, expect, it } from 'vitest'

import { claimReviewRequirements, claimReviewSections } from './claimReviewProjection.js'

describe('claim review projection', () => {
  it('groups claimant-visible Claim fields without copying their values', () => {
    const form = {
      'claim.product_family': { value: 'home', status: 'confirmed' },
      'incident.description': { value: 'A pipe burst.', status: 'confirmed' },
      'incident.location': { value: 'Kitchen', status: 'proposed' },
      'property.address': { value: '1 Queen Street', status: 'confirmed' },
      'parties.other_parties': { value: 'None', status: 'confirmed' },
      'custom.claimant_note': { value: 'Call after 4pm', status: 'confirmed' },
    }

    expect(claimReviewSections(form)).toEqual([
      {
        id: 'overview',
        title: 'Claim overview',
        fields: [['claim.product_family', form['claim.product_family']]],
        contentsItems: [],
      },
      {
        id: 'incident',
        title: 'Incident details',
        fields: [
          ['incident.description', form['incident.description']],
          ['incident.location', form['incident.location']],
        ],
        contentsItems: [],
      },
      {
        id: 'loss',
        title: 'Insured item and loss',
        fields: [['property.address', form['property.address']]],
        contentsItems: [],
      },
      {
        id: 'parties',
        title: 'Other parties involved',
        fields: [['parties.other_parties', form['parties.other_parties']]],
        contentsItems: [],
      },
      {
        id: 'other',
        title: 'Other information',
        fields: [['custom.claimant_note', form['custom.claimant_note']]],
        contentsItems: [],
      },
    ])
  })

  it('keeps contents items in the loss section instead of inventing form fields', () => {
    const contentsItems = [
      { item_id: 'item-1', description: 'Laptop', status: 'proposed' },
    ]

    expect(claimReviewSections({}, contentsItems)).toEqual([
      {
        id: 'loss',
        title: 'Insured item and loss',
        fields: [],
        contentsItems,
      },
    ])
  })

  it('reads missing and later requirements only from the backend projection', () => {
    const dynamicForm = {
      requirements: {
        ready: false,
        missing_required_now: ['incident.occurred_at', 'incident.occurred_at'],
        pending_later: ['property.address'],
      },
    }

    expect(claimReviewRequirements(dynamicForm)).toEqual({
      available: true,
      ready: false,
      missingRequiredNow: ['incident.occurred_at'],
      pendingLater: ['property.address'],
    })
  })

  it('does not infer readiness when the backend requirements projection is absent', () => {
    expect(claimReviewRequirements(null)).toEqual({
      available: false,
      ready: false,
      missingRequiredNow: [],
      pendingLater: [],
    })
  })
})

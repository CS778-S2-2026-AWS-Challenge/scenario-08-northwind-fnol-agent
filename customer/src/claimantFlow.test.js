import { describe, expect, it } from 'vitest'
import {
  TurnEvent,
  TurnPhase,
  initialSendFlow,
  startTurn,
  transitionTurn,
  turnOwnsView,
  viewTurnPhase,
} from './claimantFlow.js'

const started = () => startTurn(initialSendFlow(), 'turn-1')

describe('claimant send flow', () => {
  it('lets the turn on screen change the view until it settles', () => {
    let flow = started()
    expect(turnOwnsView(flow, 'turn-1')).toBe(true)
    flow = transitionTurn(flow, 'turn-1', TurnEvent.SUBMITTED)
    expect(viewTurnPhase(flow)).toBe(TurnPhase.SUBMITTED)
    flow = transitionTurn(flow, 'turn-1', TurnEvent.SETTLED)
    expect(flow).toEqual(initialSendFlow())
  })

  it('detaches a submitted turn when the claimant leaves, and keeps it running', () => {
    let flow = transitionTurn(started(), 'turn-1', TurnEvent.SUBMITTED)
    flow = transitionTurn(flow, 'turn-1', TurnEvent.LEFT_FOR_HOME)
    expect(turnOwnsView(flow, 'turn-1')).toBe(false)
    expect(flow.turns['turn-1']).toBe(TurnPhase.DETACHED)
    flow = transitionTurn(flow, 'turn-1', TurnEvent.SETTLED)
    expect(flow.turns).toEqual({})
  })

  it('defers leaving while the message is prepared and leaves at submission', () => {
    let flow = transitionTurn(started(), 'turn-1', TurnEvent.LEAVE_REQUESTED)
    expect(turnOwnsView(flow, 'turn-1')).toBe(true)
    flow = transitionTurn(flow, 'turn-1', TurnEvent.SUBMITTED)
    expect(flow.turns['turn-1']).toBe(TurnPhase.DETACHED)
    expect(turnOwnsView(flow, 'turn-1')).toBe(false)
  })

  it('keeps the claimant on the claim when preparation fails after a leave request', () => {
    let flow = transitionTurn(started(), 'turn-1', TurnEvent.LEAVE_REQUESTED)
    flow = transitionTurn(flow, 'turn-1', TurnEvent.SETTLED)
    expect(flow).toEqual(initialSendFlow())
  })

  it('ignores events the current phase does not allow', () => {
    const flow = started()
    expect(transitionTurn(flow, 'turn-1', TurnEvent.LEFT_FOR_HOME)).toBe(flow)
    expect(transitionTurn(flow, 'unknown-turn', TurnEvent.SETTLED)).toBe(flow)
  })

  it('lets a new turn own the view while a detached one finishes', () => {
    let flow = transitionTurn(started(), 'turn-1', TurnEvent.SUBMITTED)
    flow = transitionTurn(flow, 'turn-1', TurnEvent.LEFT_FOR_HOME)
    flow = startTurn(flow, 'turn-2')
    expect(turnOwnsView(flow, 'turn-2')).toBe(true)
    flow = transitionTurn(flow, 'turn-1', TurnEvent.SETTLED)
    expect(turnOwnsView(flow, 'turn-2')).toBe(true)
    expect(Object.keys(flow.turns)).toEqual(['turn-2'])
  })
})

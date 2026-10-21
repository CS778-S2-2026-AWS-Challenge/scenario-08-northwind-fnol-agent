/*
 * Claimant send flow: what happens to a message in flight when the claimant leaves
 * the claim it belongs to.
 *
 * PARTIAL STATE MODEL. This module models one known gap of the claimant client and
 * nothing else: returning home while a message is being sent. Before it, leaving
 * mid-send cleared the message bubble but kept the claimant on the claim, and a
 * reply that arrived later could be written into whatever conversation was on
 * screen. Each turn now has an explicit phase, and only the turn that still owns
 * the view may change what the claimant sees.
 *
 * Still to do before the claimant client has a complete state model:
 * - Navigation state. Which claim, session and page are on screen is still spread
 *   across App.jsx (`activeClaimRef`, `activeSessionIdRef`, `isWorkspaceActive`,
 *   `pageState`, `status`). It should become one machine whose home state has no
 *   active claim by construction.
 * - Only the header Back button goes through this model. The brand link
 *   (`setPage('home')`), opening another claim from history, the profile or a deep
 *   link while a message is in flight are not modelled here; those entry points are
 *   still blocked or handled by the `isBusy` checks in App.jsx.
 * - Session pause. Leaving mid-send skips the pause request, because the session
 *   still has a turn in flight. When a session should be paused (inactivity, an
 *   explicit "later") is an open product decision.
 * - A message that fails after the claimant has left is reported with a home-level
 *   notice only; the failed draft is not kept for retry.
 * - Leaving while the message is still being prepared (claim creation or uploads)
 *   is deferred until it is submitted, with no visible "leaving" feedback.
 * - Uploads, confirmations, service consent and payout/contact steps keep their own
 *   status flags in App.jsx and are not part of this model.
 */

/**
 * Phases of one send. A turn starts in `preparing` (creating the claim, uploading
 * files), moves to `submitted` once the message request is sent, and ends when it
 * settles. Leaving home is honoured immediately once submitted; while preparing it
 * is recorded and carried out at submission, so files and a new claim are never
 * dropped half-way.
 */
export const TurnPhase = Object.freeze({
  PREPARING: 'preparing',
  LEAVE_REQUESTED: 'leave_requested',
  SUBMITTED: 'submitted',
  DETACHED: 'detached',
})

/** Events, per turn. Anything not listed for the current phase is ignored. */
export const TurnEvent = Object.freeze({
  LEAVE_REQUESTED: 'LEAVE_REQUESTED',
  SUBMITTED: 'SUBMITTED',
  LEFT_FOR_HOME: 'LEFT_FOR_HOME',
  SETTLED: 'SETTLED',
})

const SETTLED = 'settled'

/**
 * The transition table. A turn that is `detached` keeps running in the background:
 * its result is remembered in the claim history but never applied to the screen.
 */
const TRANSITIONS = Object.freeze({
  [TurnPhase.PREPARING]: {
    [TurnEvent.LEAVE_REQUESTED]: TurnPhase.LEAVE_REQUESTED,
    [TurnEvent.SUBMITTED]: TurnPhase.SUBMITTED,
    [TurnEvent.SETTLED]: SETTLED,
  },
  [TurnPhase.LEAVE_REQUESTED]: {
    // Submission carries out the deferred leave.
    [TurnEvent.SUBMITTED]: TurnPhase.DETACHED,
    // A turn that ends before submission (an upload failed) keeps the claimant on
    // the claim, so the failure is visible where it happened.
    [TurnEvent.SETTLED]: SETTLED,
  },
  [TurnPhase.SUBMITTED]: {
    [TurnEvent.LEFT_FOR_HOME]: TurnPhase.DETACHED,
    [TurnEvent.SETTLED]: SETTLED,
  },
  [TurnPhase.DETACHED]: {
    [TurnEvent.SETTLED]: SETTLED,
  },
})

/**
 * @typedef {{ viewTurnId: string | null, turns: Readonly<Record<string, string>> }} SendFlow
 * `viewTurnId` is the one turn allowed to change the screen; `turns` holds every turn
 * that has not settled, including detached ones still running in the background.
 */

/** @returns {SendFlow} */
export function initialSendFlow() {
  return { viewTurnId: null, turns: {} }
}

/**
 * Start a turn. It owns the view, because the claimant can only send from the
 * conversation on screen.
 *
 * @param {SendFlow} flow
 * @param {string} turnId
 * @returns {SendFlow}
 */
export function startTurn(flow, turnId) {
  return {
    viewTurnId: turnId,
    turns: { ...flow.turns, [turnId]: TurnPhase.PREPARING },
  }
}

/**
 * Apply one event to one turn. Events the table does not allow leave the flow
 * unchanged.
 *
 * @param {SendFlow} flow
 * @param {string} turnId
 * @param {string} event
 * @returns {SendFlow}
 */
export function transitionTurn(flow, turnId, event) {
  const phase = flow.turns[turnId]
  const next = phase ? TRANSITIONS[phase]?.[event] : undefined
  if (!next) return flow
  const turns = { ...flow.turns }
  if (next === SETTLED) delete turns[turnId]
  else turns[turnId] = next
  const keepsView = next !== SETTLED && next !== TurnPhase.DETACHED
  return {
    viewTurnId: flow.viewTurnId === turnId && !keepsView ? null : flow.viewTurnId,
    turns,
  }
}

/**
 * The phase of the turn that owns the view, or null when none is in flight.
 *
 * @param {SendFlow} flow
 * @returns {string | null}
 */
export function viewTurnPhase(flow) {
  return flow.viewTurnId ? flow.turns[flow.viewTurnId] ?? null : null
}

/**
 * Whether this turn may still change what the claimant sees.
 *
 * @param {SendFlow} flow
 * @param {string} turnId
 * @returns {boolean}
 */
export function turnOwnsView(flow, turnId) {
  return flow.viewTurnId === turnId
}

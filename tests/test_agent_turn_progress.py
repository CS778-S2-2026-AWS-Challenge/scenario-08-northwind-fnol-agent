from backend.domain.realtime import AgentTurnProgressStage, RealtimeAudience
from backend.repositories.fixture import FixtureRepository
from backend.services.agent_turn_progress import AgentTurnProgressReporter
from backend.services.realtime import delivery_for


def test_progress_is_claimant_only_monotonic_and_terminal() -> None:
    repository = FixtureRepository()
    reporter = AgentTurnProgressReporter(
        repository,
        claim_id='clm_progress',
        customer_id='cus_progress',
        session_id='ses_progress',
        turn_id='message-progress',
    )

    reporter.accepted()
    reporter.emit(AgentTurnProgressStage.CONTEXT_LOADING, 'claim.context')
    reporter.emit(AgentTurnProgressStage.MODEL_WAITING, 'model.response')
    reporter.completed()
    reporter.emit(AgentTurnProgressStage.TOOL_RUNNING, 'must.not.publish')

    events = repository.replay_realtime_events(None, limit=20)
    assert [event.progress.ordinal for event in events if event.progress] == [1, 2, 3, 4]
    assert [event.progress.stage for event in events if event.progress] == [
        AgentTurnProgressStage.TURN_ACCEPTED,
        AgentTurnProgressStage.CONTEXT_LOADING,
        AgentTurnProgressStage.MODEL_WAITING,
        AgentTurnProgressStage.TURN_COMPLETED,
    ]
    assert all(event.audiences == (RealtimeAudience.CLAIMANT,) for event in events)
    delivery = delivery_for(events[-1], RealtimeAudience.CLAIMANT)
    assert delivery.event == 'agent.turn.progress'
    assert delivery.data['state'] == 'completed'
    assert delivery.data['turn_id'] == 'message-progress'

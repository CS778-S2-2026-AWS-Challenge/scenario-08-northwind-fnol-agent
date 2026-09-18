"""Publish claimant-safe progress from real Runtime execution boundaries."""

import logging
from threading import Lock

from backend.domain.realtime import (
    AgentTurnProgress,
    AgentTurnProgressPublication,
    AgentTurnProgressStage,
)
from backend.repositories.protocols import PersistenceRepository

logger = logging.getLogger(__name__)


class AgentTurnProgressReporter:
    def __init__(
        self,
        repository: PersistenceRepository,
        *,
        claim_id: str,
        customer_id: str,
        session_id: str,
        turn_id: str,
    ) -> None:
        self._repository = repository
        self._claim_id = claim_id
        self._customer_id = customer_id
        self._session_id = session_id
        self._turn_id = turn_id
        self._ordinal = 0
        self._terminal = False
        self._lock = Lock()

    def emit(
        self,
        stage: AgentTurnProgressStage,
        safe_activity_code: str | None = None,
        *,
        retryable: bool | None = None,
    ) -> None:
        with self._lock:
            if self._terminal:
                return
            self._ordinal += 1
            state = 'running'
            if stage is AgentTurnProgressStage.TURN_COMPLETED:
                state = 'completed'
                self._terminal = True
            elif stage is AgentTurnProgressStage.TURN_FAILED:
                state = 'failed'
                self._terminal = True
            publication = AgentTurnProgressPublication(
                claim_id=self._claim_id,
                customer_id=self._customer_id,
                progress=AgentTurnProgress(
                    turn_id=self._turn_id,
                    session_id=self._session_id,
                    stage=stage,
                    state=state,
                    ordinal=self._ordinal,
                    safe_activity_code=safe_activity_code,
                    retryable=retryable,
                ),
            )
        try:
            self._repository.append_realtime_publication(publication)
        except Exception:
            # Progress is observational and must not roll back an otherwise valid Claim turn.
            logger.exception(
                'agent.turn.progress publication failed',
                extra={
                    'claim_id': self._claim_id,
                    'session_id': self._session_id,
                    'turn_id': self._turn_id,
                    'stage': stage.value,
                },
            )

    def accepted(self) -> None:
        self.emit(AgentTurnProgressStage.TURN_ACCEPTED, 'turn.accepted')

    def completed(self) -> None:
        self.emit(AgentTurnProgressStage.TURN_COMPLETED, 'turn.completed')

    def failed(self, *, retryable: bool) -> None:
        self.emit(
            AgentTurnProgressStage.TURN_FAILED,
            'turn.failed',
            retryable=retryable,
        )

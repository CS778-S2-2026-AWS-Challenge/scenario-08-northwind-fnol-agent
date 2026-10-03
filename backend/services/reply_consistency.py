"""Check that a model reply agrees with what Runtime actually recorded this turn.

Runtime does not edit the model's words. When the words contradict the ledger,
the whole turn goes back to the model once with the ruling attached so it can
say the same thing truthfully.

Two kinds of check run. Structural checks compare the turn's own parts (a
summary with no fields, a declared ending the reply does not match). Whether
the words say something the ledger does not back -- a refused service named, an
arrangement or escalation claimed, a service asked about in words, the claimant
sent to "their insurer", an answer promised that no question passed on backs --
is a judgement about meaning, made only by the review model (``reply_judge``).
When the review model is not configured or its call fails, no rule stands in
for it: the reply is shown and the turn is recorded as not reviewed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.services.reply_judge import ReplyJudge
from backend.services.turn_proposal_validation import ValidatedTurn


@dataclass(frozen=True, slots=True)
class ReplyInconsistency:
    """One reason a reply cannot be shown as written."""

    kind: str
    detail: str


# These are sent back once, but they do not mislead the claimant about what
# Northwind has done: if the rewrite still has one, the turn stands rather than
# failing the claimant's whole message.
SOFT_PROBLEMS = frozenset(
    {'leaves_claimant_stuck', 'ending_mismatch', 'claims_documents_block_lodging'}
)


@dataclass(frozen=True, slots=True)
class ConsistencyReview:
    inconsistencies: tuple[ReplyInconsistency, ...] = field(default_factory=tuple)
    # False when the review model did not read the words (not configured, or
    # its call failed); only the structural checks ran.
    words_reviewed: bool = True

    @property
    def consistent(self) -> bool:
        return not self.inconsistencies

    @property
    def truthful(self) -> bool:
        """No problem other than a soft one remains."""
        return all(item.kind in SOFT_PROBLEMS for item in self.inconsistencies)

    def runtime_review(self, rejected: list[dict[str, str]]) -> dict[str, object]:
        """The note handed back to the model with the original request."""

        return {
            'runtime_review': {
                'reason': 'reply_contradicts_ledger',
                'problems': [
                    {'kind': item.kind, 'detail': item.detail} for item in self.inconsistencies
                ],
                'rejected_parts': rejected,
                'instruction': (
                    'Rewrite the reply so it matches what was actually recorded: do not name or '
                    'promise the rejected services, and do not say anything was arranged, '
                    'booked, escalated or submitted. Offer a service only with offer_service, '
                    "never by asking in words. Northwind is the claimant's insurer: a question "
                    'you cannot answer goes into northwind_questions before the reply says the '
                    'claims team will answer it. Leave the claimant one clear thing to answer or '
                    'do, or say what happens next. Keep every accepted fact and question. Return '
                    'the full envelope again.'
                ),
            }
        }


def _structural_problems(validated: ValidatedTurn) -> list[ReplyInconsistency]:
    """Checks on the turn's own parts; no wording is read."""

    problems: list[ReplyInconsistency] = []
    if validated.action == 'summarize' and not validated.summary_fields:
        problems.append(
            ReplyInconsistency(
                kind='summary_without_fields',
                detail='summarize was chosen but summary_fields did not name any current field',
            )
        )
    asks_for_documents = any(item.stance == 'asking' for item in validated.document_requests)
    if (
        validated.turn_ending is not None
        and '?' not in validated.reply
        and validated.turn_ending != 'nothing_needed'
        and validated.action not in {'summarize', 'answer_only', 'escalate'}
        and validated.escalation is None
        and not validated.service_identities
        and not asks_for_documents
        and not validated.northwind_questions
    ):
        # Nothing to answer, nothing to act on, no summary to check, and the
        # model did not say nothing is needed: the claimant is left guessing.
        problems.append(
            ReplyInconsistency(
                kind='leaves_claimant_stuck',
                detail='the reply asks nothing, offers nothing and does not say what happens next',
            )
        )
        return problems
    # The declared ending has to match the words: a question is asked, and
    # "nothing needed" does not ask the claimant for anything.
    asks = '?' in validated.reply
    if validated.turn_ending == 'question' and not asks:
        problems.append(
            ReplyInconsistency(
                kind='ending_mismatch',
                detail='turn_ending is question but the reply asks no question',
            )
        )
    if validated.turn_ending == 'nothing_needed' and asks:
        problems.append(
            ReplyInconsistency(
                kind='ending_mismatch',
                detail='turn_ending is nothing_needed but the reply asks the claimant something',
            )
        )
    return problems


def review_reply(validated: ValidatedTurn, judge: ReplyJudge | None = None) -> ConsistencyReview:
    """Structural checks, plus the review model's reading of the words."""

    problems = _structural_problems(validated)
    found = judge.problems(validated) if judge is not None else None
    if found is None:
        return ConsistencyReview(tuple(problems), words_reviewed=False)
    problems.extend(ReplyInconsistency(kind=kind, detail=detail) for kind, detail in found)
    return ConsistencyReview(tuple(problems))


# What the claimant said is recorded from the first answer; a rewrite is asked
# for because of the reply's words. A part the rewrite leaves out is kept from
# the first answer, so a reworded reply never loses a recorded fact.
_RECORDED_PARTS = (
    'field_changes',
    'contents_item_changes',
    'document_requests',
    'evidence_interpretations',
    'northwind_questions',
    'scope_note',
)


def keep_recorded_parts(first: object, rewrite: object) -> object:
    """The rewritten answer, with recorded parts it dropped restored from the first."""

    if not isinstance(first, dict) or not isinstance(rewrite, dict):
        return rewrite
    merged = dict(rewrite)
    for key in _RECORDED_PARTS:
        if not merged.get(key) and first.get(key):
            merged[key] = first[key]
    return merged

"""Check that a model reply agrees with what Runtime actually recorded this turn.

Runtime does not edit the model's words. When the words contradict the ledger,
the whole turn goes back to the model once with the ruling attached so it can
say the same thing truthfully.

Two kinds of check run. Structural checks compare the turn's own parts (a
summary with no fields). Wording
checks -- a refused service named, an arrangement or escalation claimed, a
service asked about in words, the claimant sent to "their insurer", an answer
promised with no question passed on -- are made by the review model
(``reply_judge``) when one is configured; the English patterns below are the
fallback when it is not, or when its call fails.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.domain.external_service_registry import SERVICE_REGISTRY
from backend.services.reply_judge import ReplyJudge
from backend.services.turn_proposal_validation import _EXECUTION_CLAIM, ValidatedTurn

_GENERIC_SERVICE_WORDS = frozenset(
    {'vehicle', 'home', 'contents', 'information', 'guidance', 'reporting', 'specialist'}
)
# Sending the report to the claims team is the model's own future act, not a
# third-party promise -- but only as intent ("I'll send it"), never as a
# completed action ("I submitted it") the model cannot actually perform:
# Claim creation is a separate, claimant-confirmed API call this validator has
# no visibility into, so a past-tense or present-perfect submission claim is
# never truthful within this same turn.
_SUBMISSION_INTENT_VERB = re.compile(
    r"\b(?:will|(?:i|we)(?:'ll|’ll))\s+(?:\S+\s+){0,2}?(?:submit|send)\b",  # noqa: RUF001
    re.IGNORECASE,
)


_SERVICE_QUESTION = re.compile(
    r'\b(?:need|want|like|require)\b[^?]{0,60}\b(?:services?|assistance|help|guidance|support)\b',
    re.IGNORECASE,
)
_OTHER_INSURER = re.compile(
    r'\b(?:contact|ask|check with|speak (?:to|with)|reach out to|call)\b[^.?!]{0,40}'
    r'\b(?:your|the)\s+(?:insurer|insurance (?:company|provider))\b',
    re.IGNORECASE,
)
_PROMISED_ANSWER = re.compile(
    r'\b(?:claims team|team|we|someone|a claims (?:handler|professional))\b[^.?!]{0,30}?'
    r"(?:\bwill|'ll|’ll)\s+(?:\S+\s+){0,2}?(?:confirm|answer|check|get back|let you know)\b",  # noqa: RUF001
    re.IGNORECASE,
)
_ESCALATION_CLAIM = re.compile(
    r"\b(?:i|we)(?:'ve|’ve| have)?\s+(?:escalated|referred|passed|flagged|forwarded)\b",  # noqa: RUF001
    re.IGNORECASE,
)


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
                    'claims team will handle it. Leave the claimant one clear thing to answer or '
                    'do, or say what happens next. Keep every accepted fact and question. Return '
                    'the full envelope again.'
                ),
            }
        }


def _service_terms(identity: str) -> set[str]:
    entry = SERVICE_REGISTRY.get(identity)
    if entry is None:
        return {identity.casefold()}
    name = entry.service_name.casefold()
    words = {word for word in re.findall(r'[a-z]+', name) if word not in _GENERIC_SERVICE_WORDS}
    return {name, *words}


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
    """Compare the reply against the services and claims Runtime accepted."""

    problems = _structural_problems(validated)
    found = judge.problems(validated) if judge is not None else None
    if found is not None:
        problems.extend(ReplyInconsistency(kind=kind, detail=detail) for kind, detail in found)
        return ConsistencyReview(tuple(problems))
    problems.extend(_wording_problems(validated))
    return ConsistencyReview(tuple(problems))


def _wording_problems(validated: ValidatedTurn) -> list[ReplyInconsistency]:
    """English patterns used when no review model is available."""

    problems: list[ReplyInconsistency] = []
    lowered = validated.reply.casefold()
    for identity in validated.rejected_services:
        hits = [term for term in _service_terms(identity) if term and term in lowered]
        if hits:
            problems.append(
                ReplyInconsistency(
                    kind='names_rejected_service',
                    detail=f'{identity}: {", ".join(sorted(hits))}',
                )
            )
    # An arrangement claim is never true within this turn, offered service or not: the model's
    # offer_service only creates a pending card, and arranging, booking, approving, completing
    # or contacting only happens after the claimant grants that card their own consent -- a
    # separate turn this validator has no visibility into. Submitting the report is the model's
    # own future job, so "I'll send it" is exempt; a question ("Shall I send it?") asserts
    # nothing either way.
    for sentence in re.split(r'(?<=[.!?])\s+', validated.reply.strip()):
        if sentence.rstrip().endswith('?'):
            continue
        match = _EXECUTION_CLAIM.search(sentence)
        if match is None or _SUBMISSION_INTENT_VERB.search(sentence):
            continue
        problems.append(
            ReplyInconsistency(kind='claims_arrangement_without_service', detail=match.group(0))
        )
        break
    sentences = re.split(r'(?<=[.!?])\s+', validated.reply.strip())
    if not validated.service_identities:
        # Services are offered as cards, which are the consent request. Asking in
        # words ("Do you need any repair services?") promises something no card
        # backs, and skips the rule that services wait for a confirmed account.
        for sentence in sentences:
            if sentence.rstrip().endswith('?') and _SERVICE_QUESTION.search(sentence):
                problems.append(
                    ReplyInconsistency(kind='offers_service_in_words', detail=sentence.strip())
                )
                break
    for sentence in sentences:
        match = _OTHER_INSURER.search(sentence)
        if match is not None:
            # Northwind is the claimant's insurer.
            problems.append(ReplyInconsistency(kind='refers_to_insurer', detail=match.group(0)))
            break
    if validated.escalation is None:
        for sentence in sentences:
            match = _ESCALATION_CLAIM.search(sentence)
            if match is not None and not sentence.rstrip().endswith('?'):
                problems.append(
                    ReplyInconsistency(kind='claims_escalation_without_one', detail=match.group(0))
                )
                break
    if not validated.northwind_questions:
        for sentence in sentences:
            match = _PROMISED_ANSWER.search(sentence)
            if match is not None and not sentence.rstrip().endswith('?'):
                problems.append(
                    ReplyInconsistency(
                        kind='promises_answer_without_question', detail=match.group(0)
                    )
                )
                break
    return problems


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

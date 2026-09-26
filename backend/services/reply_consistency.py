"""Check that a model reply agrees with what Runtime actually recorded this turn.

Runtime does not edit the model's words. When the words contradict the ledger,
the whole turn goes back to the model once with the ruling attached so it can
say the same thing truthfully. The checks are structural, not semantic: they
look for named services Runtime refused and for arrangement claims when no
service was accepted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.domain.external_service_registry import SERVICE_REGISTRY
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


@dataclass(frozen=True, slots=True)
class ReplyInconsistency:
    """One reason a reply cannot be shown as written."""

    kind: str
    detail: str


@dataclass(frozen=True, slots=True)
class ConsistencyReview:
    inconsistencies: tuple[ReplyInconsistency, ...] = field(default_factory=tuple)

    @property
    def consistent(self) -> bool:
        return not self.inconsistencies

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
                    'booked or submitted. Keep every accepted fact and question. Return the full '
                    'envelope again.'
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


def review_reply(validated: ValidatedTurn) -> ConsistencyReview:
    """Compare the reply against the services and claims Runtime accepted."""

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
    if validated.action == 'summarize' and not validated.summary_fields:
        problems.append(
            ReplyInconsistency(
                kind='summary_without_fields',
                detail='summarize was chosen but summary_fields did not name any current field',
            )
        )
    return ConsistencyReview(tuple(problems))

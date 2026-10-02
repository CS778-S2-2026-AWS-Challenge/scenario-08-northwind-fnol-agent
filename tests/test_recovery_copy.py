from backend.domain.recovery_policy_registry import _PUBLISHED_RULES


def test_each_recovery_reason_has_its_own_claimant_sentence() -> None:
    sentences = [rule.claimant_projection for rule in _PUBLISHED_RULES]
    assert len(sentences) == len(set(sentences))


def test_claimant_sentences_avoid_system_words() -> None:
    for rule in _PUBLISHED_RULES:
        lowered = rule.claimant_projection.casefold()
        for word in ('runtime', 'capability', 'authoritative', 'provider', 'recovery session'):
            assert word not in lowered, (rule.rule_id, word)

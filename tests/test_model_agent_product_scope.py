from backend.services.model_agent import _knowledge_product


def test_knowledge_product_uses_canonical_three_path_claim_types() -> None:
    assert _knowledge_product('motor') == 'motor'
    assert _knowledge_product('home') == 'home'
    assert _knowledge_product('contents') == 'contents'


def test_knowledge_product_keeps_legacy_property_alias_scoped_to_home() -> None:
    assert _knowledge_product('property') == 'home'


def test_knowledge_product_does_not_guess_when_claim_type_is_unknown() -> None:
    assert _knowledge_product(None) is None
    assert _knowledge_product('') is None
    assert _knowledge_product('travel') is None

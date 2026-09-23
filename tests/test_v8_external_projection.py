from backend.domain.external_service_registry import (
    capability_catalogue,
    service_action_presentation,
)


def test_unknown_family_catalogue_retains_only_cross_family_manual_guidance() -> None:
    rows = capability_catalogue()
    assert [row.service_identity for row in rows] == ['police_105_reporting_guidance']
    assert rows[0].official_phone
    assert not rows[0].uses_external_task
    assert any(row.uses_external_task for row in capability_catalogue('motor'))


def test_presentation_follows_permission_and_task_progress() -> None:
    assessor = 'vehicle_damage_assessment_routing'
    assert service_action_presentation(assessor, 'consent_required') == 'consent_request'
    assert service_action_presentation(assessor, 'consent_withdrawn') == 'status_update'
    assert service_action_presentation(assessor, 'queued') == 'tracked_task'
    assert service_action_presentation(assessor, 'retryable_failure') == 'action_button'
    assert (
        service_action_presentation('police_105_reporting_guidance', 'manual_available')
        == 'info_link'
    )

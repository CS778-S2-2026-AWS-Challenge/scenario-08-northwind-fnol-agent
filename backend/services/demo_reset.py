from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from backend.core.errors import ApiError


@runtime_checkable
class DemoResettable(Protocol):
    """Explicit opt-in boundary for synthetic runtime components."""

    def reset_demo_state(self) -> dict[str, int]:
        raise NotImplementedError


def reset_demo_components(components: Mapping[str, object]) -> dict[str, int]:
    """Validate every component before clearing any controlled demo state."""
    unavailable = [
        name for name, component in components.items() if not isinstance(component, DemoResettable)
    ]
    if unavailable:
        names = ', '.join(sorted(unavailable))
        raise ApiError(
            status_code=409,
            code='DEMO_RESET_UNAVAILABLE',
            message=f'Demo reset is unavailable for: {names}. No state was cleared.',
        )

    cleared: dict[str, int] = {}
    for component in components.values():
        assert isinstance(component, DemoResettable)
        component_counts = component.reset_demo_state()
        duplicate_names = cleared.keys() & component_counts.keys()
        if duplicate_names:
            names = ', '.join(sorted(duplicate_names))
            raise RuntimeError(f'Demo reset components returned duplicate counters: {names}.')
        cleared.update(component_counts)
    return dict(sorted(cleared.items()))

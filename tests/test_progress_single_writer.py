"""Structural guard for persisted progress ownership, excluding typed DTO copies."""

import ast
from pathlib import Path

SERVICES = Path(__file__).resolve().parents[1] / 'backend' / 'services'
PROGRESS_KEYS = {'workflow_state', 'customer_next_step'}
ALLOWED_WRITERS = {
    ('turn_reducer.py', 'reduce_turn'),
    ('turn_reducer.py', 'recompute_progress'),
    # The reducer-owned adapter applies recompute's result and explicit authorized
    # staff/creation transitions; callers cannot write projection fields themselves.
    ('turn_reducer.py', 'apply_progress'),
    ('handoffs.py', 'updated_claim_for_handoff'),
    ('claims.py', 'start_claim'),
    # An accepted, durably recorded claims-system result initializes CREATED,
    # never reopens intake; the operation record it settles from is itself
    # gated on the same authorised decision create_external_claim checked.
    ('integrations.py', '_settle_recorded_claim_creation'),
}


class ProgressCopies(ast.NodeVisitor):
    def __init__(self) -> None:
        self.function = ''
        self.constructed_types: dict[str, str] = {}
        self.writes: list[tuple[str, int, set[str], ast.Call]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        previous = self.function, self.constructed_types
        self.function, self.constructed_types = node.name, {}
        self.generic_visit(node)
        self.function, self.constructed_types = previous

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.constructed_types[target.id] = node.value.func.id
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Attribute) or node.func.attr != 'model_copy':
            self.generic_visit(node)
            return
        update = next((item.value for item in node.keywords if item.arg == 'update'), None)
        keys = (
            {
                key.value
                for key in update.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            if isinstance(update, ast.Dict)
            else set()
        )
        touched = keys & PROGRESS_KEYS
        if touched:
            receiver = node.func.value
            # A response DTO copy is not a persisted Claim mutation. Prove its
            # constructor in the same scope instead of exempting a variable name.
            is_response_projection = (
                isinstance(receiver, ast.Name)
                and self.constructed_types.get(receiver.id) == 'ClaimantExternalServiceResponse'
            )
            if not is_response_projection:
                self.writes.append((self.function, node.lineno, touched, node))
        self.generic_visit(node)


def test_persisted_progress_copies_have_one_explicit_owner() -> None:
    violations = []
    found = set()
    for path in sorted(SERVICES.glob('*.py')):
        visitor = ProgressCopies()
        visitor.visit(ast.parse(path.read_text(encoding='utf-8')))
        for function, line, keys, _node in visitor.writes:
            owner = (path.name, function)
            found.add(owner)
            if owner not in ALLOWED_WRITERS:
                violations.append(f'{path.name}:{line} {function} writes {sorted(keys)}')
    assert not violations, '\n'.join(violations)
    assert ('turn_reducer.py', 'apply_progress') in found
    assert ('turn_reducer.py', 'reduce_turn') in found


def test_external_creation_exception_only_initializes_created_state() -> None:
    tree = ast.parse((SERVICES / 'integrations.py').read_text(encoding='utf-8'))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == '_settle_recorded_claim_creation'
    )
    state_values = [
        value
        for node in ast.walk(function)
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values, strict=True)
        if isinstance(key, ast.Constant) and key.value == 'workflow_state'
    ]
    assert len(state_values) == 1
    value = state_values[0]
    assert isinstance(value, ast.IfExp)
    assert ast.unparse(value.body) == 'WorkflowState.CREATED'
    assert ast.unparse(value.orelse) == 'claim.claim_state.workflow_state'


def test_authorized_staff_state_updates_always_return_to_shared_progress() -> None:
    tree = ast.parse((SERVICES / 'staff_actions.py').read_text(encoding='utf-8'))
    consumers = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        calls = {
            call.func.id
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        }
        if '_apply_state_changes' in calls:
            consumers.append(node.name)
            assert '_progress_after_staff_mutation' in calls, node.name
    assert set(consumers) == {'resolve_handoff', 'update_staff_action'}


def test_writer_guard_distinguishes_response_projection_from_claim_copy() -> None:
    visitor = ProgressCopies()
    visitor.visit(
        ast.parse("""
def update(claim):
    response = ClaimantExternalServiceResponse()
    response = response.model_copy(update={'customer_next_step': step})
    updated = claim.model_copy(update={'customer_next_step': step})
    state = claim.claim_state.model_copy(update={'workflow_state': state})
""")
    )
    assert [keys for _, _, keys, _ in visitor.writes] == [
        {'customer_next_step'},
        {'workflow_state'},
    ]

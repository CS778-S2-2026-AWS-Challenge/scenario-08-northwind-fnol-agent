# Day 4 Responsive, Accessibility, and Error-State Verification

This record closes the verification scope for issue [#45](https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/issues/45). The tested baseline is `main` candidate `fdeecfa1da7f084b80c6833dd0447ddba05dabd3`, plus the bounded accessibility and responsive fixes in this pull request.

## Checks and results

| Area | Evidence |
| --- | --- |
| Desktop and mobile layout | Claimant and staff entry/empty states were rendered in Chrome at `1440 x 1000` and `390 x 844`. At mobile width, each document's scroll width equals the `390px` viewport. The claimant form, staff sidebar, content, controls, and collapsed assistant remain within the viewport without critical overlap. |
| Keyboard access | The claimant entry path is covered through tab focus and keyboard submission. Staff buttons, selects, textareas, inputs, and attachment controls retain visible focus indicators and accessible names. |
| Loading and disabled states | Claimant mutation controls and staff queue refresh are disabled while their request is active. The workbench exposes `aria-busy` and changes the refresh label while loading. Staff mutation controls remain disabled when no valid claim, action, or signal is selected. |
| Empty and error states | Both surfaces retain an explicit empty state. Claimant failures and staff queue failures use `role="alert"`, restore retry controls, and do not fail silently. |
| Upload state | The evidence API tests cover accepted and rejected upload media states. The staff assistant attachment picker has an accessible name and its selected-file/remove state is covered in the frontend suite. The assistant remains a non-authoritative local prototype control. |
| Transfer state | Claimant tests cover queued, accepted/in-progress, urgent, and reviewed handoff presentation. Focused backend tests verify complete staff packets and claimant-safe projections. |
| Role boundary | Workbench, evidence, and handoff API tests verify that staff receive the internal context required for handling while claimant responses exclude staff-only queues, reason codes, packets, signals, and actions. |

## Verification commands

```text
npm test
2 test files passed; 16 tests passed

npm run lint
passed

npm run build
passed

py -3.12 -m pytest tests/test_employee_workbench_static.py tests/test_evidence_api.py tests/test_handoff_api.py tests/test_workbench_api.py -q
29 passed in 7.78s
```

## Boundary

These checks validate the current synthetic prototype surfaces and documented API boundary. They do not claim conformance with a formal accessibility standard, production browser certification, or a Northwind production identity and permission model.

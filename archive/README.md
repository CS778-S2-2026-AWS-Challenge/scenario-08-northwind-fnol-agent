# Archived frontend tests

This directory preserves frontend test suites that were too broad and expensive for the active
product quality jobs. Product source remains under `customer/`, `workbench/`, and `admin/`.

The archived tests are historical evidence only. Test discovery and continuous integration must
not execute them. New regression coverage belongs in focused tests beside the active component or
contract that owns the behavior.

The archived suites are:

- `frontend-heavy-tests/customer/src/App.test.jsx`.
- `frontend-heavy-tests/workbench/src/pages/WorkbenchPage.test.jsx`.
- `frontend-heavy-tests/workbench/src/components/ReviewActions.test.jsx`.

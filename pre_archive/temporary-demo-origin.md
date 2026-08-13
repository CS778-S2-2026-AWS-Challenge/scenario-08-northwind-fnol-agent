# Temporary Demo Origin

This note preserves the removed single-origin presentation setup for historical reference. It is
not a supported development or production entry point.

The temporary setup built the claimant UI, served the employee workbench, and exposed the FastAPI
routes from one loopback origin at `http://127.0.0.1:8765`. The external demonstration tunnel
provided the public claimant and employee URLs. Runtime state was in-memory and was reset by
restarting the demo origin.

The archived PowerShell scripts in this directory were used to start, reset, and stop that origin.
They must not be restored as part of formal product work without an explicit scope decision.

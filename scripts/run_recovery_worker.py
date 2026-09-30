"""Compatibility wrapper for the packaged P17 recovery worker."""

from backend.recovery_worker_main import main, run_worker

__all__ = ['main', 'run_worker']


if __name__ == '__main__':
    raise SystemExit(main())

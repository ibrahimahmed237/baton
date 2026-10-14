"""Context-local operation budget shared by entry points and storage adapters."""
from contextvars import ContextVar
from time import monotonic


_expires = ContextVar('hook_expires', default=None)


def remaining(default=5.0):
    end = _expires.get()
    return default if end is None else max(0.0, end - monotonic())


def sqlite_timeout(default=5.0):
    # SQLite busy handlers defer Python signals; leave time for the boundary.
    return min(default, remaining(), 0.01) if _expires.get() is not None else default


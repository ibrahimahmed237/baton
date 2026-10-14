"""Interrupt blocking hook work on the CLI's main thread, including flock."""
from contextlib import contextmanager
import signal
import threading
from time import monotonic
from ..ports.budget import _expires, remaining, sqlite_timeout




class DeadlineHit(BaseException):
    """Bypass service rollback loops; unfinished writes recover under the next lock."""


@contextmanager
def deadline(seconds=2.0):
    if threading.current_thread() is not threading.main_thread():
        raise DeadlineHit()
    if seconds <= 0:
        raise DeadlineHit()
    started = monotonic()
    seconds = min(seconds, remaining(seconds))
    if seconds <= 0:
        raise DeadlineHit()
    token = _expires.set(started + seconds)
    previous = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)

    def expire(signum, frame):
        raise DeadlineHit()

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, min(seconds, old_timer[0]) if old_timer[0] else seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        _expires.reset(token)
        signal.signal(signal.SIGALRM, previous)
        if old_timer[0]:
            signal.setitimer(signal.ITIMER_REAL, max(0.000001, old_timer[0] - (monotonic() - started)), old_timer[1])

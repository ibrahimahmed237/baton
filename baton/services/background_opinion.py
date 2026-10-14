"""Second-opinion job entry points shared by immediate and detached commands."""
from .background import Background, Opinions
from .background_brief import WorkerLease


def generate_opinion(engine, ident, label):
    """Release the worker lock for a supervised, read-only opinion request."""
    lease = WorkerLease(engine)
    lease.acquire()
    try:
        Opinions(engine.store, engine.adapters, engine.clock, label).generate(ident, lease)
    finally:
        lease.release()


def immediate_opinion(engine, request, label):
    """Preserve the immediate answer form using the same retained job lifecycle."""
    background = Background(engine.store, engine.clock)
    ident = background.create('ask', request)
    Opinions(engine.store, engine.adapters, engine.clock, label).generate(ident)
    return background.status(ident)

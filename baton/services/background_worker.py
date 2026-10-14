"""Detached worker lifetime with construction and work supplied by the caller."""
import os
import resource


def dispatch_background(engine, work, construct):
    """Use an injected scheduler or detach before constructing a fresh engine."""
    dispatch = getattr(engine, 'background_dispatch', None)
    if dispatch is not None:
        dispatch(lambda: work(engine))
        return
    if os.fork():
        return
    try:
        os.setsid()
        upper = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
        os.closerange(3, min(upper, 1048576))
        null = os.open(os.devnull, os.O_RDWR)
        try:
            for descriptor in (0, 1, 2):
                os.dup2(null, descriptor)
        finally:
            if null > 2:
                os.close(null)
        fresh = construct(engine.root, adapters=engine.adapters, clock=engine.clock)
        try:
            work(fresh)
        finally:
            fresh.close()
    finally:
        os._exit(0)

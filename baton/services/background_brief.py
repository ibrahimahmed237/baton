"""Brief policy and bounded generation, independent of command serialization."""
from contextlib import nullcontext
from .background import Background, BoundedRunner, BackgroundStopped, PreviewRunner


class WorkerLease:
    """Keep service work excluded, releasing the lock only during read-only ask."""
    def __init__(self, engine, locked=False):
        self.engine, self.lock = engine, None
        self.locked = locked

    def acquire(self):
        self.lock = (nullcontext() if self.locked or getattr(self.engine, 'background_dispatch', None)
                     else self.engine.command_lock())
        self.lock.__enter__()

    def release(self):
        if self.lock:
            self.lock.__exit__(None, None, None)
            self.lock = None


def generate_brief(engine, ident, token, publish, locked=False):
    configure_retention(engine)
    background = Background(engine.store, engine.clock)
    replacements = {}
    lease = WorkerLease(engine, locked=locked)
    lease.acquire()
    engine.store.set_background_owner(ident)
    try:
        deadline = background.begin(ident)
        briefs = engine.briefs
        for side, adapter in engine.adapters.items():
            if adapter.runner is not None:
                replacements[side] = adapter.runner
                adapter.runner = BoundedRunner(adapter.runner, background, ident, deadline, lease)
        planned = briefs.confirm(token)
        if background.status(ident)['state'] != 'running':
            raise BackgroundStopped()
        background.finish(ident, publish(planned))
    except BackgroundStopped:
        pass
    except Exception as error:
        if background.status(ident)['state'] == 'running':
            background.finish(ident, {'error': {'kind': type(error).__name__}})
    finally:
        engine.store.set_background_owner(None)
        for side, runner in replacements.items():
            engine.adapters[side].runner = runner
        lease.release()


def plan_brief(engine, link_id, destination=None, writer='auto'):
    """Select a destination and preview with non-spawning runner readiness."""
    destination = destination or tuple(engine.store.get_link(link_id).sides)[-1]
    replacements = {}
    try:
        for side, adapter in engine.adapters.items():
            if adapter.runner is not None:
                replacements[side] = adapter.runner
                adapter.runner = PreviewRunner(adapter.runner)
        return engine.briefs.plan(link_id, destination, writer=None if writer == 'auto' else writer)
    finally:
        for side, runner in replacements.items():
            engine.adapters[side].runner = runner


def configure_retention(engine):
    """Supply owned external-resource deletion without depending on CLI storage."""
    import json
    import os
    import stat
    from pathlib import Path
    from .transcripts import FolderTranscripts

    def remove_transcript(ident):
        value = json.loads(ident)
        path = Path(value['path'])
        folder = engine.root / 'transcripts'
        # The only filesystem scope is Baton's private transcript directory.
        if path.parent.resolve() != folder.resolve():
            return
        path = folder / path.name
        try:
            info = folder.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise ValueError('transcript_directory')
            FolderTranscripts(folder).verify(str(path), value['digest'])
        except FileNotFoundError:
            return
        path.unlink()

    engine.store._configure_background_cleanup({
        'cli_plan': engine.plans.store.delete, 'transcript': remove_transcript})

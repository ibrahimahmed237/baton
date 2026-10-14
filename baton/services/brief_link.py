"""Public lifecycle for linking through a separately reviewed brief."""
from .background import Background, PreviewRunner
from .background_brief import generate_brief


class BriefLink:
    """Own readiness, generation scheduling and immutable creation policy."""
    def __init__(self, engine):
        self.engine = engine
        self.background = Background(engine.store, engine.clock)

    def preview(self, prepare, request):
        replacements = {}
        try:
            for side, adapter in self.engine.adapters.items():
                if adapter.runner is not None:
                    replacements[side] = adapter.runner
                    adapter.runner = PreviewRunner(adapter.runner)
            return prepare(request)
        finally:
            for side, runner in replacements.items():
                self.engine.adapters[side].runner = runner

    def confirm(self, token, review, dispatch, publish):
        if self.engine.store.brief_plan(token)['stage'] == 'generate':
            ident = self.background.create('brief', {'service_plan': token, 'review': review})
            dispatch(self.engine, lambda engine: generate_brief(engine, ident, token,
                lambda planned: publish(engine, planned)))
            return 'background', self.status(ident)
        return 'receipt', self.engine.briefs.confirm(token)

    def status(self, ident, cancel=False):
        value = self.background.stop(ident) if cancel else self.background.status(ident)
        review = self.engine.store.brief_artifact(ident)['request']['review']
        return {**review, **value, 'confirmation': None}

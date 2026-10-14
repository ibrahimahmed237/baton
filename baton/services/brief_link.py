"""Public lifecycle for linking through a separately reviewed brief."""
from ..domain.capabilities import WriteWindow
from .brief_types import BriefPlan, BriefResult
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
            return self.creation_review(prepare(request))
        finally:
            for side, runner in replacements.items():
                self.engine.adapters[side].runner = runner

    def creation_review(self, planned):
        if isinstance(planned, BriefPlan):
            return planned.with_availability(self.engine.adapters[planned.side].app.running())
        return planned

    def confirm(self, token, review, dispatch, publish):
        if self.engine.store.brief_plan(token)['stage'] == 'generate':
            ident = self.background.create('brief', {'service_plan': token, 'review': review})
            dispatch(self.engine, lambda engine: generate_brief(engine, ident, token,
                lambda planned: publish(engine, self.creation_review(planned))))
            return 'background', self.status(ident)
        side = review['steps'][0]['tool']
        adapter = self.engine.adapters[side]
        if adapter.facts.write_window == WriteWindow.APP_CLOSED and adapter.app.running():
            return 'receipt', BriefResult(token, False, error='AppMustBeClosed')
        return 'receipt', self.engine.briefs.confirm(token)

    def status(self, ident, cancel=False):
        value = self.background.stop(ident) if cancel else self.background.status(ident)
        review = self.engine.store.brief_artifact(ident)['request']['review']
        return {**review, **value, 'confirmation': None}

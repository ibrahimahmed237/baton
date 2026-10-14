"""Public lifecycle for linking through a separately reviewed brief."""
from dataclasses import replace
from hashlib import sha256
from ..domain.capabilities import Visibility, WriteWindow
from .relaunch import Relaunch
from .noteformat import NoteRef
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
        if not isinstance(planned, BriefPlan) or planned.stage != 'create':
            return planned
        adapter = self.engine.adapters[planned.side]
        if not (adapter.app.running() and adapter.facts.write_window != WriteWindow.ANY_TIME or
                adapter.facts.new_chat_visible == Visibility.AFTER_RELAUNCH):
            return planned
        service = Relaunch(self.engine.store, self.engine.adapters, self.engine.clock)
        lifecycle = service.plan_brief_creation(self.engine.briefs, planned.plan_id)
        alias = 'p_' + sha256(('brief-relaunch:' + planned.plan_id).encode()).hexdigest()
        ident = 'new_chat.relaunch' if adapter.facts.new_chat_visible == Visibility.AFTER_RELAUNCH else 'new_chat.running_relaunch'
        allowed = ['cancel'] if lifecycle.decision_needed else ['close_sync_reopen', 'cancel']
        values = {'tool': planned.side, 'running': lifecycle.running, 'opens_at_chat': adapter.facts.opens_at_chat, 'relaunch_plan_id': alias, 'button_ids': allowed}
        if adapter.facts.write_window != WriteWindow.APP_CLOSED and not lifecycle.decision_needed:
            allowed.append('sync_relaunch_later')
            values['sync_relaunch_later_plan_id'] = 'p_' + sha256(('brief-create-only:' + planned.plan_id).encode()).hexdigest()
            values['sync_relaunch_later_command'] = 'relaunch'
        note = NoteRef(ident, values)
        notes = tuple(n for n in planned.notes if n.id != 'create.close_manually') + (note,)
        if lifecycle.decision_needed:
            notes += tuple(NoteRef(n.id, {**n.values, 'button_ids': ['cancel']}) for n in lifecycle.notes)
        review = replace(planned, notes=notes, confirmation_available=not lifecycle.decision_needed,
                         lifecycle_steps=lifecycle.steps, relaunch_plan=lifecycle)
        return review

    def confirm(self, token, review, dispatch, publish):
        if self.engine.store.brief_plan(token)['stage'] == 'generate':
            ident = self.background.create('brief', {'service_plan': token, 'review': review})
            dispatch(self.engine, lambda engine: generate_brief(engine, ident, token,
                lambda planned: publish(engine, self.creation_review(planned))))
            return 'background', self.status(ident)
        alias = next((n['values'].get('relaunch_plan_id') for n in review['notes']
                      if n['values'].get('relaunch_plan_id')), None)
        if alias:
            from .background_relaunch import restore_plan
            stored = self.engine.plans.store.load(alias)
            if stored is None:
                from ..domain.errors import ChatChanged
                raise ChatChanged()
            planned = restore_plan(stored.arguments['plan'])
            return 'receipt', Relaunch(self.engine.store, self.engine.adapters, self.engine.clock).apply_brief_creation(
                planned, self.engine.briefs, token)
        return 'receipt', self.engine.briefs.confirm(token)

    def status(self, ident, cancel=False):
        value = self.background.stop(ident) if cancel else self.background.status(ident)
        review = self.engine.store.brief_artifact(ident)['request']['review']
        return {**review, **value, 'confirmation': None}

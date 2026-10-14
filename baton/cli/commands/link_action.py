"""Serialize Linker plans and dispatch the public brief-link lifecycle."""
from .. import output
from ..plans import StoredPlan
from .brief import dispatch_background
from .unlink import confirmed_action
from ...services.brief_link import BriefLink
from ...services.brief_types import BriefPlan


def remember_brief(engine, command, planned):
    review = output.background_brief_plan(planned)
    engine.plans.store.save(StoredPlan(planned.plan_id, planned.plan_id, command,
        {'service_plan': planned.plan_id, 'review': review}, engine.clock.now()))
    return review


def link_action(ctx, args, request, prepare):
    lifecycle = BriefLink(ctx.engine)
    if getattr(args, 'status', None):
        return output.background_status(lifecycle.status(args.status))
    if getattr(args, 'cancel', None):
        return output.background_status(lifecycle.status(args.cancel, cancel=True))
    service = ctx.engine.linker
    if ctx.confirm:
        stored = ctx.engine.plans.store.load(ctx.confirm)
        if stored and 'service_plan' in stored.arguments:
            arguments = ctx.confirmed(lambda r: r['service_plan'])
            token, review = arguments['service_plan'], arguments['review']
            kind, result = lifecycle.confirm(token, review, dispatch_background,
                lambda engine, planned: remember_brief(engine, ctx.command, planned))
            if kind == 'background':
                return output.background_status(result)
            return output.action_receipt({**review, 'plan_id': token,
                'applied': result.applied, 'notes': [output.note('brief.summary_receipt')],
                'confirmation': None}, result)
        return confirmed_action(ctx, request, prepare,
                                lambda p: output.link_action_plan(p, service), service.apply)
    planned = lifecycle.preview(prepare, request)
    if isinstance(planned, BriefPlan):
        return remember_brief(ctx.engine, ctx.command, planned)
    value = output.link_action_plan(planned, service)
    value['plan_id'] = ctx.remember(planned.plan_id, request)
    return value

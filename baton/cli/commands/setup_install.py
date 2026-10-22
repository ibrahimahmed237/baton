"""Hook setup commands parse, dispatch and serialize a service preview."""
import base64
import json
import time
from pathlib import Path
from ...ports.setup_install import InstallRefused
from ..plans import WrongPlanAction, InvalidPlan
from . import command
from .. import output
from ...notes.catalogue import get


def arguments(parser):
    parser.add_argument('--tool')
    parser.add_argument('--scope', choices=('project', 'global'), default='project')
    parser.add_argument('--project')


def serialise(result):
    return {**{key: value for key, value in result.items() if key not in ('_change', '_record', '_record_source', 'notes')},
            'tool_label': output.label(result['tool']),
            'notes': [output.note(note.id, note.values) for note in result['notes']]}


def run(ctx, args, removing):
    service = ctx.engine.setup_install
    def preview(request):
        project = request.get('project')
        if project and ctx.engine.sandboxed and not Path(project).absolute().is_relative_to(ctx.engine.tools_home.absolute()):
            raise InstallRefused()
        return service.preview(**request)
    if ctx.confirm:
        try:
            encoded = ctx.confirm.removeprefix('p_si_')
            if not ctx.confirm.startswith('p_si_') or len(encoded) > 12000: raise ValueError()
            stored = json.loads(base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True))
            if not isinstance(stored, dict) or set(stored) != {'command', 'at', 'request', 'fingerprint'}: raise ValueError()
            if not isinstance(stored['command'], str) or not isinstance(stored['fingerprint'], str): raise ValueError()
            if stored['command'] != ctx.command: raise WrongPlanAction()
            if not 0 <= time.time() - stored['at'] <= 600: raise InvalidPlan()
            request = stored['request']
            if not isinstance(request, dict) or set(request) != {'tool', 'removing', 'scope', 'project'}: raise ValueError()
            if not isinstance(request['tool'], str) or request['tool'] not in service.hooks: raise ValueError()
            if not isinstance(request['project'], str) or not Path(request['project']).is_absolute(): raise ValueError()
            if request['removing'] is not removing or request['scope'] not in ('project', 'global'): raise ValueError()
            result = preview(request)
            if result['plan_id'] != stored['fingerprint']: raise InvalidPlan()
        except (ValueError, KeyError, TypeError, OverflowError): raise InvalidPlan() from None
        result = service.apply(**request, preview=result)
        result['plan_id'] = ctx.confirm
        return serialise(result)
    request = {'tool': args.tool, 'removing': removing, 'scope': args.scope,
               'project': str(Path(args.project).absolute()) if args.project else service.project}
    result = preview(request)
    if not result['can_confirm']:
        result['plan_id'] = None
        return serialise(result)
    request['project'] = result['project']
    stored = {'command': ctx.command, 'request': request, 'fingerprint': result['plan_id'], 'at': time.time()}
    result['plan_id'] = 'p_si_' + base64.urlsafe_b64encode(json.dumps(stored).encode()).decode().rstrip('=')
    return serialise(result)


@command('setup install', get('setup.install_action').template, arguments=arguments, plan=True)
def install(ctx, args):
    return run(ctx, args, False)


@command('setup uninstall', get('setup.uninstall_action').template, arguments=arguments, plan=True)
def uninstall(ctx, args):
    return run(ctx, args, True)

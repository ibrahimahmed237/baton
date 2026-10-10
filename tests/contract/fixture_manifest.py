"""Explicit routes and semantic providers for every built app fixture.

This is a filename inventory, never an inventory of old JSON payloads. Recipes
in generate_fixtures construct their inputs before invoking engine services.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Fixture:
    """A reviewable screen requirement and the authority that supplies its data."""
    filename: str
    command: str
    state: str
    provider: str
    requirement: str
    executable: bool
    recipe: str
    callable: str

READS = {'setup', 'chats', 'suggestions', 'links', 'status', 'history', 'merge-show', 'settings-get'}
SERVICES = {'link', 'copy', 'relink', 'unlink', 'sync', 'brief', 'merge', 'undo', 'restore'}
FUTURE = {'continue', 'relaunch', 'notify', 'open', 'ask', 'ask-add', 'catch-up', 'setup-install',
          'settings-set', 'rename', 'pause', 'resume', 'keep', 'send', 'pin', 'unpin'}
D2_STATES = ('no_links', 'in_sync', 'one_side_ahead', 'waiting', 'relaunch_needed', 'decision_needed', 'paused', 'setup_incomplete')
D3_STATES = ('empty', 'filled', 'tool_missing')
D4_STATES = tuple('s' + str(n) for n in range(1, 13)) + ('s4b', 'paused', 'missing', 'hooks', 'unknown')
D5_STATES = ('claude', 'codex', 'cursor', 'opencode', 'already', 'unavailable', 'large')
D5_TARGETS = {'claude': ('claude',), 'codex': ('codex',), 'cursor': ('cursor',),
              'opencode': ('claude', 'codex', 'cursor', 'opencode'),
              'already': ('opencode',), 'unavailable': ('opencode',), 'large': ('codex',)}
D7_STATES = ('limit_reset', 'limit_no_reset', 'context_size', 'no_size', 'brief_fallback')

# Small model projections exercise the frozen shared shapes with service data.
MODELS = ('note', 'note-button', 'chat', 'side', 'side-condition', 'turn', 'turn-message', 'step', 'plan',
          'link-summary', 'suggestion', 'setup-tool', 'setup-finding', 'settings', 'history-event',
          'next-message', 'usage', 'usage-limit', 'since-you-left', 'same-file', 'removed-turn', 'brief-details')

def _routes():
    """Spell the current filename routes as finite semantic state families."""
    for command in (*MODELS, *sorted(READS | SERVICES | FUTURE)):
        yield command + '.sample.json'
    for command, states in {'note': ('minimal',), 'side': ('empty',), 'turn': ('without-messages',),
                            'plan': ('unlinked',), 'links': ('empty',), 'usage': ('limited', 'unknown'),
                            'merge-show': ('no-shared',), 'undo': ('empty',)}.items():
        for state in states:
            yield f'{command}.{state}.json'
    for state in D2_STATES:
        for command in ('links', 'suggestions', 'continue'):
            yield f'{command}.d2_{state}.json'
    for state in D3_STATES:
        for command in ('chats', 'suggestions', 'links', 'history', 'setup'):
            yield f'{command}.d3_{state}.json'
        for tool in ('claude', 'codex', 'opencode', 'cursor'):
            yield f'chats.d3_{state}_{tool}.json'
    for ident in ('', '_3', '_4', '_5'):
        yield f'status.d3_filled{ident}.json'
    for state in D4_STATES:
        yield f'status.d4_{state}.json'
    for command in ('copy', 'unlink', 'sync', 'relaunch'):
        yield f'{command}.d4_actions.json'
    for state in D5_STATES:
        for command in ('chat', 'chats', 'setup', 'links', 'link'):
            yield f'{command}.d5_{state}.json'
        for tool in ('claude', 'codex', 'opencode', 'cursor'):
            yield f'chats.d5_{state}_{tool}.json'
        for target in D5_TARGETS[state]:
            for command in ('copy', 'link', 'relink'):
                yield f'{command}.d5_{state}_{target}.json'
            for command in ('link', 'relink'):
                for mode in ('attached_history', 'brief'):
                    yield f'{command}.d5_{state}_{target}_{mode}.json'
            yield f'link.d5_{state}_replace_{target}.json'
    yield 'link.d5_already_replace_codex.json'
    for tool in ('claude', 'codex', 'cursor'):
        yield f'link.d6_new_chat_{tool}.json'
    for state in ('claude_open_idle', 'claude_replying', 'codex_holding', 'cursor_running', 'opencode_any_time'):
        yield f'sync.d6_{state}.json'
    for state in ('idle', 'replying', 'when_idle'):
        yield f'relaunch.d6_{state}.json'
    yield 'relaunch.d6_cursor_running.json'
    yield 'setup.d6_labels.json'
    yield 'setup-install.d6_missing_hooks.json'
    for tool in ('claude', 'codex', 'opencode', 'cursor', 'replying'):
        yield f'undo.d6_{tool}.json'
    yield 'setup.d7_labels.json'
    for state in D7_STATES:
        yield f'status.d7_{state}.json'
        yield f'brief.d7_{state}.json'
        if state != 'brief_fallback':
            yield f'brief.d7_{state}_generated.json'
    yield 'brief.d7_offline.json'
    for state in ('limit_reset', 'limit_no_reset', 'brief_fallback', 'unlinked'):
        yield f'notify.d7_{state}.json'
    yield 'continue.d7_limit_reset.json'
    yield 'link.service_full_copy_applied.json'

def _entry(filename):
    command, state, _ = filename.split('.')
    provider = ('real_read' if command in READS else 'real_service_receipt' if state.endswith('_applied')
                else 'real_service_plan' if command in SERVICES else 'future_contract' if command in FUTURE
                else 'model_projection')
    if state.startswith('d4_s'):
        requirement = 'sync-status ' + state.removeprefix('d4_').upper() + ' / R1–R20 / D4'
        recipe = 'World.status_recipe:' + state
    elif state.startswith('d4_'):
        requirement = 'sync-status R4 / A1,A7 / D4 ' + state.removeprefix('d4_')
        recipe = 'World.status_recipe:' + state
    elif state.startswith('d2_'):
        requirement = 'D2 ' + state.removeprefix('d2_') + ' / DESIGN7 / R15,R16 / G9'
        recipe = 'World.popover:' + state
    elif state.startswith('d3_'):
        requirement = 'D3 ' + state.removeprefix('d3_') + ' / G2,G9 / UI8,UI13 shared/separate/hidden receipts'
        recipe = 'World.window:' + state
    elif state.startswith('d5_'):
        requirement = 'D5 ' + state.removeprefix('d5_') + ' / A0,A3,A4 / G4a,G5,G6 / X1,X2'
        recipe = 'World.dialog:' + state
    elif state.startswith('d6_'):
        row = ('Undo on ' + state.removeprefix('d6_') if command == 'undo' else
               'Tool command or hooks missing' if 'missing_hooks' in state else
               'Closing an app while replying' if 'replying' in state or 'when_idle' in state else
               'New chat / open chat / write window ' + state.removeprefix('d6_'))
        requirement = 'D6 / G4a,G4b notes table: ' + row + ' / A6,T5,T6'
        recipe = command + '_provider:' + state
    elif state.startswith('d7_'):
        requirement = 'D7 ' + state.removeprefix('d7_') + ' / W1–W6,W14,W15 / V1–V6 / approved cost/generate/review/create'
        recipe = 'World.handoff:' + state
    else:
        requirement = 'D0 shared CONTRACT ' + command + ' / CP2 section6'
        recipe = 'model_provider:' + command + ':' + state
    read_callable = {'merge-show': 'baton.cli.commands.merge.merge',
                     'settings-get': 'baton.cli.commands.settings.get'}
    callable_name = (read_callable.get(command, 'baton.cli.commands.' + command + '.' + command) if provider == 'real_read' else
                     'BriefService.plan/confirm' if command == 'brief' or '_brief' in state else
                     'Linker.plan_' + command + '/apply' if command in ('link', 'relink', 'copy', 'unlink') else
                     'Applier.preview/apply' if command == 'sync' else
                     'Merger.plan/apply' if command == 'merge' else 'Undo.plan/restore/apply' if command in ('undo', 'restore') else
                     'LimitOffers.check (future notify envelope)' if command == 'notify' else
                     'output serializers (non-executable ' + command + ')')
    return Fixture(filename, command, state, provider, requirement, provider == 'real_read', recipe, callable_name)

MANIFEST = tuple(_entry(filename) for filename in sorted(set(_routes())))
BY_NAME = {item.filename: item for item in MANIFEST}

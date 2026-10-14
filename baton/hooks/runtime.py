"""One bounded, quiet boundary used by CLI commands and installed entry points."""
import argparse
from contextlib import nullcontext
import json
import logging
import select
import sys
from . import HookCall, protocol
from .deadline import DeadlineHit, deadline, remaining
from . import delivery

logger = logging.getLogger(__name__)


def arguments(parser):
    parser.add_argument('--tool', required=True)
    parser.add_argument('--chat')
    parser.add_argument('--turn-id')
    parser.add_argument('--event', choices=('turn_end', 'busy', 'idle'))


def payload(stream, required):
    if not required:
        try:
            if stream.isatty() or not select.select([stream], [], [], 0)[0]:
                return {}
        except (ValueError, OSError, TypeError):
            return {}
    raw = stream.read(1048577)
    if len(raw) > 1048576:
        raise ValueError('hook_payload_size')
    result = json.loads(raw) if raw.strip() else {}
    if not isinstance(result, dict):
        raise ValueError('hook_payload_shape')
    return result


def invoke(args, *, prompt, engine_factory=None, stdin=None, seconds=2.0, locked=False,
           stdout=None, contract=False):
    native = protocol(args.tool)
    empty = native.nothing(prompt) if native else ''
    engine = None
    result = empty
    try:
        with deadline(seconds):
            try:
                if native is None:
                    raise ValueError('hook_tool')
                raw = payload(stdin or sys.stdin, not args.chat)
                call = native.parse(raw)
                if args.chat and call.chat and args.chat != call.chat:
                    raise ValueError('hook_chat_mismatch')
                call = HookCall(args.chat or call.chat, args.turn_id or call.turn,
                                'busy' if prompt else args.event or call.event)
                if not call.chat:
                    raise ValueError('hook_chat_missing')
                if engine_factory is None:
                    from ..cli.wiring import build
                    engine_factory = build
                engine = engine_factory()
                with nullcontext() if locked else engine.command_lock():
                    observe = getattr(engine.adapter(args.tool).state, 'observe', None)
                    if observe is not None:
                        observe({**raw, 'chat_id': call.chat, 'event': call.event})
                    value = (delivery.catch_up if prompt else delivery.notify)(engine, args.tool, call)
                    result = (json.dumps(value) + '\n' if contract else native.nothing(False)) if not prompt else value or empty
            except Exception:
                logger.warning('hook_failed', exc_info=True)
                result = empty
            finally:
                if engine is not None and not locked and remaining() > 0:
                    try:
                        engine.store.close()
                    except Exception:
                        result = empty
                        logger.warning('hook_close_failed', exc_info=True)
            if stdout is not None:
                stdout.write(result)
                stdout.flush()
    except (Exception, DeadlineHit):
        # No cleanup or logging may start once the absolute budget is exhausted.
        result = empty
    return result


class _QuietParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('hook_arguments')


def _parse(words):
    parser = _QuietParser(add_help=False)
    arguments(parser)
    parser.add_argument('--json', action='store_true')
    return parser.parse_args(words)


def _empty(words, prompt):
    tool = words[words.index('--tool') + 1] if '--tool' in words and words.index('--tool') + 1 < len(words) else ''
    native = protocol(tool)
    return native.nothing(prompt) if native else ''


def _run(words, prompt, engine_factory, stdout, contract=False):
    try:
        with deadline():
            try:
                args = _parse(words)
            except (ValueError, SystemExit):
                result = _empty(words, prompt)
                stdout.write(result)
                stdout.flush()
            else:
                result = invoke(args, prompt=prompt, engine_factory=engine_factory,
                                seconds=max(0.0, remaining() - 0.005), contract=contract)
                stdout.write(result)
                stdout.flush()
    except (Exception, DeadlineHit):
        return _empty(words, prompt)
    return result


def main(prompt, argv=None):
    words = list(sys.argv[1:] if argv is None else argv)
    result = _run(words, prompt, None, sys.stdout)
    return 0


def dispatch(argv, *, engine_factory, stdout):
    """Route native commands before ordinary initialization and lock acquisition."""
    words = list(sys.argv[1:] if argv is None else argv)
    json_requested = '--json' in words
    while words and words[0] == '--json':
        words.pop(0)
    if not words or words[0] not in ('catch-up', 'notify'):
        return None
    prompt = words.pop(0) == 'catch-up'
    _run(words, prompt, engine_factory, stdout, contract=json_requested and not prompt)
    return 0

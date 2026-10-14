"""Installed prompt entry point and confirmed reviewed-answer delivery."""
from .runtime import main


def reviewed_reply(engine, tool, call):
    """Attach only confirmed, unexpired answers addressed to this prompt's chat."""
    from ..services.background import Opinions
    from ..cli.tools import label
    if not hasattr(engine.store, 'reviewed_answers'):
        return ''
    return Opinions(engine.store, engine.adapters, engine.clock, label).attach_reviewed(
        tool, call.chat, call.turn)


if __name__ == '__main__':
    raise SystemExit(main(True))

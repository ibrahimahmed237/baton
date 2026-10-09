"""baton links: every link with a one-line state.

PROVISIONAL, C1 proof of the wiring. C2 completes the read command.
Every link is refreshed from its chats before it is described, so `in_sync` is
never read from rows that are older than the chats.
"""
from __future__ import annotations

from typing import Any

from ...domain.link import Link
from ...services.status import link_headline
from ...services.refresh import ChatRefresh
from .. import output
from . import Context, command


@command("links", "List all links with a one-line state")
def links(ctx: Context, args: Any) -> dict[str, Any]:
    """Print the active links."""
    return {"links": [_summary(ctx, link) for link in ctx.engine.store.links()]}


def _summary(ctx: Context, link: Link) -> dict[str, Any]:
    fresh = ChatRefresh(ctx.engine.store, ctx.engine.adapters, ctx.engine.clock).refresh(link.id)
    link, state, missing = fresh["link"], fresh["status"], fresh["missing"]
    return {"link_id": link.id,
            "sides": {side: _chat(ctx, link, side) for side in link.sides},
            "mode": link.mode, "paused": link.paused, "headline": output.note(*link_headline(state, missing)),
            "in_sync": state.in_sync and not missing, "decision_needed": state.decision_needed}


def _chat(ctx: Context, link: Link, side: str) -> dict[str, Any]:
    chat_id = link.chat(side)
    try:
        return output.chat_from_ref(side, ctx.engine.adapter(side).locator.resolve(chat_id), True, link.id)
    except KeyError:
        return output.chat(side, chat_id, "", "", "", True, link.id)



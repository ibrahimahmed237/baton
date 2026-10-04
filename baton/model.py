"""The common shape both tools' chats are read into.

A chat is a list of turns. A turn is one real prompt from the user plus
everything the agent did until the next one. Baton syncs whole turns and
tracks each message by the ID its own tool gave it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PROMPT = "prompt"
REPLY = "reply"
TOOL_CALL = "tool_call"
TOOL_RESULT = "tool_result"


@dataclass(frozen=True)
class Message:
    id: str
    kind: str
    text: str = ""
    at: str = ""
    tool: str = ""
    tool_input: Any = None
    # Ties a TOOL_RESULT to the TOOL_CALL it answers.
    call_id: str = ""
    is_error: bool = False


@dataclass(frozen=True)
class Turn:
    prompt: Message
    messages: tuple[Message, ...] = field(default_factory=tuple)

    @property
    def id(self) -> str:
        return self.prompt.id

    @property
    def started_at(self) -> str:
        return self.prompt.at

    @property
    def ended_at(self) -> str:
        return self.messages[-1].at if self.messages else self.prompt.at

    @property
    def reply_text(self) -> str:
        """The agent's last words in this turn, which is what a reader of the chat sees as its answer."""
        for message in reversed(self.messages):
            if message.kind == REPLY:
                return message.text
        return ""

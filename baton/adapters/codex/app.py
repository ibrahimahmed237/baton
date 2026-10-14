"""Control the Codex desktop app (inside the ChatGPT app): ask it to quit, open it at a chat."""
from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime, timezone

from ...domain.errors import ChatReplying, NotAvailable

_APP_PROCESS = "/ChatGPT.app/Contents/MacOS/ChatGPT"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class SystemProcess:
    """The operating-system calls behind the app: the only code that observes or opens a real process."""

    def running(self) -> bool:
        """Whether the ChatGPT app is running."""
        listing = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True, check=True).stdout
        return any(_APP_PROCESS in line for line in listing.splitlines())

    def started_at(self) -> str:
        """When the running app was launched (UTC), or empty when it is not running."""
        listing = subprocess.run(["ps", "-axo", "lstart=,command="], capture_output=True, text=True, check=True,
                                 env={**os.environ, "LC_ALL": "C"}).stdout
        for line in listing.splitlines():
            line = line.strip()
            if _APP_PROCESS in line:
                stamp = datetime.strptime(line[:24], "%a %b %d %H:%M:%S %Y")
                return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return ""

    def open_url(self, url: str) -> None:
        """Ask the system to open a codex:// link."""
        subprocess.run(["open", url], check=True)

    def quit(self) -> None:
        """Ask the app to quit normally."""
        subprocess.run(["osascript", "-e", 'tell application "ChatGPT" to quit'], check=True)

    def open_app(self) -> None:
        """Launch the app."""
        subprocess.run(["open", "-a", "ChatGPT"], check=True)


class InertProcess:
    """The process port when none is passed in: sees no app, starts nothing, opens and quits nothing.

    It is the default of the adapter, so a test root or a trial folder can never reach
    the real machine; only `CodexAdapter.on_this_machine` swaps in SystemProcess.
    """

    def running(self) -> bool:
        """No app is observed."""
        return False

    def started_at(self) -> str:
        """No app is observed, so there is no launch time."""
        return ""

    def open_url(self, url: str) -> None:
        """Nothing is opened."""
        raise NotAvailable()

    def quit(self) -> None:
        """Nothing is quit."""
        raise NotAvailable()

    def open_app(self) -> None:
        """Nothing is launched."""
        raise NotAvailable()


class CodexApp:
    """Open the app at a chat, or close it when no chat is replying. Codex has nothing to release one chat."""

    def __init__(self, adapter):
        self.adapter = adapter

    def running(self) -> bool:
        """Whether the app is running."""
        return self.adapter.process.running()

    def _require_nothing_replying(self) -> None:
        """Refuse while a chat Baton cannot vouch for is held, or any chat has an unfinished task (held or not)."""
        state = self.adapter.state
        if any(not self.adapter.scope.contains(ident) for ident in state.held_chats()):
            raise NotAvailable()
        if state.replying_chats():
            raise ChatReplying()

    def close(self) -> None:
        """Refuse automatic closure until global idle exclusion is verified."""
        self._require_nothing_replying()
        coordinator = self.adapter.coordination
        if coordinator is None or not hasattr(coordinator, 'global_idle'):
            raise NotAvailable()
        with coordinator.global_idle(self.adapter):
            self._require_nothing_replying()
            self.adapter.process.quit()
            deadline = time.monotonic() + 10
            while self.running():
                if time.monotonic() >= deadline:
                    raise NotAvailable()
                time.sleep(0.05)

    def open(self, chat_id: str | None, folder: str | None) -> None:
        """Open the app, or open it at a chat."""
        if chat_id is None:
            self.adapter.process.open_app()
            return
        self.adapter.locator.resolve(chat_id)
        if not _SAFE_ID.match(chat_id):
            raise ValueError("invalid chat id")
        self.adapter.process.open_url("codex://threads/" + chat_id)

    def release(self, chat_id: str) -> None:
        """Codex keeps a loaded chat until the app quits; one chat cannot be let go."""
        raise NotAvailable()

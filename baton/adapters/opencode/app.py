"""Inert-by-default OpenCode desktop process controls."""
from datetime import datetime, timezone
import os
import subprocess
import time
from urllib.parse import urlencode

from ...domain.errors import ChatReplying, NotAvailable


class InertProcess:
    """Observe no app and refuse process actions unless explicitly injected."""

    def running(self):
        """No real app is inspected."""
        return False

    def started_at(self):
        """No app launch time is observed."""
        return ""

    def open_url(self, url):
        """Refuse an unconfigured app launch."""
        raise NotAvailable()

    def quit(self):
        """Refuse an unconfigured app close."""
        raise NotAvailable()


class SystemProcess:
    """Real system calls, selected only by on_this_machine."""

    @staticmethod
    def _listing():
        return subprocess.run(["ps", "-axo", "lstart=,command="], capture_output=True, text=True,
                              check=True, env={**os.environ, "LC_ALL": "C"}).stdout.splitlines()

    def running(self):
        """Observe the desktop process rather than a background CLI run."""
        return any("/OpenCode.app/Contents/MacOS/" in line for line in self._listing())

    def started_at(self):
        """Return the desktop launch time as UTC, when observed."""
        line = next((s.strip() for s in self._listing() if "/OpenCode.app/Contents/MacOS/" in s), "")
        if not line:
            return ""
        return datetime.strptime(line[:24], "%a %b %d %H:%M:%S %Y").astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def open_url(self, url):
        """Open the folder deep link without contacting the password-protected server."""
        subprocess.run(["open", url], check=True)

    def quit(self):
        """Ask the desktop to quit normally."""
        subprocess.run(["osascript", "-e", 'tell application "OpenCode" to quit'], check=True)


class OpenCodeApp:
    """Open a folder; no native chat deep link or single-chat release exists."""

    def __init__(self, adapter, close_timeout=10, monotonic=None, sleep=None):
        self.adapter = adapter
        self.close_timeout = close_timeout
        self.monotonic = monotonic or time.monotonic
        self.sleep = sleep or time.sleep

    def running(self):
        """Delegate to the injected process control."""
        return self.adapter.process.running()

    def open(self, chat_id, folder):
        """Use only the open-project folder URL."""
        if not folder and chat_id:
            folder = self.adapter.locator.resolve(chat_id).folder
        if not folder:
            raise NotAvailable()
        self.adapter.process.open_url("opencode://open-project?" + urlencode({"directory": folder}))

    def close(self):
        """Refuse closing during any unfinished native reply."""
        scoped = self.adapter.allowed_chat_ids | self.adapter.writer.created
        chats = self.adapter.locator.chats()
        if any(c.id not in scoped for c in chats):
            raise NotAvailable()
        if any(self.adapter.state.condition(c.id).replying for c in chats):
            raise ChatReplying()
        self.adapter.process.quit()
        deadline = self.monotonic() + self.close_timeout
        while self.running():
            if self.monotonic() >= deadline:
                raise NotAvailable()
            self.sleep(.05)

    def release(self, chat_id):
        """No single-chat release is supported."""
        raise NotAvailable()

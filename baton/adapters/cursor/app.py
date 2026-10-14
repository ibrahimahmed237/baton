"""Injected desktop control; real process calls are explicit opt-in only."""
import subprocess
import os
import re
import time
from datetime import datetime, timezone

from ...domain.errors import ChatReplying, NotAvailable


class InertProcess:
    def running(self):
        # An inert control cannot attest that the app is closed.
        raise NotAvailable()

    def started_at(self):
        return ''

    def quit(self):
        raise NotAvailable()

    def open_folder(self, folder):
        raise NotAvailable()


def cursor_command(command):
    command = command.strip()
    return bool(re.search(r'(?:^|/)Cursor\.app/Contents/(?:MacOS/Cursor(?:\s|$)|Frameworks/.*Cursor Helper)', command)
                or re.match(r'^Cursor(?: Helper(?: \([^)]*\))?)?(?:\s|$)', command))


class SystemProcess:
    def running(self):
        try:
            result = subprocess.run(['ps', '-axo', 'command='], capture_output=True, text=True, check=True)
            return result.returncode != 0 or any(cursor_command(line) for line in result.stdout.splitlines())
        except (OSError, subprocess.SubprocessError):
            return True

    def started_at(self):
        try:
            output = subprocess.run(['ps', '-axo', 'lstart=,command='], capture_output=True,
                                    text=True, check=True, env={**os.environ, 'LC_ALL': 'C'}).stdout
        except (OSError, subprocess.SubprocessError):
            return ''
        for line in output.splitlines():
            line = line.strip()
            if cursor_command(line[24:]):
                stamp = datetime.strptime(line[:24], '%a %b %d %H:%M:%S %Y')
                return stamp.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
        return ''

    def quit(self):
        subprocess.run(['osascript', '-e', 'tell application "Cursor" to quit'], check=True)

    def open_folder(self, folder):
        if not folder:
            raise NotAvailable()
        subprocess.run(['open', '-a', 'Cursor', folder], check=True)


class CursorApp:
    def __init__(self, adapter):
        self.adapter = adapter

    def running(self):
        try:
            return self.adapter.process.running()
        except NotAvailable:
            # Observation remains usable; writers require the process evidence directly.
            return False

    def close(self):
        # Only a running Cursor can be replying. A chat never observed counts as replying
        # (unknown), so a running app is not closed on a guess.
        if self.running():
            if any(value.get('replying') is True for value in self.adapter.state.observations().values()):
                raise ChatReplying()
            if not self.adapter.hooks.check().ok:
                error = NotAvailable()
                error.note_id = 'relaunch.replying_unknown'
                raise error
        self.adapter.process.quit()
        deadline = time.monotonic() + 10
        while self.running():
            if time.monotonic() >= deadline:
                raise NotAvailable()
            time.sleep(.05)

    def open(self, chat_id, folder):
        if chat_id is not None:
            folder = self.adapter.locator.resolve(chat_id).folder
        self.adapter.process.open_folder(folder)

    def release(self, chat_id):
        raise NotAvailable()

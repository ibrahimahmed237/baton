"""Separate cursor-agent background requests, never linked app chats."""
import subprocess
from shutil import which
from ...domain.errors import NotAvailable
from ...ports.tool import SetupFinding


class InertRunner:
    def ready(self):
        return self.available()

    def available(self):
        return SetupFinding('runner', False, 'setup.runner', {'tool': 'cursor'})

    def ask(self, prompt, folder, read_only=True):
        raise NotAvailable()


class CursorRunner:
    def __init__(self, command):
        self.command = command

    def _run(self, args, folder=None):
        return self.command(args, cwd=folder, capture_output=True, text=True, timeout=120)

    def ready(self):
        ok = which('cursor-agent') is not None
        return SetupFinding('runner', ok, '' if ok else 'setup.runner', {'tool': 'cursor'})

    def available(self):
        try:
            result = self._run(['cursor-agent', 'status'])
            # Status prose is unverified; only exact known responses indicate readiness.
            output = result.stdout.strip().lower()
            ok = result.returncode == 0 and output in ('logged in', 'signed in')
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        return SetupFinding('runner', ok, '' if ok else 'setup.runner', {'tool': 'cursor'})

    def ask(self, prompt, folder, read_only=True):
        if not read_only or not self.available().ok:
            raise NotAvailable()
        try:
            result = self._run(['cursor-agent', '-p', '--mode', 'ask', '--output-format', 'text',
                                '--', prompt], folder)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise NotAvailable() from error
        if result.returncode:
            raise NotAvailable()
        return result.stdout

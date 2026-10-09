"""Ephemeral reader process; never resumes a linked session."""
import shutil
import subprocess
from ...domain.errors import NotAvailable
from ...ports.tool import SetupFinding

class ClaudeRunner:
    """Run a separate ephemeral process restricted to reading."""
    def __init__(self, command=None): self.command = command or subprocess.run
    def _run(self, args, folder=None):
        return self.command(args, cwd=folder, capture_output=True, text=True, timeout=120)
    def available(self):
        """Report whether the background command is signed in and usable."""
        try:
            result = self._run(['claude', 'auth', 'status', '--json'])
            import json
            ok = result.returncode == 0 and json.loads(result.stdout).get('loggedIn') is True
        except (OSError, ValueError, subprocess.TimeoutExpired): ok = False
        return SetupFinding('runner', ok, '' if ok else 'setup.runner', {'tool': 'claude'})
    def ask(self, prompt, folder, read_only=True):
        """Ask in an ephemeral read-only process without resuming a linked chat."""
        if not read_only: raise NotAvailable()
        if not self.available().ok: raise NotAvailable()
        result = self._run(['claude', '-p', '--no-session-persistence', '--setting-sources', 'project',
            '--allowedTools', 'Read,Grep,Glob', '--', prompt], folder)
        if result.returncode: raise NotAvailable()
        return result.stdout

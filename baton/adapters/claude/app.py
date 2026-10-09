"""App/process controls isolated behind an injectable operating-system port."""
import os
import shlex
import signal
import subprocess
import time
from datetime import datetime, timezone
from ...domain.errors import ChatReplying, NotAvailable

class SystemProcess:
    """Isolate operating-system observations and app control calls."""
    def alive(self, pid):
        """Check whether a positive process identity is still alive."""
        if not isinstance(pid, int) or pid <= 0: return False
        try: os.kill(pid, 0); return True
        except OSError: return False
    def running(self):
        """Observe whether the desktop app process is running."""
        listing = subprocess.run(['ps', '-axo', 'command='], capture_output=True, text=True, check=True).stdout
        return any('/Claude.app/Contents/MacOS/Claude' in line for line in listing.splitlines())
    def started_at(self):
        """Return the desktop process launch time when it can be observed."""
        env = {**os.environ, 'LC_ALL': 'C'}
        listing = subprocess.run(['ps', '-axo', 'lstart=,command='], capture_output=True,
            text=True, check=True, env=env).stdout
        for line in listing.splitlines():
            line = line.strip()
            if '/Claude.app/Contents/MacOS/Claude' in line:
                stamp = datetime.strptime(line[:24], '%a %b %d %H:%M:%S %Y')
                return stamp.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
        return ''
    def owns_session(self, pid, sid):
        """Verify that a process belongs to the requested native session."""
        if not isinstance(pid, int) or pid <= 0: return False
        result = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True,
            text=True, check=False)
        if result.returncode: return False
        try: args = shlex.split(result.stdout.strip())
        except ValueError: return False
        if not args or os.path.basename(args[0]) != 'claude': return False
        return any(args[i] in ('--session-id', '--resume') and args[i + 1] == sid
            for i in range(len(args) - 1))
    def terminate(self, pid):
        """Send a normal termination signal to an already verified process."""
        if pid <= 0: raise ValueError('invalid process id')
        os.kill(pid, signal.SIGTERM)
    def open_url(self, url):
        """Ask the system to open the supplied native chat link."""
        subprocess.run(['open', url], check=True)
    def quit(self):
        """Ask the desktop app to quit normally."""
        subprocess.run(['osascript', '-e', 'tell application "Claude" to quit'], check=True)
    def open_app(self):
        """Ask the system to launch the desktop app."""
        subprocess.run(['open', '-a', 'Claude'], check=True)

class ClaudeApp:
    """Open, close or release only chats whose state allows it."""
    def __init__(self, adapter): self.adapter = adapter
    def running(self):
        """Observe whether the desktop app process is running."""
        return self.adapter.process.running()
    def close(self):
        """Quit normally only after checking for active replies."""
        if any(e.get('status') == 'busy' for e in self.adapter.state.registry()): raise ChatReplying()
        self.adapter.process.quit()
        deadline = time.monotonic() + 10
        while self.running():
            if time.monotonic() >= deadline: raise NotAvailable()
            time.sleep(.05)
    def open(self, chat_id, folder):
        """Open the app or a resolved native chat."""
        if chat_id is None: self.adapter.process.open_app()
        else:
            self.adapter.locator.resolve(chat_id)
            self.adapter.process.open_url('claude://claude.ai/epitaxy/' + chat_id)
    def release(self, chat_id):
        """End an idle owned chat process and wait for its registry release."""
        entries = list(self.adapter.state.registry(chat_id))
        if any(e.get('status') == 'busy' for e in entries): raise ChatReplying()
        # Refresh before signalling: a reply may have started after the preview.
        current = list(self.adapter.state.registry(chat_id))
        if any(e.get('status') == 'busy' for e in current): raise ChatReplying()
        for entry in current:
            if not self.adapter.process.owns_session(entry['pid'], entry['sessionId']): raise NotAvailable()
        for entry in current:
            # Revalidate immediately before each signal, including registry busy state.
            latest = list(self.adapter.state.registry(chat_id))
            match = next((e for e in latest if e.get('pid') == entry['pid']), None)
            if match is None: continue
            if match.get('status') == 'busy': raise ChatReplying()
            if not self.adapter.process.owns_session(entry['pid'], entry['sessionId']): raise NotAvailable()
            self.adapter.process.terminate(entry['pid'])
        deadline = time.monotonic() + 10
        while list(self.adapter.state.registry(chat_id)):
            if time.monotonic() >= deadline: raise NotAvailable()
            time.sleep(.05)

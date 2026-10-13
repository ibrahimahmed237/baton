"""App/process controls isolated behind an injectable operating-system port."""
import os
import shlex
import signal
import subprocess
import time
from datetime import datetime, timezone
from ...domain.errors import ChatChanged, ChatReplying, NotAvailable

def local_start_utc(value, convert=None, *, fold=0, zone=None):
    """Parse a local ps start time and convert it to UTC with an injectable converter."""
    stamp = datetime.strptime(value, '%a %b %d %H:%M:%S %Y').replace(fold=fold)
    if zone is not None: stamp = stamp.replace(tzinfo=zone)
    return (convert(stamp) if convert else stamp.astimezone(timezone.utc)).astimezone(timezone.utc)

class SystemProcess:
    """Isolate operating-system observations and app control calls."""
    def __init__(self, command=None, local_to_utc=None, *, local_zone=None):
        self.command = command; self.local_to_utc = local_to_utc; self.local_zone = local_zone
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
    def owns_session(self, pid, sid, entry=None):
        """Verify that a process belongs to the requested native session."""
        if type(pid) is not int or pid <= 0 or not isinstance(sid, str) or not sid: return False
        command = self.command or subprocess.run
        if entry is not None:
            if not isinstance(entry, dict) or entry.get('_registry_pid') != str(pid): return False
            if entry.get('pid') != pid or entry.get('sessionId') != sid: return False
            if entry.get('status') not in ('idle', 'busy'): return False
            if 'procStart' in entry:
                try:
                    result = command(['ps', '-p', str(pid), '-o', 'lstart=,comm='], capture_output=True,
                        text=True, check=False, env={**os.environ, 'LC_ALL': 'C'})
                    if result.returncode: return False
                    line = result.stdout.strip()
                    if not line[24:].strip().endswith('/claude.app/Contents/MacOS/claude'): return False
                    registered = datetime.strptime(entry['procStart'], '%a %b %d %H:%M:%S %Y').replace(tzinfo=timezone.utc)
                    return any(registered == local_start_utc(line[:24], self.local_to_utc,
                        fold=fold, zone=self.local_zone) for fold in (0, 1))
                except (OSError, TypeError, ValueError, OverflowError): return False
        try:
            result = command(['ps', '-p', str(pid), '-o', 'command='], capture_output=True,
                text=True, check=False)
        except OSError: return False
        if result.returncode: return False
        try: args = shlex.split(result.stdout.strip())
        except ValueError: return False
        if not args or os.path.basename(args[0]) != 'claude': return False
        return any(args[i] in ('--session-id', '--resume') and args[i + 1] == sid
            for i in range(len(args) - 1))
    def terminate(self, pid):
        """Send a normal termination signal to an already verified process."""
        if type(pid) is not int or pid <= 1: raise ValueError('invalid process id')
        try: os.kill(pid, signal.SIGTERM)
        except ProcessLookupError: pass
        except PermissionError as error: raise NotAvailable() from error
    def open_url(self, url):
        """Ask the system to open the supplied native chat link."""
        subprocess.run(['open', url], check=True)
    def quit(self):
        """Ask the desktop app to quit normally."""
        subprocess.run(['osascript', '-e', 'tell application "Claude" to quit'], check=True)
    def open_app(self):
        """Ask the system to launch the desktop app."""
        subprocess.run(['open', '-a', 'Claude'], check=True)

class InertProcess:
    """The process port when none is passed in: sees no app or session, signals and opens nothing.

    It is the default of the adapter, so a test root or a trial folder can never reach
    the real machine; only `ClaudeAdapter.on_this_machine` swaps in SystemProcess.
    """
    def alive(self, pid):
        """No process is observed."""
        return False
    def running(self):
        """No app is observed."""
        return False
    def started_at(self):
        """No app is observed, so there is no launch time."""
        return ''
    def owns_session(self, pid, sid, entry=None):
        """No process is observed, so none belongs to a session."""
        return False
    def terminate(self, pid):
        """Nothing is signalled."""
        raise NotAvailable()
    def open_url(self, url):
        """Nothing is opened."""
        raise NotAvailable()
    def quit(self):
        """Nothing is quit."""
        raise NotAvailable()
    def open_app(self):
        """Nothing is launched."""
        raise NotAvailable()

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
        current = list(self.adapter.state.registry(chat_id))
        if not current:
            self._wait_until_still(chat_id)
            return
        for entry in current:
            if entry.get('status') == 'busy': raise ChatReplying()
            if not self.adapter.process.owns_session(entry['pid'], entry['sessionId'], entry): raise NotAvailable()
        for entry in current:
            # Revalidate immediately before each signal, including registry busy state.
            latest = list(self.adapter.state.registry(chat_id))
            match = next((e for e in latest if e.get('pid') == entry['pid']), None)
            if match is None: continue
            if match.get('status') == 'busy': raise ChatReplying()
            if not self.adapter.process.owns_session(match['pid'], match['sessionId'], match): raise NotAvailable()
            # Process identity or busy state can still change between this check and signal.
            self.adapter.process.terminate(entry['pid'])
        deadline = time.monotonic() + 10
        while list(self.adapter.state.registry(chat_id)):
            if time.monotonic() >= deadline: raise NotAvailable()
            time.sleep(.05)

        self._wait_until_still(chat_id)

    def _wait_until_still(self, chat_id):
        """Wait at most three seconds for both native files to stop changing."""
        paths = (self.adapter.locator.session_path(chat_id), self.adapter.locator.entry(chat_id)[0])
        def signature():
            try:
                return tuple((p.stat().st_size, p.stat().st_mtime_ns) for p in paths)
            except OSError as error:
                raise ChatChanged() from error
        deadline = self.adapter.monotonic() + 3
        previous = signature()
        while self.adapter.monotonic() < deadline:
            self.adapter.sleep(min(.1, max(0, deadline - self.adapter.monotonic())))
            current = signature()
            if current == previous:
                return
            previous = current
        raise ChatChanged()

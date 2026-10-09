"""Session registry plus injectable process checks; no idle-time inference."""
import json
from ...domain.conditions import SideCondition
from ...ports.tool import FormatCheck
from .reader import read_records

class ClaudeState:
    """Report native holders, format checks and visibility evidence."""
    def __init__(self, adapter): self.adapter = adapter
    def registry(self, chat_id=None):
        """Read live session holders, optionally for one stable chat."""
        sid = self.adapter.locator.entry(chat_id)[1]["cliSessionId"] if chat_id else None
        for path in (self.adapter.root / ".claude/sessions").glob("*.json"):
            try: entry = json.loads(self.adapter.locator.inside(path).read_text())
            except (OSError, ValueError): continue
            pid = entry.get("pid")
            if isinstance(pid, int) and pid > 0 and self.adapter.process.alive(pid):
                if sid is None or entry.get("sessionId") == sid: yield entry
    def condition(self, chat_id):
        """Combine existence, holder, hook and launch evidence for a chat."""
        try: self.adapter.locator.resolve(chat_id)
        except KeyError: return SideCondition(exists=False, app_running=self.adapter.process.running())
        entries = list(self.registry(chat_id))
        return SideCondition(open=bool(entries), replying=any(e.get("status") == "busy" for e in entries),
            app_running=self.adapter.process.running(), app_started_at=self.adapter.process.started_at(),
            hooks_ready=self.adapter.hooks.check().ok, format_known=self.format_version().known)
    def format_version(self):
        """Validate every native sidebar target, including hidden entries."""
        versions = set()
        try:
            for _, entry in self.adapter.locator.entries():
                path = self.adapter.locator.session_path(entry["sessionId"])
                # Tolerant reads may skip damaged tail lines; writes never may.
                text = path.read_text()
                if text and not text.endswith('\n'): return FormatCheck(False, "incomplete")
                records = [json.loads(line) for line in text.splitlines() if line.strip()]
                if not all(isinstance(r, dict) for r in records): return FormatCheck(False, "unknown")
                for rec in records:
                    if rec.get("type") in ("user", "assistant"):
                        version = rec.get("version", "")
                        versions.add(version)
                        if not all(k in rec for k in ("uuid", "parentUuid", "message")):
                            return FormatCheck(False, version)
            known = not versions or versions <= set(self.adapter.facts.checked_versions)
            return FormatCheck(known, next(iter(sorted(versions)), self.adapter.facts.checked_versions[0]))
        except (OSError, ValueError, KeyError): return FormatCheck(False, "unknown")

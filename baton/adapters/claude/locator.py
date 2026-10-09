"""Stable desktop sidebar identities, resolved afresh on every operation."""
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from ...ports.tool import ChatRef

class ClaudeLocator:
    """Resolve stable sidebar identities to their current native files."""
    def __init__(self, root): self.root = Path(root).resolve()
    def inside(self, path):
        """Refuse any resolved path outside the configured adapter root."""
        path = Path(path).resolve()
        if not path.is_relative_to(self.root): raise ValueError("outside adapter root")
        return path
    @property
    def sidebar(self):
        """Return the desktop sidebar directory under the configured root."""
        return self.root / "Library/Application Support/Claude/claude-code-sessions"
    def entries(self):
        """Read native sidebar entries without applying discovery filters."""
        for path in self.sidebar.glob("*/*/local_*.json"):
            path = self.inside(path)
            try: entry = json.loads(path.read_text())
            except (OSError, ValueError): continue
            if isinstance(entry, dict) and entry.get("sessionId"): yield path, entry
    def entry(self, chat_id):
        """Locate the sidebar entry for one stable chat identity."""
        matches = [(p, e) for p, e in self.entries() if e["sessionId"] == chat_id]
        if len(matches) != 1: raise KeyError(chat_id)
        return matches[0]
    def session_path(self, chat_id):
        """Follow the sidebar identity to its current native chat file."""
        _, entry = self.entry(chat_id)
        sid = entry.get("cliSessionId", "")
        if not sid or Path(sid).name != sid: raise ValueError("invalid session id")
        matches = list((self.root / ".claude/projects").glob("*/" + sid + ".jsonl"))
        if len(matches) != 1: raise KeyError(chat_id)
        return self.inside(matches[0])
    def chats(self):
        """List discoverable native sidebar chats."""
        return [self.resolve(e["sessionId"]) for _, e in self.entries()
                if not e.get("isArchived") and not e.get("scriptStarted")]
    def resolve(self, chat_id):
        """Return the current reference for a stable chat identity."""
        _, entry = self.entry(chat_id)
        self.session_path(chat_id)
        ms = entry.get("lastActivityAt", 0)
        updated = datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
        return ChatRef(chat_id, entry.get("title", ""), entry.get("cwd", ""), updated)
    def name(self, chat_id):
        """Read the current title from the native sidebar entry."""
        return self.resolve(chat_id).name
    def creation_paths(self, chat_id, sid, folder, account=None):
        """Choose confined native chat and sidebar paths for creation."""
        accounts = sorted({p.parent for p, _ in self.entries()})
        target = self.inside(account) if account else (accounts[0] if len(accounts) == 1 else None)
        if target is None: raise ValueError("an explicit sidebar account is required")
        project = re.sub(r"[^A-Za-z0-9]", "-", folder) or "-"
        return self.inside(self.root / ".claude/projects" / project / (sid + ".jsonl")), self.inside(target / (chat_id + ".json"))

"""Session registry plus injectable process checks; no idle-time inference."""
import json
import re
from ...domain.conditions import SideCondition
from ...ports.tool import FormatCheck
from .reader import _ON_THE_CHAIN

class ClaudeState:
    """Report native holders, format checks and visibility evidence."""
    def __init__(self, adapter): self.adapter = adapter
    def registry(self, chat_id=None):
        """Read live session holders, optionally for one stable chat."""
        sid = self.adapter.locator.entry(chat_id)[1]["cliSessionId"] if chat_id else None
        for path in (self.adapter.root / ".claude/sessions").glob("*.json"):
            try: entry = json.loads(self.adapter.locator.inside(path).read_text())
            except (OSError, ValueError): continue
            if not isinstance(entry, dict): continue
            pid = entry.get("pid")
            if type(pid) is int and pid > 0 and path.stem == str(pid) and self.adapter.process.alive(pid):
                if sid is None or entry.get("sessionId") == sid: yield dict(entry, _registry_pid=path.stem)
    def condition(self, chat_id):
        """Combine existence, holder, hook and launch evidence for a chat."""
        try: self.adapter.locator.resolve(chat_id)
        except KeyError: return SideCondition(exists=False, app_running=self.adapter.process.running())
        entries = list(self.registry(chat_id))
        check = self.format_version()
        condition = SideCondition(open=bool(entries), replying=any(e.get("status") == "busy" for e in entries),
            app_running=self.adapter.process.running(), app_started_at=self.adapter.process.started_at(),
            hooks_ready=self.adapter.hooks.check().ok, format_known=check.known, format_new_version=check.new_version)
        return condition
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
                # Any ancestor can be pulled onto the chain through parentUuid.
                chained_ids = {r[key] for r in records for key in ("parentUuid", "logicalParentUuid")
                               if isinstance(r.get(key), str)}
                for rec in records:
                    if rec.get("type") in _ON_THE_CHAIN or (isinstance(rec.get("uuid"), str) and rec["uuid"] in chained_ids):
                        if not chain_shape_known(rec): return FormatCheck(False, "unknown")
                    if not isinstance(rec.get("type"), str): return FormatCheck(False, "unknown")
                    if "message" in rec and rec["type"] not in ("user", "assistant", "system"):
                        return FormatCheck(False, "unknown")
                    if rec.get("type") in ("user", "assistant"):
                        version = rec.get("version", "")
                        if not record_shape_known(rec):
                            return FormatCheck(False, version if isinstance(version, str) else "unknown")
                        versions.add(version)
            latest = max(versions, key=version_key) if versions else self.adapter.facts.checked_versions[0]
            return FormatCheck(True, latest, latest not in self.adapter.facts.checked_versions)
        except (OSError, ValueError, KeyError): return FormatCheck(False, "unknown")


def version_key(version):
    """Compare numeric release components rather than their spelling."""
    return tuple(int(part) for part in re.findall(r"\d+", version)), version


def chain_shape_known(record):
    """Every record used as a native parent needs the known chain envelope."""
    return (record.get("type") in _ON_THE_CHAIN and
            all(isinstance(record.get(k), str) for k in ("uuid", "sessionId", "timestamp")) and
            bool(record["uuid"]) and bool(record["sessionId"]) and
            "parentUuid" in record and
            (record["parentUuid"] is None or isinstance(record["parentUuid"], str)))


def record_shape_known(record):
    """Validate the message envelope and content consumed by the reader/writer."""
    if not all(isinstance(record.get(key), str) for key in ("uuid", "sessionId", "timestamp", "version")):
        return False
    if not record["uuid"] or not record["sessionId"] or not record["version"]:
        return False
    if "parentUuid" not in record or record["parentUuid"] is not None and not isinstance(record["parentUuid"], str):
        return False
    if type(record.get("isSidechain")) is not bool:
        return False
    message = record.get("message")
    if not isinstance(message, dict) or message.get("role") != ("user" if record["type"] == "user" else "assistant"):
        return False
    content = message.get("content")
    if isinstance(content, str):
        return True
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, dict) or not isinstance(block.get("type"), str):
            return False
        kind = block["type"]
        if kind == "text" and not isinstance(block.get("text"), str):
            return False
        if kind == "tool_use" and (not all(isinstance(block.get(k), str) for k in ("id", "name")) or not isinstance(block.get("input"), dict)):
            return False
        if kind == "tool_result" and (not isinstance(block.get("tool_use_id"), str) or not isinstance(block.get("content"), (str, list))):
            return False
        if kind == "thinking" and not isinstance(block.get("thinking"), str):
            return False
        if kind not in ("text", "tool_use", "tool_result", "thinking", "redacted_thinking", "image", "document"):
            return False
    return True

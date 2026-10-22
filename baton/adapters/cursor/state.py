"""Shape checks and durable hook observations, independent of app versions."""
from contextlib import closing
import json
import sqlite3

from ...domain.conditions import SideCondition
from ...domain.errors import NotAvailable
from ...ports.tool import FormatCheck
from .locator import valid_id


class CursorState:
    def __init__(self, adapter):
        self.adapter = adapter

    def observations(self):
        path = self.adapter.locator.inside(self.adapter.root / '.baton/cursor-turns.json')
        values = json.loads(path.read_text()) if path.exists() else {}
        for header in self.adapter.locator.headers():
            values.setdefault(header['composerId'], {'replying': True, 'replying_known': False})
        return values

    def observe(self, payload):
        """Persist native prompt/stop evidence for the later notify entry point."""
        from .writer import save_json
        ident = payload.get('chat_id', payload.get('conversation_id', payload.get('composer_id')))
        event = payload.get('hook_event_name') or {'busy': 'beforeSubmitPrompt', 'idle': 'stop', 'turn_end': 'stop'}.get(payload.get('event'))
        if not valid_id(ident) or event not in ('beforeSubmitPrompt', 'stop', 'afterAgentResponse'):
            raise NotAvailable()
        observations = self.observations()
        previous = observations.get(ident, {})
        observations[ident] = {**previous, 'open': True, 'replying': event == 'beforeSubmitPrompt', 'replying_known': True,
                              'status': payload.get('status', ''),
                              'tokens': payload.get('token_usage', payload.get('tokens', previous.get('tokens')))}
        path = self.adapter.locator.inside(self.adapter.root / '.baton/cursor-turns.json')
        save_json(path, observations)

    def replying(self, chat_id):
        value = self.observations().get(chat_id, {})
        return value.get('replying') if value.get('replying_known', 'replying' in value) else 'unknown'

    def condition(self, chat_id):
        running = self.adapter.app.running()
        try:
            self.adapter.locator.resolve(chat_id)
        except KeyError:
            return SideCondition(exists=False, app_running=running, hooks_ready=self.adapter.hooks.check().ok)
        observed = self.observations().get(chat_id, {})
        checked = self.format_version()
        return SideCondition(open=observed.get('open', False) and running,
                             replying=self.replying(chat_id), app_running=running,
                             app_started_at=self.adapter.process.started_at(),
                             hooks_ready=self.adapter.hooks.check().ok, format_known=checked.known,
                             format_new_version=checked.new_version)

    def format_version(self, chat_id=None):
        version = '18'
        new_versions = []
        try:
            with closing(self.adapter.locator.connect()) as db:
                for table, required in (('composerHeaders', {'composerId', 'value'}),
                                        ('cursorDiskKV', {'key', 'value'})):
                    columns = {row[1] for row in db.execute('PRAGMA table_info(' + table + ')')}
                    if not required <= columns:
                        return FormatCheck(False, 'schema')
            headers = ([self.adapter.locator.header(chat_id)] if chat_id is not None
                       else sorted(self.adapter.locator.headers(), key=self._updated, reverse=True))
            if not self.adapter.locator.state_db.exists():
                return FormatCheck(False, 'missing')
            readable = 0
            for header in headers:
                try:
                    data = self.adapter.locator.data(header['composerId'])
                except (KeyError, OSError):
                    if chat_id is not None:
                        return FormatCheck(False, 'missing')
                    continue
                readable += 1
                version = str(data.get('_v', 'unknown'))
                if version not in self.adapter.facts.checked_versions:
                    new_versions.append(version)
                if (type(data.get('_v')) is not int or data['_v'] < 1 or
                        data.get('composerId') != header['composerId'] or
                        not isinstance(data.get('name'), (str, type(None))) or  # untitled chats have no name
                        not isinstance(data.get('fullConversationHeadersOnly'), list) or
                        not isinstance(data.get('conversationState'), str)):
                    return FormatCheck(False, version)
                value = json.loads(header['value'])
                if value.get('composerId') != header['composerId'] or not isinstance(value.get('name'), (str, type(None))):
                    return FormatCheck(False, version)
                ids = set()
                for head, bubble in zip(data['fullConversationHeadersOnly'], self.adapter.locator.bubbles(header['composerId'], data)):
                    ident = head['bubbleId']
                    if (not isinstance(ident, str) or ident in ids or bubble.get('bubbleId') != ident or
                            'type' not in head or bubble.get('type') != head['type'] or
                            (head['type'] in (1, 2) and not any(key in bubble for key in ('toolCall', 'toolResult'))
                             and not isinstance(bubble.get('text'), str))):
                        return FormatCheck(False, version)
                    ids.add(ident)
                if chat_id is None and readable == 5:
                    break
            return FormatCheck(True, new_versions[0] if new_versions else version, bool(new_versions))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error):
            return FormatCheck(False, version)

    @staticmethod
    def _updated(header):
        try:
            value = json.loads(header['value'])
            return value.get('lastUpdatedAt') or header.get('lastUpdatedAt') or value.get('createdAt') or 0
        except (ValueError, TypeError, AttributeError):
            return header.get('lastUpdatedAt') or 0

    def target_format(self, chat_id):
        return self.format_version(chat_id)

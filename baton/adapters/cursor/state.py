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
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def observe(self, payload):
        """Persist native prompt/stop evidence for the later notify entry point."""
        from .writer import save_json
        ident = payload.get('conversation_id', payload.get('composer_id'))
        event = payload.get('hook_event_name')
        if not valid_id(ident) or event not in ('beforeSubmitPrompt', 'stop', 'afterAgentResponse'):
            raise NotAvailable()
        observations = self.observations()
        previous = observations.get(ident, {})
        observations[ident] = {**previous, 'open': True, 'replying': event == 'beforeSubmitPrompt',
                              'status': payload.get('status', ''),
                              'tokens': payload.get('token_usage', payload.get('tokens', previous.get('tokens')))}
        path = self.adapter.locator.inside(self.adapter.root / '.baton/cursor-turns.json')
        save_json(path, observations)

    def replying(self, chat_id):
        return self.observations().get(chat_id, {}).get('replying', False) is True

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

    def format_version(self):
        version = '18'
        new_versions = []
        try:
            with closing(self.adapter.locator.connect()) as db:
                for table, required in (('composerHeaders', {'composerId', 'value'}),
                                        ('cursorDiskKV', {'key', 'value'})):
                    columns = {row[1] for row in db.execute('PRAGMA table_info(' + table + ')')}
                    if not required <= columns:
                        return FormatCheck(False, 'schema')
            headers = self.adapter.locator.headers()
            if not self.adapter.locator.state_db.exists():
                return FormatCheck(False, 'missing')
            for header in headers:
                data = self.adapter.locator.data(header['composerId'])
                version = str(data.get('_v', 'unknown'))
                if version not in self.adapter.facts.checked_versions:
                    new_versions.append(version)
                if (type(data.get('_v')) is not int or data['_v'] < 1 or
                        data.get('composerId') != header['composerId'] or
                        not isinstance(data.get('name'), str) or
                        not isinstance(data.get('fullConversationHeadersOnly'), list) or
                        not isinstance(data.get('conversationState'), str)):
                    return FormatCheck(False, version)
                value = json.loads(header['value'])
                if value.get('composerId') != header['composerId'] or not isinstance(value.get('name'), str):
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
            return FormatCheck(True, new_versions[0] if new_versions else version, bool(new_versions))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error):
            return FormatCheck(False, version)

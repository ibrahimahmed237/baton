"""Private cached chat references and persisted configuration values."""
from __future__ import annotations

import json
from typing import Any


class ReadMetadata:
    """Remember observed names independently of a native chat's continued existence."""

    def remember_chat(self, tool: str, chat: str, payload: dict) -> None:
        with self.db:
            self.db.execute(
                'INSERT INTO chat_metadata(tool,chat,payload) VALUES(?,?,?) '
                'ON CONFLICT(tool,chat) DO UPDATE SET payload=excluded.payload',
                (tool, chat, json.dumps(payload, sort_keys=True, ensure_ascii=False)))

    def known_chat(self, tool: str, chat: str) -> dict | None:
        row = self.db.execute('SELECT payload FROM chat_metadata WHERE tool=? AND chat=?',
                              (tool, chat)).fetchone()
        return json.loads(row[0]) if row else None

    def settings_values(self) -> dict:
        return {row['key']: json.loads(row['value'])
                for row in self.db.execute('SELECT key,value FROM settings')}

    def save_setting(self, key: str, value: Any) -> None:
        """Persist a value; C3 owns user-facing validation and the write command."""
        with self.db:
            self.db.execute('INSERT INTO settings(key,value) VALUES(?,?) '
                            'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                            (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))

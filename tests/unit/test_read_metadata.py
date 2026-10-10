"""C2 read metadata persists without recovering or changing native writes."""
import tempfile
import unittest
from pathlib import Path

from baton.ledger.sqlite_store import Ledger
from baton.services.settings_read import SettingsRead


class ReadMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'record.sqlite')
        self.store = Ledger(self.path)
        self.addCleanup(lambda: self.store.close())

    def test_names_follow_renames_and_survive_restart_without_cross_chat_collision(self):
        self.store.remember_chat('a', 'chat', {'id': 'chat', 'name': 'First', 'folder': '/work'})
        self.store.remember_chat('b', 'chat', {'id': 'chat', 'name': 'Other'})
        self.store.remember_chat('a', 'chat', {'id': 'chat', 'name': 'Renamed', 'folder': '/work'})
        self.store.close()
        self.store = Ledger(self.path)
        self.assertEqual(self.store.known_chat('a', 'chat')['name'], 'Renamed')
        self.assertEqual(self.store.known_chat('b', 'chat')['name'], 'Other')
        self.assertIsNone(self.store.known_chat('a', 'missing'))
        cached = self.store.known_chat('a', 'chat')
        cached['name'] = 'local mutation'
        self.assertEqual(self.store.known_chat('a', 'chat')['name'], 'Renamed')

    def test_settings_persist_without_exposing_unknown_invalid_or_nonfinite_values(self):
        for key, value in {'theme': 'graphite', 'enabled': False, 'glass': 70.5,
                           'private_unknown': 'sentinel', 'threshold': 'lots'}.items():
            self.store.save_setting(key, value)
        defaults = {'theme': 'system', 'enabled': True, 'glass': 62, 'threshold': 150000}
        choices = {'theme': ('system', 'light', 'graphite')}
        bounds = {'glass': (40, 95), 'threshold': (0, None)}
        self.store.close()
        self.store = Ledger(self.path)
        reader = SettingsRead(self.store, defaults, choices=choices, bounds=bounds)
        self.assertEqual(reader.get(), {'theme': 'graphite', 'enabled': False,
                                        'glass': 70.5, 'threshold': 150000})
        for key, bad in [('theme', 'invented'), ('enabled', 1), ('glass', 96),
                         ('glass', True), ('threshold', -1), ('threshold', None)]:
            with self.subTest(key=key, bad=bad):
                self.store.save_setting(key, bad)
                self.assertEqual(reader.get()[key], defaults[key])
        with self.store.db:
            self.store.db.execute('UPDATE settings SET value=? WHERE key=?', ('NaN', 'glass'))
        self.assertEqual(reader.get()['glass'], 62)
        self.store.save_setting('threshold', 10**1000)
        self.assertEqual(reader.get()['threshold'], 10**1000)

    def test_metadata_and_configuration_never_finalize_pending_journal(self):
        ident = self.store.journal_begin(None, 'a', 'chat', 'add', '2026-10-10T00:00:00Z',
                                        {'tool': 'a', 'chat_id': 'chat', 'kind': 'add', 'data': {}})
        before = self.store.journal_entry(ident)
        self.store.remember_chat('a', 'chat', {'name': 'Still here'})
        self.store.save_setting('theme', 'light')
        SettingsRead(self.store, {'theme': 'system'}).get()
        self.assertEqual(self.store.journal_entry(ident), before)
        self.assertEqual(self.store.journal_entries(pending=True), [before])

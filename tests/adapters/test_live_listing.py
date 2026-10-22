"""CP3 listing regressions on synthetic native shapes in temporary homes."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from baton.adapters.claude import ClaudeAdapter
from baton.adapters.codex import CodexAdapter
from baton.adapters.cursor import CursorAdapter
from baton.domain.errors import NotAvailable
from baton.ports.clock import SystemClock
from baton.ledger.sqlite_store import Ledger
from baton.services.read_views import ReadViews
from tests.fixtures.claude import build as claude
from tests.fixtures.codex import build as codex
from tests.fixtures.cursor import build as cursor
from tests.fixtures.no_processes import no_processes


class LiveListing(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.guard = no_processes()
        self.guard.__enter__()
        self.addCleanup(self.guard.__exit__, None, None, None)

    def test_claude_orphan_sidebar_is_skipped_but_direct_resolution_is_missing(self):
        live = claude.build(self.root, [], chat='local_live', session='live')
        orphan = claude.build(self.root, [], chat='local_orphan', session='deleted')
        adapter = ClaudeAdapter(self.root)
        adapter.locator.session_path(orphan).unlink()
        self.assertEqual([ref.id for ref in adapter.locator.chats()], [live])
        with self.assertRaises(KeyError):
            adapter.locator.resolve(orphan)

    def test_cursor_nullable_times_and_bad_rows_do_not_break_listing(self):
        cursor.build(self.root, [])
        rows = [
            ('created', {'lastUpdatedAt': None, 'createdAt': 1767225600000}, None, None),
            ('columns', {}, 1767225600000, None),
            ('missing', {}, None, None),
            ('nulls', {'lastUpdatedAt': None, 'createdAt': None}, None, None),
            ('epoch', {'lastUpdatedAt': 0, 'createdAt': 1767225600000}, None, None),
            (None, {}, None, None),
            ('broken', 'invalid-json', None, None),
            ('array', [], None, None),
            ('bad-time', {'lastUpdatedAt': 'invalid'}, None, None),
            ('huge-time', {'lastUpdatedAt': 10**100}, None, None),
        ]
        for ident, value, created, updated in rows:
            cursor.run_sql(self.root,
                'INSERT INTO composerHeaders(composerId,value,createdAt,lastUpdatedAt) VALUES(?,?,?,?)',
                (ident, value if value == 'invalid-json' else json.dumps(value), created, updated))
        refs = {ref.id: ref for ref in CursorAdapter(self.root).locator.chats()}
        self.assertEqual(set(refs), {'cursor-fixture', 'created', 'columns', 'missing', 'nulls', 'epoch'})
        for ident in ('created', 'columns'):
            self.assertEqual(refs[ident].updated_at, '2026-01-01T00:00:00Z')
        for ident in ('missing', 'nulls'):
            self.assertEqual(refs[ident].updated_at, '')
        self.assertEqual(refs['epoch'].updated_at, '1970-01-01T00:00:00Z')

    def test_codex_listing_projects_metadata_without_authorizing_content(self):
        first = codex.build(self.root, [], folder='/chosen')
        second = codex.build(self.root, [], thread='other', folder='/elsewhere', title='Other')
        codex.insert_thread(self.root, 'archived', archived=1)
        codex.insert_thread(self.root, 'subagent', thread_source='subagent')
        codex.insert_thread(self.root, 'source-subagent', source='{"subagent":{"parent_thread_id":"parent"}}')
        codex.insert_thread(self.root, 'role', agent_role='worker')
        codex.insert_thread(self.root, 'metadata-only', rollout_path='')
        adapter = CodexAdapter(self.root)
        queries = []
        original_connect = sqlite3.connect

        def metadata_connection(*args, **kwargs):
            connection = original_connect(*args, **kwargs)
            def authorize(action, table, column, *_):
                if action == sqlite3.SQLITE_READ and table == 'threads':
                    self.assertIn(column, {'id', 'name', 'title', 'cwd', 'updated_at_ms', 'updated_at',
                                           'archived', 'thread_source', 'agent_role', 'source'})
                return sqlite3.SQLITE_OK
            connection.set_authorizer(authorize)
            connection.set_trace_callback(queries.append)
            return connection

        with patch('baton.adapters.codex.locator.sqlite3.connect', metadata_connection), \
                patch.object(Path, 'open', side_effect=AssertionError('listing opened a file')):
            refs = {ref.id: ref for ref in adapter.locator.chats()}
        self.assertEqual(set(refs), {first, second, 'metadata-only'})
        self.assertEqual(refs[second].name, 'Other')
        self.assertEqual(refs[first].updated_at, '2026-01-01T00:00:00Z')
        self.assertFalse(any('SELECT *' in sql for sql in queries))
        self.assertEqual(adapter.scope.original, frozenset())
        self.assertEqual(adapter.scope.created, set())
        for operation in (lambda: adapter.locator.resolve(first), lambda: adapter.reader.read(first),
                          lambda: adapter.reader.usage(first), lambda: adapter.writer.prepare(first, 'add'),
                          lambda: adapter.writer.add(first, []), lambda: adapter.writer.rename(first, 'changed')):
            with self.assertRaises(NotAvailable):
                operation()
        store = Ledger(':memory:')
        self.addCleanup(store.close)
        views = ReadViews(store, {'codex': adapter}, SystemClock(), {}, lambda tool: tool)
        self.assertEqual([item['ref'].id for item in views.chats('codex', '/chosen')], [first])
        selected = CodexAdapter(self.root, allowed_chat_ids=(first,))
        self.assertEqual(selected.locator.resolve(first), refs[first])
        self.assertEqual(selected.reader.read(first), [])
        with self.assertRaises(NotAvailable):
            selected.reader.read(second)

    def test_codex_listing_supports_seconds_and_optional_name_columns(self):
        codex.build(self.root, [])
        codex.run_sql(self.root, 'ALTER TABLE threads DROP COLUMN updated_at_ms')
        codex.run_sql(self.root, 'ALTER TABLE threads DROP COLUMN name')
        refs = CodexAdapter(self.root).locator.chats()
        self.assertEqual(refs[0].name, 'fixture')
        self.assertEqual(refs[0].updated_at, '2026-01-01T00:00:00Z')


class ClaudeEntryWithoutSessionId(unittest.TestCase):
    """Seen on the real Mac: a sidebar entry whose cliSessionId is empty (chat never started)."""

    def test_listing_skips_it(self):
        from baton.adapters.claude.locator import ClaudeLocator
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sidebar = root / "Library/Application Support/Claude/claude-code-sessions/a/b"
            sidebar.mkdir(parents=True)
            (sidebar / "local_x.json").write_text(json.dumps({"sessionId": "local_x", "cliSessionId": "", "title": "t"}))
            (root / ".claude/projects").mkdir(parents=True)
            self.assertEqual(ClaudeLocator(root).chats(), [])


class CursorFolderListing(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        guard = no_processes()
        guard.__enter__()
        self.addCleanup(guard.__exit__, None, None, None)
        self.chat = cursor.build(self.root, [])
        cursor.run_sql(self.root, 'UPDATE composerHeaders SET value=? WHERE composerId=?',
                       (json.dumps({'name': 'Folder fixture'}), self.chat))
        self.locator = CursorAdapter(self.root).locator

    def workspace(self, key, folder, ids):
        from contextlib import closing
        path = self.root / 'Library/Application Support/Cursor/User/workspaceStorage' / key
        path.mkdir(parents=True)
        (path / 'workspace.json').write_text(json.dumps({'folder': folder}))
        with closing(sqlite3.connect(path / 'state.vscdb')) as db, db:
            db.execute('CREATE TABLE ItemTable(key TEXT PRIMARY KEY, value BLOB)')
            db.execute('INSERT INTO ItemTable VALUES(?,?)', ('composer.composerData',
                json.dumps({'allComposers': [{'composerId': ident} for ident in ids]})))
        return path

    def transcript(self, key, ident=None):
        ident = ident or self.chat
        path = self.root / '.cursor/projects' / key / 'agent-transcripts' / ident / (ident + '.jsonl')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('not needed for folder discovery')
        return path

    def test_workspace_membership_preserves_hyphens_spaces_and_uri_characters(self):
        folder = '/Users/example/my-project/a space/#folder'
        self.workspace('first', 'file:///Users/example/my-project/a%20space/%23folder', [self.chat])
        self.workspace('other', 'file:///Users/example/other', ['other-chat'])
        self.transcript('Users-example-stale-folder')
        self.assertEqual(self.locator.resolve(self.chat).folder, folder)
        self.assertEqual(self.locator.chats()[0].folder, folder)

    def test_transcript_key_fallback_and_exact_folder_filter(self):
        folder = '/Users/ibrahimahmed/Desktop/projects/baton'
        self.transcript('Users-ibrahimahmed-Desktop-projects-baton')
        store = Ledger(':memory:')
        self.addCleanup(store.close)
        views = ReadViews(store, {'cursor': CursorAdapter(self.root)}, SystemClock(), {}, lambda tool: tool)
        self.assertEqual(self.locator.resolve(self.chat).folder, folder)
        self.assertEqual([item['ref'].id for item in views.chats('cursor', folder)], [self.chat])
        for other in (folder + '/child', folder + '/', '/Users/ibrahimahmed/Desktop/projects', '/baton'):
            self.assertEqual(views.chats('cursor', other), [])

    def test_workspace_folder_can_disambiguate_a_transcript_key_without_membership(self):
        self.workspace('first', 'file:///Users/example/my-project', ['other-chat'])
        self.transcript('Users-example-my-project')
        self.assertEqual(self.locator.chats()[0].folder, '/Users/example/my-project')

    def test_missing_folder_evidence_stays_empty_without_hiding_chat(self):
        self.assertEqual(self.locator.resolve(self.chat).folder, '')
        self.assertEqual([ref.id for ref in self.locator.chats()], [self.chat])

    def test_damaged_workspace_does_not_hide_transcript_fallback(self):
        bad = self.workspace('bad', 'file:///Users/example/bad', [self.chat])
        (bad / 'state.vscdb').write_bytes(b'broken sqlite')
        self.workspace('remote', 'vscode-remote://host/remote', [self.chat])
        self.transcript('Users-example-fallback')
        self.assertEqual(self.locator.chats()[0].folder, '/Users/example/fallback')

    def test_conflicting_workspace_membership_can_use_unique_transcript(self):
        self.workspace('first', 'file:///Users/example/one', [self.chat])
        self.workspace('second', 'file:///Users/example/two', [self.chat])
        self.transcript('Users-example-fallback')
        self.assertEqual(self.locator.resolve(self.chat).folder, '/Users/example/fallback')

    def test_duplicate_transcript_locations_leave_folder_unknown(self):
        self.transcript('Users-example-one')
        self.transcript('Users-example-two')
        self.assertEqual(self.locator.chats()[0].folder, '')

    def test_folder_lookup_ignores_symlinked_metadata_without_reading_target(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'workspace.json').write_text('{invalid')
        storage = self.root / 'Library/Application Support/Cursor/User/workspaceStorage'
        storage.mkdir(parents=True)
        (storage / 'linked').symlink_to(outside, target_is_directory=True)
        projects = self.root / '.cursor/projects'
        projects.mkdir(parents=True)
        (projects / 'linked').symlink_to(outside, target_is_directory=True)
        original = Path.read_text

        def read_text(path, *args, **kwargs):
            self.assertNotIn('linked', path.parts)
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read_text):
            self.assertEqual(self.locator.chats()[0].folder, '')

    def test_malformed_workspace_shapes_are_ignored_independently(self):
        for index, metadata in enumerate(([], {'folder': {}}, {'folder': None},
                                          {'folder': 'file://remote/Users/example/project'})):
            path = self.workspace(str(index), 'file:///Users/example/unused', [self.chat])
            (path / 'workspace.json').write_text(json.dumps(metadata))
        self.workspace('valid', 'file:///Users/example/valid', [self.chat])
        self.assertEqual(self.locator.resolve(self.chat).folder, '/Users/example/valid')

    def test_empty_header_folder_can_use_workspace_path_and_preserves_explicit_folder(self):
        cursor.run_sql(self.root, 'UPDATE composerHeaders SET value=? WHERE composerId=?',
                       (json.dumps({'folder': '', 'workspacePath': '/explicit/project'}), self.chat))
        self.workspace('first', 'file:///Users/example/other', [self.chat])
        self.assertEqual(self.locator.chats()[0].folder, '/explicit/project')

    def test_listing_reads_workspace_once_read_only_and_never_transcript_contents(self):
        cursor.build(self.root, [], ident='second-chat')
        self.workspace('first', 'file:///Users/example/project', [self.chat, 'second-chat'])
        self.transcript('Users-example-project')
        connections = []
        original_connect = sqlite3.connect
        original_read_text = Path.read_text

        def connect(database, *args, **kwargs):
            if '/workspaceStorage/' in str(database):
                self.assertTrue(database.endswith('?mode=ro'))
                connections.append(database)
            return original_connect(database, *args, **kwargs)

        def read_text(path, *args, **kwargs):
            self.assertNotEqual(path.suffix, '.jsonl')
            return original_read_text(path, *args, **kwargs)

        with patch('baton.adapters.cursor.locator.sqlite3.connect', connect), \
                patch.object(Path, 'read_text', read_text):
            self.assertEqual(len(self.locator.chats()), 2)
        self.assertEqual(len(connections), 1)

    def test_workspace_changes_are_seen_on_the_next_listing(self):
        self.assertEqual(self.locator.chats()[0].folder, '')
        path = self.workspace('first', 'file:///Users/example/first', [self.chat])
        self.assertEqual(self.locator.chats()[0].folder, '/Users/example/first')
        (path / 'workspace.json').write_text(json.dumps({'folder': 'file:///Users/example/second'}))
        self.assertEqual(self.locator.chats()[0].folder, '/Users/example/second')


class ClaudeApiRequestBlob(unittest.TestCase):
    """Seen on the real Mac (Claude 2.1.30x): a bookkeeping record with a message but no chain envelope."""

    def test_it_does_not_make_the_format_unknown(self):
        from baton.adapters.claude.state import _MESSAGE_BOOKKEEPING
        self.assertIn("api-request-blob", _MESSAGE_BOOKKEEPING)
        blob = {"type": "api-request-blob", "hash": "h", "sessionId": "s", "message": {"role": "user", "content": "x"}}
        with tempfile.TemporaryDirectory() as folder:
            adapter = ClaudeAdapter(Path(folder))
            self.assertTrue(adapter.state._text_format(json.dumps(blob) + "\n").known)


class CursorUntitledChat(unittest.TestCase):
    """Seen on the real Mac: a Cursor chat that was never named stores `name: null`."""

    def test_the_shape_rule_accepts_a_missing_name(self):
        import inspect
        from baton.adapters.cursor import state
        self.assertIn("(str, type(None))", inspect.getsource(state.CursorState.format_version))

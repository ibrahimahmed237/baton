"""Hand-built native envelopes copied from M0; no production writer reuse."""
import json
from pathlib import Path
from baton.domain.model import PROMPT, REPLY, TOOL_CALL, TOOL_RESULT

def build(root, turns, chat='local_fixture', session='fixture_session', folder='/fixture/project'):
    root = Path(root)
    sidebar = root / 'Library/Application Support/Claude/claude-code-sessions/org/account'
    sidebar.mkdir(parents=True, exist_ok=True)
    (sidebar / (chat + '.json')).write_text(json.dumps({'sessionId': chat, 'cliSessionId': session,
        'title': 'fixture', 'cwd': folder, 'lastActivityAt': 0, 'isArchived': False}))
    project = root / '.claude/projects/fixture-project'
    project.mkdir(parents=True, exist_ok=True)
    records, parent = [], None
    for turn in turns:
        for m in (turn.prompt, *turn.messages):
            r = {'uuid': m.id, 'parentUuid': parent, 'timestamp': m.at, 'sessionId': session,
                'cwd': folder, 'version': '2.1.284', 'isSidechain': False}
            if m.kind == PROMPT:
                r.update(type='user', origin={'kind': 'human'}, promptId=m.id,
                    message={'role': 'user', 'content': m.text})
            elif m.kind == REPLY:
                r.update(type='assistant', message={'role': 'assistant', 'model': 'test-model',
                    'content': [{'type': 'text', 'text': m.text}], 'usage': {'input_tokens': 10, 'output_tokens': 5}})
            elif m.kind == TOOL_CALL:
                r.update(type='assistant', message={'role': 'assistant', 'content': [{'type': 'tool_use',
                    'id': m.call_id, 'name': m.tool, 'input': m.tool_input}]})
            elif m.kind == TOOL_RESULT:
                r.update(type='user', message={'role': 'user', 'content': [{'type': 'tool_result',
                    'tool_use_id': m.call_id, 'content': m.text, 'is_error': m.is_error}]})
            else: raise ValueError(m.kind)
            records.append(r); parent = m.id
    path = project / (session + '.jsonl')
    path.write_text(''.join(json.dumps(r) + '\n' for r in records))
    return chat

class FixtureProcess:
    """Registry-driven process controls, and a simulated UI explicitly limited to tests."""
    def __init__(self, root):
        self.root = Path(root); self.is_running = False; self.pids = set(); self.calls = []
        self.visible = {}; self.adapter = None
    def alive(self, pid): return pid in self.pids
    def running(self): return self.is_running
    def started_at(self): return '2026-01-02T00:00:00Z' if self.is_running else ''
    def owns_session(self, pid, sid):
        for path in (self.root / '.claude/sessions').glob('*.json'):
            entry = json.loads(path.read_text())
            if entry.get('pid') == pid and entry.get('sessionId') == sid: return pid in self.pids
        return False
    def terminate(self, pid): self.calls.append(('terminate', pid)); self.pids.discard(pid)
    def quit(self): self.is_running = False; self.pids.clear()
    def open_app(self):
        self.is_running = True
        self.visible = {r.id: self.adapter.reader.read(r.id) for r in self.adapter.locator.chats()}
    def open_url(self, url):
        self.open_app()
        chat = url.rsplit('/', 1)[-1]
        sid = self.adapter.locator.entry(chat)[1]['cliSessionId']
        registry = self.root / '.claude/sessions'; registry.mkdir(parents=True, exist_ok=True)
        self.pids.add(1234)
        (registry / '1234.json').write_text(json.dumps({'pid': 1234, 'sessionId': sid, 'status': 'idle'}))

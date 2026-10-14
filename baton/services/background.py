"""Durable read-only jobs with bounded runner calls and immutable results."""
from datetime import datetime, timedelta
from .runner_process import RunnerProcess
from time import monotonic
from uuid import uuid4

from ..domain.errors import ChatChanged, NotAvailable


class BackgroundStopped(NotAvailable):
    note_id = 'background.stopped'


class Background:
    def __init__(self, store, clock, *, seconds=120, elapsed=monotonic, process_controller=None):
        self.store, self.clock = store, clock
        self.seconds, self.elapsed = seconds, elapsed
        self.process_controller = process_controller or RunnerProcess

    def create(self, kind, request):
        self.store.cleanup_background(self.clock.now())
        ident = 'j_' + uuid4().hex
        self.store.save_brief_artifact(ident, {'kind': kind, 'request': request,
            'created_at': self.clock.now(), 'expires_at':
            (datetime.fromisoformat(self.clock.now()) + timedelta(hours=1)).isoformat()})
        self.store.brief_cache_put(ident, {'request_id': ident, 'state': 'pending',
            **({'deadline_at': (datetime.fromisoformat(self.clock.now()) + timedelta(seconds=self.seconds)).isoformat()}
               if kind != 'relaunch' else ({'deadline_at': request['plan']['expires_at']}
                    if request.get('plan', {}).get('expires_at') else {}))})
        if kind == 'brief' and request.get('service_plan'):
            self.store.own_background_resources(ident, [('plan', request['service_plan'])])
        return ident

    def status(self, ident):
        self.store.cleanup_background(self.clock.now())
        job = self.store.brief_artifact(ident)
        value = self.store.brief_cache_get(ident)
        if value is None or datetime.fromisoformat(self.clock.now()) >= datetime.fromisoformat(value.get('expires_at', job['expires_at'])):
            raise ChatChanged()
        if value['state'] in ('pending', 'running') and value.get('deadline_at') and (
                datetime.fromisoformat(self.clock.now()) >= datetime.fromisoformat(value['deadline_at'])):
            self.stop(ident, 'deadline')
            if job['kind'] == 'relaunch':
                self.store.brief_cache_put(ident, {'request_id': ident, 'state': 'completed',
                    'result': {'applied': False, 'error': {'kind': 'idle_timeout'}}})
            value = self.store.brief_cache_get(ident)
        return value

    def stop(self, ident, state='cancelled'):
        value = self.status(ident) if state == 'cancelled' else self.store.brief_cache_get(ident)
        if value['state'] in ('pending', 'running'):
            self.store.brief_cache_put(ident, {'request_id': ident, 'state': state})
        return self.store.brief_cache_get(ident)

    def begin(self, ident):
        if self.status(ident)['state'] != 'pending':
            raise BackgroundStopped()
        value = {'request_id': ident, 'state': 'running', 'deadline_at':
                 (datetime.fromisoformat(self.clock.now()) + timedelta(seconds=self.seconds)).isoformat()}
        self.store.brief_cache_put(ident, value)
        return self.elapsed() + self.seconds

    def finish(self, ident, result):
        if self.status(ident)['state'] not in ('pending', 'running'):
            raise BackgroundStopped()
        self.store.save_brief_artifact(ident + '_result', result)
        self.store.brief_cache_put(ident, {'request_id': ident, 'state': 'completed', 'result': result,
            'expires_at': (datetime.fromisoformat(self.clock.now()) + timedelta(hours=1)).isoformat()})
        return self.status(ident)

    def ask(self, ident, runner, prompt, folder, deadline):
        """Terminate and reap the runner before returning on every exit path."""
        if self.status(ident)['state'] != 'running':
            raise BackgroundStopped()
        if self.elapsed() >= deadline:
            self.stop(ident, 'deadline')
            raise BackgroundStopped()
        process = self.process_controller(runner, prompt, folder)
        try:
            while True:
                remaining = deadline - self.elapsed()
                if remaining <= 0 or self.status(ident)['state'] != 'running':
                    if remaining <= 0:
                        self.stop(ident, 'deadline')
                    raise BackgroundStopped()
                result = process.poll(min(.05, remaining))
                if result is None:
                    continue
                if self.status(ident)['state'] != 'running' or self.elapsed() >= deadline:
                    if self.elapsed() >= deadline:
                        self.stop(ident, 'deadline')
                    raise BackgroundStopped()
                answer, error = result
                if error:
                    raise error
                return answer
        finally:
            process.close()


class BoundedRunner:
    """Preserve readiness while sharing one job deadline across fallback attempts."""
    def __init__(self, runner, background, ident, deadline, lease=None):
        self.lease = lease
        self.runner, self.background, self.ident, self.deadline = runner, background, ident, deadline

    def ready(self):
        if hasattr(self.runner, 'ready'):
            return self.runner.ready()
        from ..ports.tool import SetupFinding
        return getattr(self.runner, 'finding', SetupFinding('runner', False, 'setup.runner', {}))

    def available(self):
        # Availability can itself spawn a login probe: bound it with the job too.
        return self.ready()

    def ask(self, prompt, folder, read_only=True):
        if not read_only:
            raise NotAvailable()
        if self.lease:
            self.lease.release()
        try:
            return self.background.ask(self.ident, self.runner, prompt, folder, self.deadline)
        finally:
            if self.lease:
                self.lease.acquire()


class OpinionUnavailable(NotAvailable):
    def __init__(self, note_id, tool):
        self.note_id, self.values = note_id, {'tool': tool}
        super().__init__()


class Opinions:
    """Privacy-bound second opinions and separately approved native additions."""
    def __init__(self, store, adapters, clock, label):
        self.store, self.adapters, self.clock, self.label = store, adapters, clock, label

    def preview(self, source, chat_id, question, writer=None, turn_id=None):
        from dataclasses import asdict
        from ..domain.link import KEPT_BACK, SKIPPED
        from ..notes.catalogue import get
        from .preview import PreviewBuilder
        from .observations import canonical_sources, verified_source
        from .usage import limit_state
        from .brief_types import _fingerprint, estimate_tokens
        if source not in self.adapters:
            raise NotAvailable()
        link = self.store.link_for(source, chat_id)
        if link and (link.paused or link.removed_at):
            raise NotAvailable()
        choices = list(link.others(source)) if link else [s for s in self.adapters if s != source]
        writer = writer or next(iter(choices), None)
        if writer is None or writer == source or writer not in self.adapters or writer not in choices:
            raise NotAvailable()
        adapter = self.adapters[writer]
        if adapter.runner is None:
            raise OpinionUnavailable('brief.skipped_no_runner', writer)
        finding = adapter.runner.ready() if hasattr(adapter.runner, 'ready') else getattr(adapter.runner, 'finding', None)
        if finding is None or not finding.ok:
            raise OpinionUnavailable(finding.note_id if finding is not None and finding.note_id else 'setup.runner', writer)
        if link and writer in link.sides and limit_state(adapter.reader.usage(link.chat(writer)), self.clock.now()).blocking:
            raise OpinionUnavailable('limit.reached', writer)
        builder = PreviewBuilder(self.store, self.adapters)
        chats = dict(link.chats) if link else {source: chat_id}
        before = builder.prepare(link.id if link else None, (), chats)
        selected = None
        if link:
            observed = {s: a.reader.read(chats[s]) for s, a in self.adapters.items() if s in chats}
            content = canonical_sources(self.store, link.id, observed)
            evidence = self.store.turn_evidence(link.id)
            safe = []
            for row in self.store.turns(link.id):
                if any(row.states.get(side) in (KEPT_BACK, SKIPPED) for side in (source, writer)):
                    if row.id == turn_id:
                        raise NotAvailable()
                    continue
                actual = verified_source(self.store, link.id, row, content.get(row.id), evidence)
                safe.append(actual)
                if row.id == turn_id:
                    selected = actual
        else:
            if self.adapters[source].state.condition(chat_id).replying is not False:
                raise NotAvailable()
            safe = self.adapters[source].reader.read(chat_id)
        if turn_id is not None and selected is None:
            raise NotAvailable()
        # Mechanical context brief plus recent exchanges; selected turn stays whole.
        lines = [t.prompt.text for t in safe]
        lines += [t.prompt.text + '\n' + t.reply_text for t in safe[-3:]]
        if selected is not None:
            lines.append(selected.prompt.text + '\n' + selected.reply_text)
        prompt = get('ask.prompt').render({'conversation': '\n\n'.join(lines), 'question': question}).template
        if builder.prepare(link.id if link else None, (), chats) != before:
            raise ChatChanged()
        request = {'source': source, 'chat_id': chat_id, 'writer': writer, 'question': question,
                   'prompt': prompt, 'tokens': estimate_tokens(prompt), 'folder': before.snapshots[source]['ref']['folder'],
                   'snapshot': asdict(before)}
        request['fingerprint'] = _fingerprint(request)
        return request

    def validate(self, request):
        from .preview import PreviewBuilder
        before = request['snapshot']
        fresh = PreviewBuilder(self.store, self.adapters).prepare(before['link_id'], (),
                                {s: v['chat_id'] for s, v in before['snapshots'].items()})
        if fresh.plan_id != before['plan_id']:
            raise ChatChanged()

    def generate(self, ident, lease=None):
        from .usage import limit_state
        background = Background(self.store, self.clock)
        request = self.store.brief_artifact(ident)['request']
        deadline = background.begin(ident)
        try:
            self.validate(request)
            snapshot = request['snapshot']
            side = request['writer']
            if side in snapshot['snapshots'] and limit_state(self.adapters[side].reader.usage(
                    snapshot['snapshots'][side]['chat_id']), self.clock.now()).blocking:
                raise NotAvailable()
            if lease:
                lease.release()
            try:
                answer = background.ask(ident, self.adapters[side].runner, request['prompt'], request['folder'], deadline).strip()
            finally:
                if lease:
                    lease.acquire()
            self.validate(request)
            if not answer:
                raise NotAvailable()
            result = {'answer_id': ident, 'answer': answer, 'tokens': len(answer) // 4,
                      'seconds': max(0, self.seconds_used(background, deadline)),
                      'writer': side, 'source': request['source'], 'chat_id': request['chat_id'],
                      'question': request['question'],
                      'privacy': ({'link': request['snapshot']['record']['link'],
                         'turns': [{'id': row['id'], 'states': row['states']}
                             for row in request['snapshot']['record']['turns']]}
                         if request['snapshot']['record'] else {})}
            background.finish(ident, result)
        except BackgroundStopped:
            pass
        except Exception as error:
            if background.status(ident)['state'] == 'running':
                background.finish(ident, {'error': {'kind': type(error).__name__}})

    @staticmethod
    def seconds_used(background, deadline):
        return background.elapsed() - (deadline - background.seconds)

    def check_privacy(self, answer):
        """Refuse a reviewed answer after routing or exclusion policy changes."""
        from dataclasses import asdict
        link = self.store.link_for(answer['source'], answer['chat_id'])
        prior = answer.get('privacy', {})
        if not prior:
            if link:
                raise ChatChanged()
            return
        if not link or link.paused or asdict(link) != prior['link']:
            raise ChatChanged()
        current = {row.id: row for row in self.store.turns(link.id)}
        for row in prior['turns']:
            if row['id'] not in current or current[row['id']].states != row['states']:
                raise ChatChanged()


    def attach_reviewed(self, tool, chat_id, message_id=''):
        """Deliver confirmed answers only through their addressed prompt hook."""
        from ..notes.catalogue import get
        self.store.cleanup_background(self.clock.now())
        rows = self.store.reviewed_answers(tool, chat_id)
        if not rows:
            return ''
        adapter = self.adapters[tool]
        condition = adapter.state.condition(chat_id)
        if not condition.exists or not condition.format_known or not adapter.state.format_version().known:
            return ''
        blocks, idents = [], []
        for row in rows:
            try:
                self.check_privacy(row['payload'])
            except ChatChanged:
                continue
            blocks.append(get('ask.answer_turn').render({**row['payload'],
                'tool': self.label(row['payload']['writer'])}).template)
            idents.append(row['id'])
        if not blocks:
            return ''
        if not message_id:
            observed = adapter.reader.read(chat_id)
            message_id = observed[-1].id if observed else 'first-message'
        reply = adapter.hooks.attach_reply('\n\n'.join(blocks), None)
        self.store.consume_reviewed_answers(idents, message_id)
        return reply


    def add_preview(self, ident):
        from dataclasses import asdict
        from .preview import PreviewBuilder
        from .brief_types import _fingerprint
        result = Background(self.store, self.clock).status(ident)
        if result['state'] != 'completed' or 'answer' not in result.get('result', {}):
            raise NotAvailable()
        answer = result['result']
        source, chat_id = answer['source'], answer['chat_id']
        link = self.store.link_for(source, chat_id)
        if link and link.paused:
            raise NotAvailable()
        snapshot = PreviewBuilder(self.store, self.adapters).prepare(link.id if link else None, (),
                                       dict(link.chats) if link else {source: chat_id})
        condition = self.adapters[source].state.condition(chat_id)
        from ..domain.capabilities import WriteWindow
        available = (condition.exists and (condition.open or condition.replying is False)
                     and condition.format_known and self.adapters[source].state.format_version().known
                     and (condition.open or not (condition.app_running and self.adapters[source].facts.write_window == WriteWindow.APP_CLOSED)))
        request = {'answer_id': ident, 'answer': answer, 'snapshot': asdict(snapshot), 'available': available, 'attachment': condition.open,
                   'action': 'attach' if condition.open else 'add',
                   'note_id': 'ask.attach_preview' if condition.open else 'ask.add_preview'}
        request['fingerprint'] = _fingerprint(request)
        return request

    def add(self, request):
        from dataclasses import asdict
        from ..domain.model import Turn, Message, PROMPT
        from ..domain.capabilities import WriteWindow
        from ..notes.catalogue import get
        from .journal import Journal
        from .mapping import content_key
        from .observations import decode_turns
        self.validate(request)
        # Validate one-hour answer retention again immediately before the write.
        current = Background(self.store, self.clock).status(request['answer_id'])
        answer = request['answer']
        if current.get('result') != answer:
            raise ChatChanged()
        self.check_privacy(answer)
        source, chat_id = answer['source'], answer['chat_id']
        adapter = self.adapters[source]
        condition = adapter.state.condition(chat_id)
        if condition.open and request.get('attachment'):
            if not request['available']:
                raise NotAvailable()
            self.store.queue_reviewed_answer(answer['answer_id'], source, chat_id,
                current['expires_at'], answer)
            return {'applied': True, 'answer_id': answer['answer_id'], 'chat_id': chat_id, 'queued': True}
        if condition.open or condition.replying is not False or not condition.format_known:
            raise OpinionUnavailable('ask.add_unavailable', source)
        if not adapter.state.format_version().known or (condition.app_running and
                adapter.facts.write_window == WriteWindow.APP_CLOSED):
            raise NotAvailable()
        before = decode_turns(request['snapshot']['snapshots'][source]['turns'])
        text = get('ask.answer_turn').render({**answer, 'tool': self.label(answer['writer'])}).template
        turn = Turn(Message('opinion_' + uuid4().hex, PROMPT, text, self.clock.now()))
        link_id = request['snapshot']['link_id']
        journal = Journal(self.store, self.adapters, self.clock)
        entry = journal.begin(link_id, source, chat_id, 'add')
        try:
            self.validate(request)
            result = adapter.writer.add(chat_id, [turn])
            actual = adapter.reader.read(chat_id)
            if (result.chat_id != chat_id or len(result.local_ids) != 1 or
                    len(actual) != len(before) + 1 or actual[-1].id != result.local_ids[0] or
                    [content_key(t) for t in actual] != [content_key(t) for t in [*before, turn]]):
                raise ChatChanged()
            if (result.receipt.tool, result.receipt.chat_id, result.receipt.kind) != (source, chat_id, 'add'):
                raise ChatChanged()
            journal.commit(entry, result.receipt)
            # Native content is committed first; ordinary refresh records it.
            # A later record failure must never roll back a committed receipt.
            if link_id is not None:
                self.store.record_turns(link_id, source, [actual[-1]])
            return {'applied': True, 'answer_id': answer['answer_id'], 'chat_id': chat_id}
        except Exception as error:
            if self.store.journal_entry(entry)['state'] == 'committed':
                return {'applied': True, 'answer_id': answer['answer_id'], 'chat_id': chat_id}
            journal.fail(entry, error)
            journal.take_back(entry)
            raise


class PreviewRunner:
    """Require non-spawning readiness evidence before disclosing an agent run."""
    def __init__(self, runner):
        self.runner = runner

    def ready(self):
        from ..ports.tool import SetupFinding
        if hasattr(self.runner, 'ready'):
            return self.runner.ready()
        return getattr(self.runner, 'finding', SetupFinding('runner', False, 'setup.runner', {}))

    def available(self):
        return self.runner.available()

    def ask(self, prompt, folder, read_only=True):
        if not read_only:
            raise NotAvailable()
        return self.runner.ask(prompt, folder, read_only=True)

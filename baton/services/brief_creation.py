"""Create the exact reviewed brief with durable rollback and native verification."""
from __future__ import annotations

from dataclasses import asdict
import logging

from ..domain.errors import ChatChanged
from ..domain.link import ADDED, SHOWN
from .mapping import content_key, for_created_chat
from .journal import Guard, Journal
from .preview import PreviewBuilder
from .observations import decode_turns

logger = logging.getLogger("baton.services.brief")

from .brief_types import BriefResult

class BriefCreation:
    """Create a chat from the exact reviewed artifact and journal it."""
    def _create(self, ident, artifact):
        request = artifact['request']
        side, link_id = request['to'], request.get('link_id')
        adapter = self.adapters[side]
        guard, journal = Guard(self.store), Journal(self.store, self.adapters, self.clock)
        entry = None
        entries = []
        try:
            self.transcripts.verify(artifact['transcript_path'], artifact['transcript_digest'])
            guard.check_write(adapter, None, action='create')
            entry = journal.begin(link_id, side, None, 'create')
            entries.append(entry)
            self._validate_request(request)
            self.transcripts.verify(artifact['transcript_path'], artifact['transcript_digest'])
            guard.check_write(adapter, None, action='create')
            turns = for_created_chat(decode_turns([artifact['turn'], *artifact['originals']]), adapter.facts)
            result = adapter.writer.create(turns, self._plan_object(ident, 'create', request, artifact['writer'], [], artifact).name,
                                           self._plan_object(ident, 'create', request, artifact['writer'], [], artifact).folder)
            prepared = self.store.journal_entry(entry)
            if (result.chat_id != prepared['chat_id'] and result.receipt.tool == side
                    and result.receipt.chat_id == result.chat_id and result.receipt.kind == 'create'):
                actual_entry = self.store.journal_begin(link_id, side, result.chat_id, 'create',
                                                        self.clock.now(), asdict(result.receipt))
                entries.append(actual_entry)
                raise ChatChanged()
            if (result.receipt.tool, result.receipt.chat_id, result.receipt.kind) != (side, prepared['chat_id'], 'create'):
                raise ChatChanged()
            actual = adapter.reader.read(result.chat_id)
            if (tuple(turn.id for turn in actual) != result.local_ids
                    or len(set(result.local_ids)) != len(turns)
                    or [content_key(t) for t in actual] != [content_key(t) for t in turns]):
                raise ChatChanged()
            self._validate_request(request)
            from ..domain.capabilities import Visibility
            state = SHOWN if adapter.facts.new_chat_visible == Visibility.AT_ONCE else ADDED
            if request['kind'] == 'existing':
                event = self.store.complete_brief(link_id, side, result.chat_id, artifact['id'], result.local_ids[0],
                                                 artifact['original_ids'], list(result.local_ids[1:]), state,
                                                 entry, asdict(result.receipt), request['record'], self.clock.now(),
                                                 PreviewBuilder(self.store, self.adapters)._snapshot(side, result.chat_id))
            else:
                link_id, event = self.store.complete_brief_link(request, result.chat_id, artifact['id'],
                                        result.local_ids[0], artifact['original_ids'], list(result.local_ids[1:]),
                                        state, entry, asdict(result.receipt), self.clock.now(),
                                        PreviewBuilder(self.store, self.adapters)._snapshot(side, result.chat_id))
            return BriefResult(ident, True, result.chat_id, link_id, event)
        except Exception as error:
            rollback = ''
            if entry is not None:
                # A exception after atomic completion must never remove its
                # committed native chat or downgrade the completed receipt.
                if self.store.journal_entry(entry)['state'] == 'committed':
                    committed_chat = self.store.journal_entry(entry)['chat_id']
                    committed_link = self.store.link_for(side, committed_chat)
                    return BriefResult(ident, True, committed_chat, committed_link.id if committed_link else link_id)
                for pending in reversed(entries):
                    journal.fail(pending, error)
                    try:
                        journal.take_back(pending)
                    except Exception as failure:
                        rollback = type(failure).__name__
            return BriefResult(ident, False, error=type(error).__name__, rollback_error=rollback)


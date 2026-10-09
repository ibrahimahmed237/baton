"""E9 V1–V3 and V5–V8: switching at a limit, context use, and since you left.

Each test is named after its row in docs/features/working-across.md and checks
note ids and values; wording is checked only where the spec gives the exact sentence.
"""
import unittest

from baton.adapters.fake import FakeAdapter, FakeBackgroundRunner
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE
from baton.domain.link import ATTACHED_HISTORY, FULL_COPY
from baton.domain.model import Message, Turn, PROMPT, REPLY, TOOL_CALL
from baton.ledger.sqlite_store import Ledger
from baton.notes.catalogue import get
from baton.ports.clock import FixedClock
from baton.ports.tool import SetupFinding, Usage
from baton.services.applier import Applier
from baton.services.digest import DigestBuilder
from baton.services.limit_offer import LimitOffers, MemoryOffers
from baton.services.linker import Linker
from baton.services.noteformat import NoteRef
from baton.services.usage import UsageService

LABELS = {'claude': 'Claude', 'codex': 'Codex', 'opencode': 'OpenCode', 'cursor': 'Cursor'}
RESET = '2026-10-05T15:00:00Z'


def label(tool):
    return LABELS[tool]


def render(ref: NoteRef):
    """What the command line does with a note: the tool ids become display names."""
    values = {key: LABELS.get(value, value) if key == 'tool' or key.endswith('_tool') else value
              for key, value in ref.values.items()}
    return get(ref.id).render(values)


def at(hour, minute):
    return f'2026-10-05T{hour:02}:{minute:02}:00Z'


def make_turn(ident, start, end, calls=0, reply='done'):
    """A turn that ran `calls` tool calls; `ident` is also the prompt text."""
    work = tuple(Message(f'{ident}-call{i}', TOOL_CALL, tool='shell', tool_input={'n': i}, at=start)
                 for i in range(calls))
    return Turn(Message(ident, PROMPT, ident, start), work + (Message(ident + '-reply', REPLY, reply, end),))


class WorkingAcrossBase(unittest.TestCase):
    def setUp(self):
        self.build()

    def build(self, claude=CLAUDE_LIKE, codex=CODEX_LIKE):
        """A linked pair with empty chats, ready to receive turns."""
        if hasattr(self, 'store'):
            self.store.close()
        self.store = Ledger(':memory:')
        self.addCleanup(self.store.close)
        self.clock = FixedClock('2026-10-05T14:00:00Z')
        self.adapters = {'claude': FakeAdapter(claude, 'claude'), 'codex': FakeAdapter(codex, 'codex')}
        self.chats = {side: adapter.build_chat([], name=side + ' chat') for side, adapter in self.adapters.items()}
        self.link = self.store.link(self.chats, FULL_COPY, self.clock.now())
        self.readers = {side: adapter.reader for side, adapter in self.adapters.items()}
        self.usage = UsageService(self.readers, self.clock)

    def sync(self, side, other, ids, turns):
        """Turns written on `side` that `other` already has: in its chat and recorded as delivered."""
        self.adapters[other].chats[self.chats[other]].extend(turns)
        self.store.deliver(self.link.id, other, ids, 'shown', 'synced', local_ids=[t.id for t in turns])

    def runner(self, side, text='', error=None, ok=True):
        """A background runner for `side` that answers `text`, raises `error`, or is not ready."""
        runner = FakeBackgroundRunner(text, error)
        if not ok:
            runner.finding = SetupFinding('runner', False, 'setup.runner', {})
        self.adapters[side].runner = runner
        return runner

    def write(self, side, *turns):
        """Add turns to a side's chat and record them in the link."""
        self.adapters[side].chats[self.chats[side]].extend(turns)
        return self.store.record_turns(self.link.id, side, turns)

    def offers(self, memory=None):
        return LimitOffers(self.store, self.readers, self.clock, memory)

    def at_limit(self, side, resets_at=RESET, tokens=50000, size=200000):
        self.adapters[side].usage_values[self.chats[side]] = Usage(tokens, size, True, resets_at)


class LimitOfferScenarios(WorkingAcrossBase):
    def test_V1_linked_chat_at_limit_offers_the_other_tool_and_continuing_syncs_it(self):
        self.write('claude', make_turn('add login', at(13, 0), at(13, 5)))
        self.at_limit('claude')
        offer = self.offers().check('claude', self.chats['claude'])
        self.assertEqual(offer.note.id, 'limit.offer_linked_behind')
        self.assertEqual({key: offer.note.values[key] for key in ('tool', 'other_tool', 'time')},
                         {'tool': 'claude', 'other_tool': 'codex', 'time': '15:00'})
        self.assertEqual((offer.link_id, offer.to_side, offer.to_chat),
                         (self.link.id, 'codex', self.chats['codex']))
        shown = render(offer.note)
        self.assertEqual(shown.template, 'Claude has reached its usage limit. It resets at 15:00. '
                                         'Continue this chat in Codex?')
        self.assertEqual([(b.id, b.label) for b in shown.buttons],
                         [('continue', 'Continue in Codex'), ('not_now', 'Not now')])

        # Continue in Codex: the waiting turn is synced into the Codex chat first.
        applier = Applier(self.store, self.adapters, self.clock)
        self.assertTrue(applier.apply(applier.preview(self.link.id)).applied)
        self.assertEqual([t.prompt.text for t in self.adapters['codex'].reader.read(offer.to_chat)], ['add login'])

        # Once Codex has every turn, the offer says so (the spec's exact sentence).
        self.assertIsNone(self.offers().check('claude', self.chats['claude']))
        self.write('claude', make_turn('another limit', at(13, 10), at(13, 15)))
        self.assertTrue(applier.apply(applier.preview(self.link.id)).applied)
        fresh = self.offers().check('claude', self.chats['claude'])
        self.assertEqual(fresh.note.id, 'limit.offer_linked')
        self.assertEqual(render(fresh.note).template,
                         'Claude has reached its usage limit. It resets at 15:00. '
                         'Continue this chat in Codex? Codex already has every turn.')

    def test_V1_without_a_reset_time_the_offer_makes_no_claim_about_one(self):
        self.build(claude=OPENCODE_LIKE)
        self.write('claude', make_turn('add login', at(13, 0), at(13, 5)))
        self.at_limit('claude', resets_at=RESET)  # the tool cannot report one, so the reader drops it
        offer = self.offers().check('claude', self.chats['claude'])
        self.assertEqual(offer.note.id, 'limit.offer_linked_no_reset_behind')
        self.assertNotIn('time', offer.note.values)
        self.assertIsNone(offer.resets_at)
        self.assertNotIn('resets', render(offer.note).template)

    def test_V2_dismissed_offer_is_not_shown_again_but_the_status_keeps_the_reset_time(self):
        self.write('claude', make_turn('add login', at(13, 0), at(13, 5)))
        self.at_limit('claude')
        memory = MemoryOffers()
        self.assertIsNotNone(self.offers(memory).check('claude', self.chats['claude']))
        # Claude hits no new limit; another check shares this isolated test memory.
        self.assertIsNone(self.offers(memory).check('claude', self.chats['claude']))
        status = self.usage.side('claude', self.chats['claude'], 'codex')
        self.assertIn(NoteRef('limit.available_at', {'tool': 'claude', 'time': '15:00'}), status.notes)
        self.assertEqual(render(status.notes[1]).template, 'Claude is available again at 15:00.')

        # A new turn that ends on a limit is a new limit, and is offered again.
        self.write('claude', make_turn('add logout', at(13, 30), at(13, 35)))
        self.assertIsNotNone(self.offers(memory).check('claude', self.chats['claude']))

    def test_V2_the_setting_turns_the_offer_off_without_using_it_up(self):
        self.write('claude', make_turn('add login', at(13, 0), at(13, 5)))
        self.at_limit('claude')
        memory = MemoryOffers()
        self.assertIsNone(self.offers(memory).check('claude', self.chats['claude'], enabled=False))
        self.assertIsNotNone(self.offers(memory).check('claude', self.chats['claude']))

    def test_V2_no_offer_when_no_limit_was_reached_or_it_is_over(self):
        self.write('claude', make_turn('add login', at(13, 0), at(13, 5)))
        self.assertIsNone(self.offers().check('claude', self.chats['claude']))
        self.at_limit('claude', resets_at='2026-10-05T13:30:00Z')  # already past at 14:00
        self.assertIsNone(self.offers().check('claude', self.chats['claude']))

    def test_V3_unlinked_chat_at_limit_leads_to_the_link_dialog_with_both_ways(self):
        chat = self.adapters['claude'].build_chat([make_turn('add login', at(13, 0), at(13, 5))])
        self.adapters['claude'].usage_values[chat] = Usage(50000, 200000, True, RESET)
        offer = self.offers().check('claude', chat)
        self.assertEqual(offer.note.id, 'limit.offer_unlinked')
        self.assertEqual(offer.note.values['other_tool'], 'codex')
        self.assertIsNone(offer.link_id)
        self.assertEqual(render(offer.note).buttons[0].id, 'link_and_continue')
        self.assertEqual(offer.ways, (FULL_COPY, ATTACHED_HISTORY))
        # Both ways the dialog offers can actually be planned for this chat.
        linker = Linker(self.store, self.adapters, self.clock)
        for way in offer.ways:
            with self.subTest(way=way):
                target = self.adapters['codex'].build_chat([]) if way == ATTACHED_HISTORY else None
                self.assertEqual(linker.plan_link('claude', chat, 'codex', target, way).mode, way)


class ContextScenarios(WorkingAcrossBase):
    def status(self, side='claude', tokens=164000, size=200000, other='codex'):
        self.write(side, make_turn('add login', at(13, 0), at(13, 5)))
        self.adapters[side].usage_values[self.chats[side]] = Usage(tokens, size, False, None)
        return self.usage.side(side, self.chats[side], other)

    def test_V5_tokens_and_share_with_the_summarising_note(self):
        status = self.status()
        self.assertEqual([ref.id for ref in status.notes], ['context.in_use', 'context.nearly_full'])
        self.assertEqual((status.context.tokens, status.context.size, status.context.percent), (164000, 200000, 82))
        self.assertEqual(render(status.notes[0]).template, 'About 164,000 tokens in use, 82% of 200,000.')
        self.assertEqual(render(status.notes[1]).template,
                         'Claude will soon summarise this chat by itself. '
                         'Continuing in Codex, or handing off with a brief, avoids that.')
        self.assertEqual(status.as_contract(), {'tokens': 164000, 'size': 200000, 'percent': 82, 'limit': None})

    def test_V5_the_note_starts_above_80_percent_before_display_rounding(self):
        for tokens, nearly in ((160000, False), (160400, True), (161000, True), (200000, True)):
            with self.subTest(tokens=tokens):
                self.build()
                self.assertEqual(self.status(tokens=tokens).context.nearly_full, nearly)

    def test_V6_no_context_size_shows_only_the_token_count(self):
        for facts in (CLAUDE_LIKE, OPENCODE_LIKE):
            with self.subTest(size_known=facts.context_size_known):
                self.build(claude=facts)
                # A tool that cannot report a size, or reports none for this model.
                status = self.status(size=None if facts.context_size_known else 200000)
                self.assertEqual([ref.id for ref in status.notes], ['context.in_use_no_size'])
                self.assertEqual(render(status.notes[0]).template, 'About 164,000 tokens in use.')
                self.assertIsNone(status.context.percent)
                self.assertFalse(status.context.nearly_full)
                self.assertIsNone(status.as_contract()['size'])
                self.assertIsNone(status.as_contract()['percent'])

    def test_W3_limit_without_reset_time_never_claims_the_tool_is_back(self):
        self.build(claude=OPENCODE_LIKE)
        self.write('claude', make_turn('add login', at(13, 0), at(13, 5)))
        self.at_limit('claude')
        status = self.usage.side('claude', self.chats['claude'])
        self.assertEqual([ref.id for ref in status.notes if ref.id.startswith('limit.')], ['limit.reached'])
        self.assertTrue(status.limit.blocking)
        self.assertEqual(status.as_contract()['limit'], {'resets_at': None})
        self.clock.value = '2030-01-01T00:00:00Z'  # however long we wait
        self.assertTrue(self.usage.side('claude', self.chats['claude']).limit.blocking)

    def test_W3_available_again_is_said_with_the_time_before_and_plainly_after(self):
        self.write('claude', make_turn('add login', at(13, 0), at(13, 5)))
        self.at_limit('claude')
        before = self.usage.side('claude', self.chats['claude'])
        self.assertEqual([ref.id for ref in before.notes if ref.id.startswith('limit.')],
                         ['limit.reached', 'limit.available_at'])
        self.clock.value = '2026-10-05T15:00:00Z'
        after = self.usage.side('claude', self.chats['claude'])
        self.assertEqual([ref.id for ref in after.notes if ref.id.startswith('limit.')], ['limit.available'])
        self.assertEqual(render(after.notes[0]).template, 'Claude is available again.')
        self.assertIsNone(after.as_contract()['limit'])


class SinceYouLeftScenarios(WorkingAcrossBase):
    def setUp(self):
        super().setUp()
        self.digests = DigestBuilder(self.store, self.readers, self.clock, label)
        shared = [make_turn('start', at(13, 0), at(13, 10)), make_turn('last message here', at(13, 40), at(13, 45))]
        # Codex already has both: they were synced before the user went away.
        self.sync('claude', 'codex', self.write('claude', *shared), shared)
        # Four later Codex turns: 9 commands, and 7 file edits touching 6 different files.
        codex = [make_turn('c1', at(13, 50), at(13, 55), calls=3), make_turn('c2', at(14, 0), at(14, 5), calls=2),
                 make_turn('c3', at(14, 10), at(14, 15), calls=2), make_turn('c4', at(14, 20), at(14, 25), calls=2)]
        edits = {'c1': ['a.py', 'b.py'], 'c2': ['c.py'], 'c3': ['d.py', 'e.py'], 'c4': ['f.py', 'a.py']}
        self.adapters['codex'].changed_files.update(edits)
        self.write('codex', *codex)

    def test_V7_status_shows_exactly_the_digest(self):
        digest = self.digests.for_side(self.link.id, 'claude')
        self.assertEqual((digest.turns, len(digest.files), digest.commands), (4, 6, 9))
        self.assertEqual(digest.since, at(13, 40))
        self.assertEqual(digest.as_contract(), {'turns': 4, 'files': 6, 'commands': 9, 'since': at(13, 40)})
        self.assertEqual(self.digests.note(digest).id, 'digest.since_you_left')
        self.assertEqual(self.digests.text(digest),
                         'Since your last message here at 13:40, Codex did 4 turns, changed 6 files and ran 9 commands.')
        self.assertEqual(render(self.digests.note(digest)).buttons[0].label, 'Show what changed')

    def test_V7_the_side_that_is_up_to_date_has_no_digest(self):
        self.assertIsNone(self.digests.for_side(self.link.id, 'codex'))

    def test_V8_attached_text_starts_with_the_digest_then_the_turns(self):
        self.adapters['claude'].set_condition(self.chats['claude'], open=True, app_running=True)
        applier = Applier(self.store, self.adapters, self.clock)
        self.assertEqual(applier.preview(self.link.id).steps[0].action, 'attach')
        waiting = [t for t in self.store.turns(self.link.id) if t.states['claude'] == 'waiting']
        blocks = [f'At {t.started_at[11:16]} in Codex: {t.first_line}' for t in waiting]
        digest = self.digests.for_side(self.link.id, 'claude')
        text = self.digests.attached_text(digest, blocks)
        self.assertTrue(text.startswith('<baton-catch-up>\n' + self.digests.text(digest) + '\n\n'))
        self.assertTrue(text.endswith('\n</baton-catch-up>'))
        self.assertEqual([text.index(block) for block in blocks], sorted(text.index(block) for block in blocks))
        self.assertLess(text.index(self.digests.text(digest)), text.index(blocks[0]))
        # The hook then records them as attached; the digest is not a turn and is never recorded.
        applier.record_attached(self.link.id, 'claude', [t.id for t in waiting], 'message-1')
        states = {t.id: t.states['claude'] for t in self.store.turns(self.link.id)}
        self.assertEqual({states[t.id] for t in waiting}, {'attached'})

    def test_V8_without_a_digest_the_attached_text_is_just_the_turns(self):
        self.assertEqual(self.digests.attached_text(None, ['one', 'two']),
                         '<baton-catch-up>\none\n\ntwo\n</baton-catch-up>')



if __name__ == '__main__':
    unittest.main()

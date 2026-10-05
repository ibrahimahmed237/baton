"""Whole-turn mapping preserves public content across target capabilities."""
from dataclasses import replace
import unittest

from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE
from baton.domain.model import Message, Turn, PROMPT, REPLY, TOOL_CALL, TOOL_RESULT, TOOL_TEXT
from baton.notes.catalogue import get
from baton.services.mapping import content_key, for_created_chat, for_target, marker, title


def turn():
    return Turn(Message('prompt', PROMPT, 'do it', '2026-01-01T00:00:00Z'), (
        Message('private', 'reasoning', 'secret'),
        Message('call', TOOL_CALL, 'calling', tool='write', tool_input={'b': 2, 'a': [1]}),
        Message('result', TOOL_RESULT, 'done', call_id='call', is_error=True),
        Message('thought', 'thinking_new_version', 'secret too'),
        Message('reply', REPLY, 'finished', '2026-01-01T00:01:00Z')))


class MappingTests(unittest.TestCase):
    def test_replay_keeps_real_blocks_and_links_but_drops_reasoning(self):
        mapped = for_target(turn(), CLAUDE_LIKE)
        self.assertEqual([m.kind for m in mapped.messages], [TOOL_CALL, TOOL_RESULT, REPLY])
        self.assertEqual(mapped.messages[0], turn().messages[1])
        self.assertEqual(mapped.messages[1].call_id, mapped.messages[0].id)
        self.assertTrue(mapped.messages[1].is_error)
        self.assertEqual(mapped.prompt, turn().prompt)
        self.assertEqual(mapped.reply_text, 'finished')

    def test_flattened_calls_and_results_use_catalogue_and_keep_final_reply(self):
        mapped = for_target(turn(), CODEX_LIKE)
        self.assertEqual([m.kind for m in mapped.messages], [TOOL_TEXT, TOOL_TEXT, REPLY])
        self.assertEqual(mapped.messages[0].text, get('mapping.tool_call').render({
            'n': 1, 'tool': 'write', 'input': '{"a": [1], "b": 2}', 'text': 'calling'}).template)
        self.assertEqual(mapped.messages[1].text, get('mapping.tool_result').render({
            'n': 1, 'text': 'done', 'is_error': 'true'}).template)
        self.assertEqual(mapped.prompt.text, 'do it')
        self.assertEqual(mapped.reply_text, 'finished')
        self.assertNotIn('secret', repr(mapped))

    def test_round_trip_through_fake_writer_reader_keeps_public_content(self):
        for facts in (CLAUDE_LIKE, CODEX_LIKE):
            adapter = FakeAdapter(facts)
            mapped = for_target(turn(), facts)
            created = adapter.writer.create([mapped], 'copy', '')
            read = adapter.reader.read(created.chat_id)[0]
            self.assertEqual(read, mapped)
            self.assertEqual((read.prompt.text, read.reply_text), ('do it', 'finished'))
            self.assertEqual(content_key(read), content_key(turn()))

    def test_mapping_does_not_alias_mutable_tool_inputs(self):
        original = turn()
        mapped = for_target(original, CLAUDE_LIKE)
        mapped.messages[0].tool_input['a'].append(3)
        self.assertEqual(original.messages[1].tool_input['a'], [1])

    def test_content_key_ignores_ids_times_and_reasoning(self):
        original = turn()
        copied = replace(original, prompt=replace(original.prompt, id='new', at='later'),
                         messages=(replace(original.messages[1], id='new-call'),
                                   replace(original.messages[2], id='new-result', call_id='new-call'),
                                   replace(original.messages[-1], id='new-reply', at='later')))
        self.assertEqual(content_key(original), content_key(copied))
        self.assertEqual(content_key(original), content_key(for_target(original, CODEX_LIKE)))

    def test_content_key_matches_full_content_not_count_or_final_reply_only(self):
        original = turn()
        for changed in (
            replace(original, prompt=replace(original.prompt, text='different prompt')),
            replace(original, messages=original.messages[:-1] + (replace(original.messages[-1], text='other'),)),
            replace(original, messages=(replace(original.messages[1], tool_input={'path': 'other'}),
                                        original.messages[2], original.messages[-1])),
            replace(original, messages=(original.messages[1], replace(original.messages[2], text='other'),
                                        original.messages[-1])),
            replace(original, messages=(original.messages[1], replace(original.messages[2], is_error=False),
                                        original.messages[-1]))):
            self.assertNotEqual(content_key(original), content_key(changed))

    def test_multiple_call_result_links_use_stable_ordinals(self):
        first = turn().messages[1]
        second = replace(first, id='second', tool='read')
        original = replace(turn(), messages=(first, second,
                         Message('result', TOOL_RESULT, 'out', call_id='second'), turn().messages[-1]))
        mapped = for_target(original, CODEX_LIKE)
        self.assertIn('call 2:', mapped.messages[2].text)
        self.assertNotEqual(content_key(original), content_key(replace(original,
            messages=(first, second, replace(original.messages[2], call_id='call'), original.messages[-1]))))

    def test_orphan_result_pairing_keeps_distinct_references_without_local_ids(self):
        original = Turn(Message('p', PROMPT, 'request'), (
            Message('one', TOOL_RESULT, 'out', call_id='missing-one'),
            Message('two', TOOL_RESULT, 'out', call_id='missing-two'),
            Message('r', REPLY, 'done')))
        same_call = replace(original, messages=(original.messages[0],
                    replace(original.messages[1], call_id='missing-one'), original.messages[2]))
        self.assertNotEqual(content_key(original), content_key(same_call))
        self.assertEqual(content_key(original), content_key(for_target(original, CODEX_LIKE)))

    def test_incomplete_turn_keeps_empty_final_reply_and_mapping_is_idempotent(self):
        original = replace(turn(), messages=turn().messages[:-1])
        mapped = for_target(original, CODEX_LIKE)
        self.assertEqual(original.reply_text, '')
        self.assertEqual(mapped.reply_text, '')
        self.assertEqual(for_target(mapped, CODEX_LIKE), mapped)
        self.assertEqual(content_key(original), content_key(mapped))
        self.assertEqual(content_key(for_target(mapped, CLAUDE_LIKE)), content_key(original))

    def test_title_tag_and_marker_are_separate_from_user_prompt(self):
        original = turn()
        mapped = for_created_chat([original], CODEX_LIKE)
        self.assertEqual(mapped[0].prompt, original.prompt)
        self.assertEqual(mapped[0].reply_text, original.reply_text)
        self.assertEqual(title('chat', 'source'), 'chat')
        self.assertEqual(title('chat', 'source', True),
                         get('history.title_tag').render({'tool': 'source'}).template + ' chat')
        self.assertEqual(marker('source'), get('history.marker').render({'tool': 'source'}).template)
        self.assertEqual(content_key(mapped[0]), content_key(original))
        self.assertEqual(for_created_chat([], CODEX_LIKE), [])

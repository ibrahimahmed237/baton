"""Prefer Cursor's transcript export, falling back to display records."""
import re
import json

from ...domain.model import TOOL_CALL
from ...ports.tool import Usage
from .records import display_messages, transcript_messages, turns_from_messages


class CursorReader:
    def __init__(self, adapter):
        self.adapter = adapter

    def read(self, chat_id):
        locator = self.adapter.locator
        bubbles = locator.bubbles(chat_id)
        messages = display_messages(bubbles)
        transcript = locator.transcript(chat_id)
        if transcript:
            messages = transcript_messages(transcript.read_bytes(), messages,
                                           {b["bubbleId"] for b in bubbles if "batonMessage" in b})
        return turns_from_messages(messages)

    def usage(self, chat_id):
        data = self.adapter.locator.data(chat_id)
        tokens = data.get('contextTokensUsed', 0)
        size = data.get('contextTokenLimit', data.get('contextWindowSize'))
        percent = data.get('contextUsagePercent', 0)
        if size is None and isinstance(percent, (int, float)) and percent > 0:
            size = round(tokens * 100 / percent)
        reached = bool(data.get('usageLimitReached', data.get('isAtUsageLimit', False)))
        transcript = self.adapter.locator.transcript(chat_id)
        if transcript:
            endings = [json.loads(line) for line in transcript.read_bytes().splitlines() if line.strip()]
            endings = [record for record in endings if record.get('type') == 'turn_ended']
            if endings:
                reason = str(endings[-1].get('reason', endings[-1].get('failure_reason', ''))).lower()
                reached = reached or any(word in reason for word in ('rate_limit', 'usage_limit', 'quota'))
        return Usage(tokens, size, reached, None)

    def files_changed(self, turn):
        paths = []
        for message in turn.messages:
            if message.kind != TOOL_CALL:
                continue
            values = message.tool_input
            if message.tool.lower() in ('write', 'edit', 'multiedit') and isinstance(values, dict):
                path = values.get('path', values.get('file_path'))
                if path and path not in paths:
                    paths.append(path)
            for path in re.findall(r'^\*\*\* (?:Add File|Update File|Delete File): (.+)$',
                                   str(values), re.M):
                if path not in paths:
                    paths.append(path)
        return paths

    def commands_run(self, turn):
        return sum(m.kind == TOOL_CALL and m.tool.rsplit('.', 1)[-1] in
                   ('shell', 'shell_command', 'exec_command', 'run_terminal_cmd') for m in turn.messages)

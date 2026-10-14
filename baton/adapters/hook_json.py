"""JSON edits preserving every unchanged value's original byte spelling."""
import json


def rewrite(source, desired, identities=None):
    decoder = json.JSONDecoder(object_pairs_hook=_unique)
    original = decoder.decode(source)

    def skip(pos):
        while pos < len(source) and source[pos].isspace(): pos += 1
        return pos

    def render(pos, old, new, path=()):
        pos = skip(pos)
        _, end = decoder.raw_decode(source, pos)
        if old == new: return source[pos:end], end
        if isinstance(old, dict) and isinstance(new, dict):
            cursor, parts = skip(pos + 1), []
            for key, value in old.items():
                start = cursor
                _, key_end = decoder.raw_decode(source, cursor)
                value_start = skip(skip(key_end) + 1)
                text, value_end = render(value_start, value, new.get(key), (*path, key))
                if key in new: parts.append(source[start:value_start] + text)
                cursor = skip(value_end)
                if source[cursor:cursor+1] == ',': cursor = skip(cursor + 1)
            parts.extend(json.dumps(key) + ': ' + json.dumps(value) for key, value in new.items() if key not in old)
            return '{' + ', '.join(parts) + '}', end
        if isinstance(old, list) and isinstance(new, list):
            cursor, available = skip(pos + 1), []
            for value in old:
                _, stop = decoder.raw_decode(source, cursor)
                available.append((value, cursor, stop, len(available)))
                cursor = skip(stop)
                if source[cursor:cursor+1] == ',': cursor = skip(cursor + 1)
            parts = []
            for value in new:
                origin = (identities or {}).get(id(value))
                match = next((i for i, pair in enumerate(available) if origin == (*path, pair[3])), None) if origin is not None else next((i for i, pair in enumerate(available) if pair[0] == value), None)
                if match is not None:
                    old_value, start, stop, index = available.pop(match)
                    parts.append(render(start, old_value, value, (*path, index))[0])
                else:
                    parts.append(json.dumps(value))
            return '[' + ', '.join(parts) + ']', end
        return json.dumps(new), end

    if original == desired: return source
    start = skip(0)
    text, end = render(start, original, desired)
    return source[:start] + text + source[end:]


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('duplicate key')
        result[key] = value
    return result


def read(source):
    value = json.loads(source, object_pairs_hook=_unique)
    if not isinstance(value, dict): raise ValueError('expected object')
    return value

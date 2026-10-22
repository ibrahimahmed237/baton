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
        if isinstance(old, (dict, list)) and isinstance(new, type(old)):
            cursor, items = skip(pos + 1), []
            pairs = old.items() if isinstance(old, dict) else enumerate(old)
            for key, value in pairs:
                start = cursor
                if isinstance(old, dict):
                    _, key_end = decoder.raw_decode(source, cursor)
                    cursor = skip(skip(key_end) + 1)
                value_start = cursor
                _, stop = decoder.raw_decode(source, cursor)
                items.append((key, value, start, value_start, stop))
                cursor = skip(stop)
                if source[cursor:cursor+1] == ',': cursor = skip(cursor + 1)
            selected = []
            if isinstance(old, dict):
                for item in items:
                    if item[0] in new: selected.append((item, new[item[0]]))
                added = [json.dumps(k) + ': ' + json.dumps(v) for k, v in new.items() if k not in old]
            else:
                available, added = list(items), []
                for value in new:
                    origin = (identities or {}).get(id(value))
                    if origin is not None:
                        match = next((i for i, item in enumerate(available) if origin == (*path, item[0])), None)
                    else:
                        match = next((i for i, item in enumerate(available) if item[1] == value), None)
                    if match is None: added.append(json.dumps(value))
                    else: selected.append((available.pop(match), value))
            if not items:
                return source[pos:end-1] + ', '.join(added) + source[end-1:end], end
            text = source[pos:items[0][2]]
            previous = None
            for item, value in selected:
                key, old_value, start, value_start, stop = item
                if previous is not None:
                    index = items.index(previous)
                    text += source[previous[4]:items[index + 1][2]] if index + 1 < len(items) else ', '
                text += source[start:value_start] + render(value_start, old_value, value, (*path, key))[0]
                previous = item
            if added:
                if selected: text += ', '
                text += ', '.join(added)
            return text + source[items[-1][4]:end], end
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

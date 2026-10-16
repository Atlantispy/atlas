"""Bounded, read-only JSON structure census; no scientific interpretation.

``scan(path, check=..., select=...)`` streams a UTF-8 file in 64 KiB reads.
Offsets are half-open byte offsets, including the value's brackets/quotes but
excluding adjacent whitespace. ``fields`` contains exact root-object values.
``nested_fields`` aggregates paths with at most two object keys; array indices
are omitted there, never in ``selected``. Aggregate byte totals may overlap
their parents and are not a partition of the file. Repeated aggregates have
first_start/last_end, deliberately not a misleading contiguous start/end span.
Content-ID object keys (64 lowercase hexadecimal characters) use a null path
component in aggregates, so data-map entries do not become separate field names.
Exact root fields and selected spans always retain the actual keys.

Rational candidates are exactly two canonical-spelling hexadecimal strings,
with a positive denominator, as emitted by mesh_tables._Pools.rational. This
census does not establish reduction, typed admission, or scientific validity.
Their widths include sign and 0x prefix; bit widths exclude these. No arbitrary
precision conversion or whole-document json.loads is performed.
"""

import json
import os
import re
import stat
from dataclasses import dataclass


CHUNK_BYTES = 64 * 1024
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_TOKEN_BYTES = 1024 * 1024
MAX_DEPTH = 128
MAX_KEY_BYTES = 1024
MAX_KEYS_PER_OBJECT = 131072
MAX_ACTIVE_KEYS = 131072
MAX_ACTIVE_KEY_BYTES = 8 * 1024 * 1024
MAX_AGGREGATE_PATHS = 4096
MAX_SELECTED = 100000
MAX_REPORT_PATH_BYTES = 16 * 1024 * 1024

_SPACE = re.compile(rb'[ \t\r\n]+')
_STRING_STOP = re.compile(rb'["\\\x00-\x1f]')
_ATOM_END = re.compile(rb'[ \t\r\n{}\[\]:,"]')
_NUMBER = re.compile(rb'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?')
_ESCAPE_HEX = re.compile(rb'[0-9a-fA-F]{4}')
_HEX = re.compile(r'(?:0x(?:0|[1-9a-f][0-9a-f]*)|-0x[1-9a-f][0-9a-f]*)\Z')
_PUNCTUATION = b'{}[]:,'
_COUNTS = ('objects', 'arrays', 'scalars', 'strings', 'integers', 'numbers',
           'booleans', 'nulls', 'keys')


class StructureJSONError(ValueError):
    """Malformed JSON, changed input, or an explicit census bound was reached."""


@dataclass(slots=True)
class _Token:
    kind: str
    start: int
    end: int
    value: object = None


def _rational_stats():
    return {'count': 0, 'pair_count': 0, 'string_count': 0,
            'max_numerator_chars': 0, 'max_denominator_chars': 0,
            'max_encoded_bytes': 0, 'min_numerator_bits': None,
            'max_numerator_bits': 0, 'min_denominator_bits': None,
            'max_denominator_bits': 0}


def _add_rational(stats, numerator, denominator, encoded_bytes):
    stats['count'] += 1  # Count is the number of candidate pairs, not strings.
    stats['pair_count'] += 1
    stats['string_count'] += 2
    stats['max_numerator_chars'] = max(stats['max_numerator_chars'], numerator[0])
    stats['max_denominator_chars'] = max(stats['max_denominator_chars'], denominator[0])
    stats['max_encoded_bytes'] = max(stats['max_encoded_bytes'], encoded_bytes)
    for name, value in (('numerator', numerator[1]), ('denominator', denominator[1])):
        low = stats['min_' + name + '_bits']
        stats['min_' + name + '_bits'] = value if low is None else min(low, value)
        stats['max_' + name + '_bits'] = max(stats['max_' + name + '_bits'], value)


def _hex_summary(value):
    if not _HEX.fullmatch(value):
        return None
    negative = value.startswith('-')
    digits = value[3 if negative else 2:]
    bits = (len(digits) - 1) * 4 + int(digits[0], 16).bit_length()
    return len(value), bits, not negative and value != '0x0'


class _Lexer:
    def __init__(self, stream, check):
        self.stream, self.check = stream, check
        self.buffer = b''
        self.pos = self.base = self.read_bytes = 0
        self.eof = False
        self.whitespace_bytes = self.punctuation_bytes = 0
        self.token_count = 0
        self.max_token_bytes = 0
        self.path = ()

    def fail(self, message, position=None):
        where = self.base + self.pos if position is None else position
        location = json.dumps(list(self.path), ensure_ascii=True, separators=(',', ':'))
        raise StructureJSONError(f'{message} at byte {where}, path {location}')

    def refill(self):
        self.check()  # Exceptions, including cancellation, propagate unchanged.
        dropped = self.pos
        self.base += dropped
        self.buffer = self.buffer[dropped:]
        self.pos = 0
        chunk = self.stream.read(CHUNK_BYTES)
        self.read_bytes += len(chunk)
        if self.read_bytes > MAX_SOURCE_BYTES:
            self.fail('source byte bound exceeded')
        self.buffer += chunk
        self.eof = not chunk
        return dropped

    def _bound(self, end):
        if end - self.pos > MAX_TOKEN_BYTES:
            self.fail('token byte bound exceeded')

    def _finish(self, kind, end, value=None):
        self._bound(end)
        token = _Token(kind, self.base + self.pos, self.base + end, value)
        self.max_token_bytes = max(self.max_token_bytes, end - self.pos)
        self.pos = end
        self.token_count += 1
        if self.token_count % 4096 == 0:
            self.check()
        return token

    def next(self):
        while True:
            if self.pos == len(self.buffer):
                if self.eof:
                    return _Token('eof', self.read_bytes, self.read_bytes)
                self.refill()
                continue
            whitespace = _SPACE.match(self.buffer, self.pos)
            if whitespace is None:
                break
            self.whitespace_bytes += whitespace.end() - self.pos
            self.pos = whitespace.end()
        byte = self.buffer[self.pos]
        if byte in _PUNCTUATION:
            self.punctuation_bytes += 1
            return self._finish(chr(byte), self.pos + 1)
        if byte == 34:
            return self.string()
        cursor = self.pos
        while True:
            delimiter = _ATOM_END.search(self.buffer, cursor)
            end = delimiter.start() if delimiter else len(self.buffer)
            self._bound(end)
            if delimiter or self.eof:
                break
            cursor = end - self.refill()
        raw = self.buffer[self.pos:end]
        if raw in (b'true', b'false'):
            return self._finish('boolean', end)
        if raw == b'null':
            return self._finish('null', end)
        if not _NUMBER.fullmatch(raw):
            self.fail('invalid JSON token')
        integer = b'.' not in raw and b'e' not in raw and b'E' not in raw
        return self._finish('integer' if integer else 'number', end,
                            len(raw) - raw.startswith(b'-') if integer else None)

    def string(self):
        cursor = self.pos + 1
        while True:
            stop = _STRING_STOP.search(self.buffer, cursor)
            if stop is None:
                self._bound(len(self.buffer))
                if self.eof:
                    self.fail('unterminated JSON string')
                cursor = len(self.buffer) - self.refill()
                continue
            cursor = stop.start()
            byte = self.buffer[cursor]
            if byte == 34:
                end = cursor + 1
                self._bound(end)
                try:
                    # Decode exactly one bounded token, enforcing strict UTF-8.
                    value = json.loads(self.buffer[self.pos:end].decode('utf-8'))
                except (ValueError, UnicodeError) as error:
                    self.fail(f'invalid JSON string ({error})')
                return self._finish('string', end, value)
            if byte < 32:
                self.fail('unescaped control character in JSON string', self.base + cursor)
            while len(self.buffer) - cursor < 2:
                if self.eof:
                    self.fail('unterminated string escape')
                cursor -= self.refill()
            escape = self.buffer[cursor + 1]
            width = 6 if escape == 117 else 2
            while len(self.buffer) - cursor < width:
                if self.eof:
                    self.fail('incomplete unicode escape')
                cursor -= self.refill()
            if escape == 117:
                if not _ESCAPE_HEX.fullmatch(self.buffer[cursor + 2:cursor + 6]):
                    self.fail('invalid unicode escape', self.base + cursor)
            elif escape not in b'"\\/bfnrt':
                self.fail('invalid string escape', self.base + cursor)
            cursor += width
            self._bound(cursor)


class _Census:
    def __init__(self, lexer, select):
        self.lexer, self.select = lexer, select
        self.counts = dict.fromkeys(_COUNTS, 0)
        self.rationals = _rational_stats()
        self.root_rationals = None
        self.fields, self.selected = [], []
        self.aggregates = {}
        self.active_key_bytes = self.report_path_bytes = self.selection_count = 0
        self.active_keys = self.max_object_keys = self.max_active_keys = 0
        self.key_bytes = self.scalar_bytes = self.max_integer_digits = 0
        self.max_depth = 0
        self.token = lexer.next()

    def fail(self, message):
        self.lexer.fail(message, self.token.start)

    def advance(self):
        old = self.token
        self.token = self.lexer.next()
        return old

    def expect(self, kind):
        if self.token.kind != kind:
            self.fail('expected ' + kind)
        return self.advance()

    def retain_path(self, path):
        # Surrogate escapes are legal JSON; use surrogatepass for bound accounting.
        charge = sum(len(part.encode('utf-8', 'surrogatepass')) if isinstance(part, str)
                     else 8 for part in path)
        self.report_path_bytes += charge
        if self.report_path_bytes > MAX_REPORT_PATH_BYTES:
            self.fail('retained report path byte bound exceeded')

    def aggregate(self, path, kind, start, end):
        keys = tuple(None if len(part) == 64 and not part.strip('0123456789abcdef') else part
                     for part in path if isinstance(part, str))
        if not keys or len(keys) > 2 or not isinstance(path[-1], str):
            return
        row = self.aggregates.get(keys)
        if row is None:
            if len(self.aggregates) >= MAX_AGGREGATE_PATHS:
                self.fail('aggregate path bound exceeded')
            self.retain_path(keys)
            row = {'path': list(keys), 'occurrences': 0, 'bytes': 0,
                   'first_start': start, 'last_end': end, 'kind_counts': {}}
            if None in keys:
                row['content_id_wildcard'] = True
            self.aggregates[keys] = row
        row['occurrences'] += 1
        row['bytes'] += end - start
        row['first_start'] = min(start, row['first_start'])
        row['last_end'] = max(end, row['last_end'])
        row['kind_counts'][kind] = row['kind_counts'].get(kind, 0) + 1
        if row['occurrences'] == 1:
            row.update(start=start, end=end, kind=kind)
        else:
            for key in ('start', 'end', 'kind'):
                row.pop(key, None)

    def value(self, path, depth):
        self.lexer.path = path
        if depth > MAX_DEPTH:
            self.fail('depth bound exceeded')
        self.max_depth = max(self.max_depth, depth)
        token = self.token
        kind = {'{': 'object', '[': 'array'}.get(token.kind, token.kind)
        if kind not in ('object', 'array', 'string', 'integer', 'number', 'boolean', 'null'):
            self.fail('expected JSON value')
        selected = self.select is not None and self.select(path, kind)
        if selected:
            self.selection_count += 1
            if self.selection_count > MAX_SELECTED:
                self.fail('selected span bound exceeded')
            self.retain_path(path)
        summary = items = None
        if kind == 'object':
            self.counts['objects'] += 1
            end, items = self.object(path, depth)
        elif kind == 'array':
            self.counts['arrays'] += 1
            end, items = self.array(path, depth)
        else:
            self.counts['scalars'] += 1
            plural = {'string': 'strings', 'integer': 'integers', 'number': 'numbers',
                      'boolean': 'booleans', 'null': 'nulls'}[kind]
            self.counts[plural] += 1
            self.scalar_bytes += token.end - token.start
            if kind == 'string':
                summary = _hex_summary(token.value)
            elif kind == 'integer':
                self.max_integer_digits = max(self.max_integer_digits, token.value)
            end = self.advance().end
        self.lexer.path = path
        self.aggregate(path, kind, token.start, end)
        if selected:
            self.selected.append({'path': list(path), 'kind': kind, 'start': token.start,
                                  'end': end, 'bytes': end - token.start, 'items': items})
        return kind, token.start, end, summary, items

    def object(self, path, depth):
        self.advance()
        seen = set()
        retained_bytes = 0
        try:
            if self.token.kind == '}':
                return self.advance().end, 0
            while True:
                self.lexer.path = path
                key_token = self.expect('string')
                key = key_token.value
                key_size = len(key.encode('utf-8', 'surrogatepass'))
                if key_size > MAX_KEY_BYTES:
                    self.fail('object key byte bound exceeded')
                if key in seen:
                    self.fail('duplicate object key')
                if len(seen) >= MAX_KEYS_PER_OBJECT:
                    self.fail('object key count bound exceeded')
                if self.active_keys >= MAX_ACTIVE_KEYS:
                    self.fail('total active object key count bound exceeded')
                if self.active_key_bytes + key_size > MAX_ACTIVE_KEY_BYTES:
                    self.fail('active object key byte bound exceeded')
                seen.add(key)
                self.active_keys += 1
                self.max_object_keys = max(self.max_object_keys, len(seen))
                self.max_active_keys = max(self.max_active_keys, self.active_keys)
                retained_bytes += key_size
                self.active_key_bytes += key_size
                self.key_bytes += key_token.end - key_token.start
                self.counts['keys'] += 1
                self.expect(':')
                root_field = not path
                if root_field:
                    before = self.counts.copy()
                    self.root_rationals = _rational_stats()
                kind, start, end, _, items = self.value(path + (key,), depth + 1)
                self.lexer.path = path
                if root_field:
                    self.fields.append({'path': [key], 'kind': kind, 'start': start,
                                        'end': end, 'bytes': end - start, 'items': items,
                                        'counts': {name: self.counts[name] - before[name]
                                                   for name in _COUNTS},
                                        'rational_strings': self.root_rationals})
                    self.root_rationals = None
                if self.token.kind == '}':
                    return self.advance().end, len(seen)
                self.expect(',')
        finally:
            self.active_key_bytes -= retained_bytes
            self.active_keys -= len(seen)

    def array(self, path, depth):
        start = self.advance().start
        count, pair = 0, []
        if self.token.kind == ']':
            return self.advance().end, 0
        while True:
            kind, _, _, summary, _ = self.value(path + (count,), depth + 1)
            self.lexer.path = path
            if count < 2:
                pair.append(summary if kind == 'string' else None)
            count += 1
            if self.token.kind == ']':
                end = self.advance().end
                if count == 2 and all(pair) and pair[1][2]:
                    _add_rational(self.rationals, pair[0], pair[1], end - start)
                    if self.root_rationals is not None:
                        _add_rational(self.root_rationals, pair[0], pair[1], end - start)
                return end, count
            self.expect(',')


def scan(path, *, check=lambda: None, select=None):
    """Return a complete bounded census, or raise without a partial report.

    ``select(path_tuple, kind)`` sees each value once; return true to retain its
    exact span. Selected spans are returned in source order. Caller callbacks
    must remain bounded and their exceptions propagate unchanged. No values are
    retained; callers may read selected small spans under their own row bounds.
    Public MAX_* constants document refusal limits, not suggested silent retries.
    """
    check()
    with open(path, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise StructureJSONError('regular input file required')
        if before.st_size > MAX_SOURCE_BYTES:
            raise StructureJSONError('source byte bound exceeded')
        lexer = _Lexer(stream, check)
        census = _Census(lexer, select)
        root_kind, _, _, _, root_items = census.value((), 0)
        if census.token.kind != 'eof':
            census.fail('trailing JSON content')
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ino, before.st_dev) != (
                after.st_size, after.st_mtime_ns, after.st_ino, after.st_dev):
            raise StructureJSONError('source changed during census')
        if lexer.read_bytes != before.st_size:
            raise StructureJSONError('source size changed during census')
    check()
    accounted = (lexer.whitespace_bytes + lexer.punctuation_bytes + census.key_bytes
                 + census.scalar_bytes)
    if accounted != lexer.read_bytes:
        raise StructureJSONError('internal lexical byte accounting differs')
    return {'schema': 'atlas.json-structure-census.v1', 'filebytes': lexer.read_bytes,
            'root_kind': root_kind, 'root_items': root_items, 'fields': census.fields,
            'nested_fields': list(census.aggregates.values()),
            'selected': sorted(census.selected, key=lambda item: (item['start'], -item['end'])),
            'counts': census.counts, 'rational_strings': census.rationals,
            'max_integer_decimal_digits': census.max_integer_digits,
            'max_object_keys': census.max_object_keys, 'max_active_keys': census.max_active_keys,
            'max_depth': census.max_depth, 'max_token_bytes': lexer.max_token_bytes,
            'lexical_bytes': {'whitespace': lexer.whitespace_bytes,
                              'punctuation': lexer.punctuation_bytes,
                              'keys': census.key_bytes, 'scalars': census.scalar_bytes},
            'root_overhead_bytes': lexer.read_bytes - sum(row['bytes'] for row in census.fields)
                                   if root_kind == 'object' else None,
            'limits': {'source_bytes': MAX_SOURCE_BYTES, 'token_bytes': MAX_TOKEN_BYTES,
                       'depth': MAX_DEPTH, 'key_bytes': MAX_KEY_BYTES,
                       'keys_per_object': MAX_KEYS_PER_OBJECT,
                       'active_keys': MAX_ACTIVE_KEYS,
                       'active_key_bytes': MAX_ACTIVE_KEY_BYTES,
                       'aggregate_paths': MAX_AGGREGATE_PATHS, 'selected': MAX_SELECTED,
                       'report_path_bytes': MAX_REPORT_PATH_BYTES, 'chunk_bytes': CHUNK_BYTES}}

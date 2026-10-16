"""Pre-interval-2 exact-width gate: recording only (coordinator approval, 16 Oct 2026).

Exact integers are bounded by MAX_INTEGER_BYTES = 1 MiB (8,388,608 bits) in every
compact record. The widest IV1 value is the heat ledger's per-cell storage residual,
2,054,539 bits (24.5%). Its width follows the end mesh's exact pose history, which
grows by one rotation step per interval, so it grows linearly, not geometrically.
See probes/step8/claude-20261015/heat-width/heat-magnitude-width-20261016.md.

This module records the widest numerator and denominator bits and the value count of
every exact field, per record kind and root field, plus the trajectory step count. It
projects interval 2 as W1+(W1-W0) and interval 3 as W1+2*(W1-W0). The gate passes
only if every projected interval-2 width is at most 50% of the limit and every
interval-3 projection at most 100%. A field absent at interval 0 takes W0 = 0 (the
larger projection). Where the difference ledger shows an approved input change, a
width may differ from r9; compare() lists every difference for that ledger to explain.

Records are scanned as their canonical JSON streams (sorted keys, ASCII, no spaces),
chunk by chunk, so any record's stream can be used: a sealed reader's or an in-memory
view's. A rational is a two-element array of canonical hex strings ("0x..",
"-0x.."); any other hex string counts as an integer (numerator width only). Bit
lengths come from the hex digit count and the first digit; no integer is parsed.
Nothing here writes, changes a value or touches an identity.
"""
import json
import re

LIMIT_BITS = 8*(1 << 20)
INTERVAL2_SHARE = 0.5
INTERVAL3_SHARE = 1.0
TRAJECTORY_KEY = 'trajectory_segments'

_HEX_DIGITS = re.compile(rb'[0-9a-f]*')
_PLAIN = re.compile(rb'[^"\\]*')
_STRUCTURE = re.compile(rb'["{}\[\],:]')
_NIBBLE = {ord(c): int(c, 16).bit_length() for c in '0123456789abcdef'}
_QUOTE, _ESCAPE, _MINUS, _ZERO, _X = map(ord, '"\\-0x')


def hex_bits(text):
    """Bit length of a canonical hex integer string, without parsing it."""
    digits = text[3:] if text.startswith('-') else text[2:]
    if not text.lstrip('-').startswith('0x') or not digits or digits.strip('0123456789abcdef'):
        raise ValueError('canonical hex integer required')
    return 0 if digits == '0' else 4*(len(digits)-1)+_NIBBLE[ord(digits[0])]


class _Container:
    __slots__ = ('elements', 'first', 'key_next', 'kind')

    def __init__(self, kind):
        self.kind, self.elements, self.first, self.key_next = kind, 0, [], kind == 'object'


class _String:
    __slots__ = ('digits', 'escape', 'first', 'is_key', 'key', 'state')

    def __init__(self, is_key):
        self.is_key, self.state, self.digits, self.first, self.escape, self.key = is_key, 'start', 0, None, False, b''


class StreamScanner:
    """Incremental canonical-JSON width scanner for one record."""

    def __init__(self):
        self.fields, self.trajectory_steps = {}, None
        self._stack, self._root_key, self._string, self._scalar = [], None, None, False

    def _field(self):
        name = self._root_key if self._root_key is not None else '$'
        field = self.fields.get(name)
        if field is None:
            field = self.fields[name] = {'count': 0, 'integers': 0,
                                         'max_numerator_bits': 0, 'max_denominator_bits': 0}
        return field

    def _integer(self, bits):
        field = self._field()
        field['integers'] += 1
        field['max_numerator_bits'] = max(field['max_numerator_bits'], bits)

    def _value(self, bits):
        """One complete value (bits for a hex string, else None) in the current container."""
        if not self._stack:
            if bits is not None:
                self._integer(bits)
            return
        top = self._stack[-1]
        top.elements += 1
        if top.kind == 'array' and top.elements <= 2:
            top.first.append(bits)
        elif bits is not None:
            self._integer(bits)

    def _scalar_done(self):
        if self._scalar:
            self._scalar = False
            self._value(None)

    def _close(self, kind):
        self._scalar_done()
        top = self._stack.pop() if self._stack else None
        if top is None or top.kind != kind:
            raise ValueError('mismatched canonical JSON container')
        if kind == 'array':
            if top.elements == 2 and None not in top.first:
                field = self._field()
                field['count'] += 1
                field['max_numerator_bits'] = max(field['max_numerator_bits'], top.first[0])
                field['max_denominator_bits'] = max(field['max_denominator_bits'], top.first[1])
            else:
                for bits in top.first:
                    if bits is not None:
                        self._integer(bits)
            if self._root_key == TRAJECTORY_KEY and len(self._stack) == 1:
                self.trajectory_steps = top.elements
        if not self._stack:
            self._root_key = None
        self._value(None)

    def _end_string(self):
        string, self._string = self._string, None
        assert string is not None
        if string.is_key:
            if len(self._stack) == 1:
                self._root_key = json.loads(b'"'+string.key+b'"')
            return
        bits = None
        if string.state == 'digits' and string.first is not None:
            bits = 0 if string.digits == 1 and string.first == _ZERO else 4*(string.digits-1)+_NIBBLE[string.first]
        self._value(bits)

    def _in_string(self, data, at, end):
        s = self._string
        assert s is not None
        while at < end:
            if s.escape:
                s.escape, s.state = False, 'other'
                if s.is_key:
                    s.key += data[at:at+1]
                at += 1
                continue
            byte = data[at]
            if byte == _QUOTE:
                if s.state not in ('digits', 'other'):
                    s.state = 'other'
                self._end_string()
                return at+1
            if byte == _ESCAPE:
                s.escape, s.state = True, 'other'
                if s.is_key:
                    s.key += b'\\'
                at += 1
                continue
            if s.state == 'start':
                s.state = 'minus' if byte == _MINUS else 'zero' if byte == _ZERO else 'other'
            elif s.state == 'minus':
                s.state = 'zero' if byte == _ZERO else 'other'
            elif s.state == 'zero':
                s.state = 'x' if byte == _X else 'other'
            elif s.state in ('x', 'digits'):
                run = _HEX_DIGITS.match(data, at).end()-at
                if run:
                    if s.state == 'x':
                        s.first, s.state = byte, 'digits'
                    s.digits += run
                    at += run
                    continue
                s.state = 'other'
                continue
            else:
                stop = _PLAIN.match(data, at).end()
                if s.is_key:
                    s.key += data[at:stop]
                at = stop
                continue
            if s.is_key:
                s.key += data[at:at+1]
            at += 1
        return at

    def feed(self, data):
        data = bytes(data)
        at, end = 0, len(data)
        while at < end:
            if self._string is not None:
                at = self._in_string(data, at, end)
                continue
            match = _STRUCTURE.search(data, at)
            if match is None:
                self._scalar = True
                break
            if match.start() > at:
                self._scalar = True
            at = match.start()
            byte = data[at:at+1]
            at += 1
            if byte == b'"':
                top = self._stack[-1] if self._stack else None
                self._string = _String(top is not None and top.kind == 'object' and top.key_next)
                if top is not None and top.kind == 'object' and top.key_next:
                    top.key_next = False
            elif byte == b'{':
                self._stack.append(_Container('object'))
            elif byte == b'[':
                self._stack.append(_Container('array'))
            elif byte == b']':
                self._close('array')
            elif byte == b'}':
                self._close('object')
            elif byte == b',':
                self._scalar_done()
                if self._stack and self._stack[-1].kind == 'object':
                    self._stack[-1].key_next = True
            # ':' needs no state: the key was consumed and the value follows.
        return self

    def finish(self):
        if self._stack or self._string is not None:
            raise ValueError('incomplete canonical JSON record stream')
        self._scalar_done()
        return dict(sorted(self.fields.items()))


class WidthTable:
    """Exact widths per record kind and root field for one interval's records."""

    def __init__(self, interval):
        self.interval, self.records, self.trajectory_steps = interval, {}, None

    def scan(self, kind, chunks):
        """Scan one record's canonical JSON chunks and merge it under ``kind``."""
        scanner = StreamScanner()
        for chunk in chunks:
            scanner.feed(chunk)
        fields = scanner.finish()
        merged = self.records.setdefault(kind, {})
        for name, value in fields.items():
            old = merged.setdefault(name, {'count': 0, 'integers': 0,
                                           'max_numerator_bits': 0, 'max_denominator_bits': 0})
            old['count'] += value['count']
            old['integers'] += value['integers']
            old['max_numerator_bits'] = max(old['max_numerator_bits'], value['max_numerator_bits'])
            old['max_denominator_bits'] = max(old['max_denominator_bits'], value['max_denominator_bits'])
        if scanner.trajectory_steps is not None:
            self.trajectory_steps = max(self.trajectory_steps or 0, scanner.trajectory_steps)
        return fields

    def widths(self):
        return {(kind, name): max(row['max_numerator_bits'], row['max_denominator_bits'])
                for kind, fields in self.records.items() for name, row in fields.items()}

    def wire(self):
        return {'schema': 'atlas.exact-width-table.v1', 'interval': self.interval,
                'trajectory_steps': self.trajectory_steps, 'limit_bits': LIMIT_BITS,
                'records': {kind: dict(sorted(fields.items())) for kind, fields in sorted(self.records.items())}}

    @classmethod
    def from_wire(cls, value):
        """A recorded table (an earlier reader's verdict) back as a gate operand; closed shape."""
        row_fields = {'count', 'integers', 'max_numerator_bits', 'max_denominator_bits'}
        if (type(value) is not dict or set(value) != {'schema', 'interval', 'trajectory_steps', 'limit_bits', 'records'}
                or value['schema'] != 'atlas.exact-width-table.v1' or value['limit_bits'] != LIMIT_BITS
                or type(value['interval']) is not int or type(value['records']) is not dict
                or not (value['trajectory_steps'] is None or type(value['trajectory_steps']) is int)):
            raise ValueError('recorded exact-width table required')
        for fields in value['records'].values():
            if type(fields) is not dict or not all(
                    type(row) is dict and set(row) == row_fields and
                    all(type(count) is int and count >= 0 for count in row.values())
                    for row in fields.values()):
                raise ValueError('recorded exact-width rows required')
        table = cls(value['interval'])
        table.records = {kind: {name: dict(row) for name, row in fields.items()}
                         for kind, fields in value['records'].items()}
        table.trajectory_steps = value['trajectory_steps']
        if table.wire() != value:
            raise ValueError('recorded exact-width table is not canonical')
        return table


def gate(root, interval1):
    """The approved pre-interval-2 gate: one row per interval-1 field."""
    before, after = root.widths(), interval1.widths()
    rows, passed = [], True
    for key in sorted(after):
        w1, w0 = after[key], before.get(key, 0)
        w2, w3 = w1+(w1-w0), w1+2*(w1-w0)
        ok = w2 <= INTERVAL2_SHARE*LIMIT_BITS and w3 <= INTERVAL3_SHARE*LIMIT_BITS
        passed = passed and ok
        rows.append({'record': key[0], 'field': key[1], 'w0_bits': w0, 'w0_measured': key in before,
                     'w1_bits': w1, 'w2_projected_bits': w2, 'w3_projected_bits': w3,
                     'w2_share': w2/LIMIT_BITS, 'w3_share': w3/LIMIT_BITS, 'passed': ok})
    return {'schema': 'atlas.exact-width-gate.v1', 'passed': passed, 'limit_bits': LIMIT_BITS,
            'interval2_share': INTERVAL2_SHARE, 'interval3_share': INTERVAL3_SHARE,
            'root_trajectory_steps': root.trajectory_steps,
            'interval1_trajectory_steps': interval1.trajectory_steps, 'rows': rows}


def compare(reference, measured):
    """Every field whose widths or counts differ; the difference ledger explains each."""
    out = []
    for kind in sorted(set(reference) | set(measured)):
        left, right = reference.get(kind, {}), measured.get(kind, {})
        for name in sorted(set(left) | set(right)):
            if left.get(name) != right.get(name):
                out.append({'record': kind, 'field': name, 'reference': left.get(name),
                            'measured': right.get(name)})
    return out

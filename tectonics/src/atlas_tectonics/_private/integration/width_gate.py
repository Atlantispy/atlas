"""Pre-interval-2 exact-width gate: recording only (approved gate policy).

Exact integers are bounded by MAX_INTEGER_BYTES = 1 MiB (8,388,608 bits) in every
compact record. The widest IV1 value is the heat ledger's per-cell storage residual,
2,054,539 bits (24.5%). Its width follows the end mesh's exact pose history, which
grows by one rotation step per interval, so it grows linearly, not geometrically.
See the retained exact-width measurement notes.

This module records the widest numerator and denominator bits and the value count of
every exact field, per record kind and root field. It
projects interval 2 as W1+(W1-W0) and interval 3 as W1+2*(W1-W0). The gate passes
only if every projected interval-2 width is at most 50% of the limit and every
interval-3 projection at most 100%. A field absent at interval 0 takes W0 = 0 (the
larger projection). Where the difference ledger shows an approved input change, a
width may differ from r9; compare() lists every difference for that ledger to explain.
After interval N >= 2, gate_next() applies the same rule one step on to the parent's
recorded table and this interval's: W(N+1) = W(N)+(W(N)-W(N-1)) at most 50% and
W(N+2) = W(N)+2*(W(N)-W(N-1)) at most 100% (approved); gate() stays the
interval-1 record.

Records are scanned as their canonical JSON streams (sorted keys, ASCII, no spaces),
chunk by chunk, so any record's stream can be used: a sealed reader's or an in-memory
view's. A rational is a two-element array of canonical hex strings ("0x..",
"-0x.."); any other hex string counts as an integer (numerator width only). Bit
lengths come from the hex digit count and the first digit; no integer is parsed.
Nothing here writes, changes a value or touches an identity.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
import json
import re
from typing import cast

LIMIT_BITS = 8*(1 << 20)
INTERVAL2_SHARE = 0.5
INTERVAL3_SHARE = 1.0

_HEX_DIGITS = re.compile(rb'[0-9a-f]*')
_PLAIN = re.compile(rb'[^"\\]*')
_STRUCTURE = re.compile(rb'["{}\[\],:]')
_NIBBLE = {ord(c): int(c, 16).bit_length() for c in '0123456789abcdef'}
_QUOTE, _ESCAPE, _MINUS, _ZERO, _X = map(ord, '"\\-0x')


def hex_bits(text):
    """Bit length of a canonical hex integer string, without parsing it."""
    digits = text[3:] if text.startswith('-') else text[2:]
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
        self.fields = {}
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
        top = cast(_Container, self._stack.pop() if self._stack else None)
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
        if not self._stack:
            self._root_key = None
        self._value(None)

    def _end_string(self):
        string, self._string = cast(_String, self._string), None
        if string.is_key:
            if len(self._stack) == 1:
                self._root_key = json.loads(b'"'+string.key+b'"')
            return
        bits = None
        if string.state == 'digits' and string.first is not None:
            bits = 0 if string.digits == 1 and string.first == _ZERO else 4*(string.digits-1)+_NIBBLE[string.first]
        self._value(bits)

    def _in_string(self, data, at, end):
        s = cast(_String, self._string)
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
        self._scalar_done()
        return dict(sorted(self.fields.items()))


class WidthTable:
    """Exact widths per record kind and root field for one interval's records."""

    def __init__(self, interval):
        self.interval, self.records = interval, {}

    def scan(self, kind, chunks):
        """Scan one record's canonical JSON chunks and merge it under ``kind``."""
        scanner = StreamScanner()
        for chunk in chunks:
            scanner.feed(chunk)
        return self.merge(kind, scanner.finish())

    def merge(self, kind, fields):
        """Merge one finished scan of a record under ``kind``; returns its fields."""
        merged = self.records.setdefault(kind, {})
        for name, value in fields.items():
            old = merged.setdefault(name, {'count': 0, 'integers': 0,
                                           'max_numerator_bits': 0, 'max_denominator_bits': 0})
            old['count'] += value['count']
            old['integers'] += value['integers']
            old['max_numerator_bits'] = max(old['max_numerator_bits'], value['max_numerator_bits'])
            old['max_denominator_bits'] = max(old['max_denominator_bits'], value['max_denominator_bits'])
        return fields

    def widths(self):
        return {(kind, name): max(row['max_numerator_bits'], row['max_denominator_bits'])
                for kind, fields in self.records.items() for name, row in fields.items()}

    def wire(self):
        return {'schema': 'atlas.exact-width-table.v1', 'interval': self.interval,
                'limit_bits': LIMIT_BITS,
                'records': {kind: dict(sorted(fields.items())) for kind, fields in sorted(self.records.items())}}

    @classmethod
    def from_wire(cls, value):
        """A recorded table (an earlier reader's verdict) back as a gate operand; closed shape."""
        row_fields = {'count', 'integers', 'max_numerator_bits', 'max_denominator_bits'}
        for fields in value['records'].values():
            if type(fields) is not dict or not all(
                    type(row) is dict and set(row) == row_fields and
                    all(type(count) is int and count >= 0 for count in row.values())
                    for row in fields.values()):
                raise ValueError('recorded exact-width rows required')
        table = cls(value['interval'])
        table.records = {kind: {name: dict(row) for name, row in fields.items()}
                         for kind, fields in value['records'].items()}
        return table


class OptionalScan:
    """A width scan riding on a proving stream. Item 14's rule: an optional speed-up never turns a stream that
    passes into a refusal, so any scanner error turns the scan off and the reader streams the record itself."""

    def __init__(self):
        self._scanner = StreamScanner()

    def feed(self, chunk):
        if self._scanner is not None:
            try:
                self._scanner.feed(chunk)
            except Exception:  # noqa: BLE001 - any scanner error only turns the optional scan off
                self._scanner = None

    def result(self):
        """The scanned fields, or None if the scan was turned off."""
        if self._scanner is None:
            return None
        try:
            return self._scanner.finish()
        except Exception:  # noqa: BLE001 - as in feed
            self._scanner = None
            return None


_PROOFS = ContextVar('atlas_reader_proofs', default=None)


class Proofs:
    """What the reader's own block proved on one store object: identity and widths per whole descriptor.

    The key is the canonical JSON of the whole descriptor, so a different segment, recipe or identity misses.
    Only a stream that passed its descriptor comparison enters, and only with its scan on. The one exception is a
    recipe row at publish: it enters from the original's own stream, with no comparison (our own write, C05430).
    """

    def __init__(self, store):
        self.store, self._proved = store, {}

    @staticmethod
    def _key(descriptor):
        return json.dumps(descriptor, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)

    def enter(self, descriptor, identity, scan):
        result = scan.result()
        if result is not None:
            self._proved[self._key(descriptor)] = (dict(identity), result)

    def get(self, descriptor):
        """(identity {'bytes', 'sha256'}, fields), or None."""
        return self._proved.get(self._key(descriptor))

    def __len__(self):
        return len(self._proved)


@contextmanager
def collect_proofs(store):
    """The reader's block on its sealed store: proving opens on ``store`` inside it record their widths.

    Nothing outside the block scans or enters a proof; the interval producer opens one around its advance
    (unit A). The proofs end with the block,
    on any exit.
    """
    proofs = Proofs(store)
    token = _PROOFS.set(proofs)
    try:
        yield proofs
    finally:
        _PROOFS.reset(token)


def active(store):
    """The current reader block's proofs if it collects for this very store object, else None."""
    proofs = _PROOFS.get()
    return proofs if proofs is not None and proofs.store is store else None


def collecting():
    """True inside any collect_proofs block. A CompactMesh render then scans its widths onto the mesh object
    itself (unit A), so no store match is needed."""
    return _PROOFS.get() is not None


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
            'rows': rows}


def gate_next(previous, current):
    """The approved gate before interval N+1, N >= 2: gate()'s rule one step on, one row per interval-N field.

    ``previous`` is interval N-1's table (the parent reader's recorded widths) and ``current``
    interval N's. A field absent at N-1 takes W(N-1) = 0 (the larger projection). Interval 1
    keeps gate() and its v1 record; anything but two consecutive tables from interval 2 on refuses.
    """
    before, after = previous.widths(), current.widths()
    rows, passed = [], True
    for key in sorted(after):
        w, w_previous = after[key], before.get(key, 0)
        w_next, w_after_next = w+(w-w_previous), w+2*(w-w_previous)
        ok = w_next <= INTERVAL2_SHARE*LIMIT_BITS and w_after_next <= INTERVAL3_SHARE*LIMIT_BITS
        passed = passed and ok
        rows.append({'record': key[0], 'field': key[1], 'w_previous_bits': w_previous,
                     'w_previous_measured': key in before, 'w_bits': w, 'w_next_projected_bits': w_next,
                     'w_after_next_projected_bits': w_after_next, 'w_next_share': w_next/LIMIT_BITS,
                     'w_after_next_share': w_after_next/LIMIT_BITS, 'passed': ok})
    return {'schema': 'atlas.exact-width-gate.v2', 'interval': current.interval,
            'next_interval': current.interval+1, 'passed': passed, 'limit_bits': LIMIT_BITS,
            'next_share': INTERVAL2_SHARE, 'after_next_share': INTERVAL3_SHARE,
            'rows': rows}


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

# Unit A (design duplicate-removal-r1 A-1): the width pass the interval producer and the reader share, moved here
# from reopen_fresh_restart with its bytes unchanged but for function-local imports. require raises ValueError here
# (ReaderRefused there).
ROOT_RECORDS = frozenset(('state', 'mesh'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _scanned(table, kind, chunks):
    """Scan one record's canonical chunks into ``table``; returns the bytes' SHA-256 and length."""
    digest, size = sha256(), 0

    def counted():
        nonlocal size
        for chunk in chunks:
            digest.update(chunk)
            size += memoryview(chunk).nbytes
            yield chunk
    table.scan(kind, counted())
    return {'sha256': digest.hexdigest(), 'nbytes': size}


def _proved_records(store, refs, *, budget, scope, source_producer, table, proofs=None):
    """One stream per record is both its proof and its widths (repeat fix K12).

    A record the restore already proved in this reader block, under this exact descriptor, is adopted with the
    widths its proving stream scanned (I1; proofs from WG.collect_proofs). The rest are opened with
    prove=False and streamed here: the SHA-256 and length are compared with the reference before the widths count.
    """
    from atlas_tectonics._private.integration.geometry import spatial_records_patch as SR
    result, misses = {}, {}
    for name, descriptor in refs.items():
        hit = None if proofs is None else proofs.get(descriptor)
        if hit is None:
            misses[name] = descriptor
            continue
        identity, fields = hit
        table.merge(name, fields)
        result[name] = {'sha256': descriptor['sha256'], 'nbytes': descriptor['bytes']}
    if not misses:
        return result
    with SR.open_records(store, misses, budget=budget, scope=scope, source_producer=source_producer,
                         prove=False) as opened:
        for name, child in opened.items():
            proved = {'sha256': misses[name]['sha256'], 'nbytes': misses[name]['bytes']}
            with child.iter_json() as stream:
                def parts(stream=stream):
                    for block in stream:
                        with block:
                            yield block.value
                require(_scanned(table, name, parts()) == proved,
                        'width stream differs from the proved record: '+name)
            result[name] = proved
            child.close()
    return result


def _mesh(workflow, scope, table):
    from atlas_tectonics._private.integration.geometry import spatial_indexed_patch as SI
    held = workflow.exterior_state.indexed_record()
    mesh = held.value['thermal_mesh']
    scan = getattr(mesh, '_width_scan', None)
    if scan is not None:
        # I3: the restore's open rendered and proved these bytes in this reader block and scanned them as it did.
        identity = mesh.identity()
        table.merge('mesh', scan)
        result = {'sha256': identity.sha256, 'nbytes': identity.canonical_bytes}
    else:
        result = _scanned(table, 'mesh', SI.iter_logical_json(mesh))
    del held, mesh
    return result


def _native_records(store, root_key, refs, *, budget, table):
    """A native root's records: each is one canonical JSON byte array of the root, streamed in
    stored chunks; the width stream is the proved bytes (SHA-256 and length equal the header)."""
    result = {}
    for name in sorted(refs):
        reference = refs[name]
        chunks = (memoryview(chunk).cast('B') for _, chunk in store.iter_chunks(root_key, reference['array'],
                                                                                budget=budget))
        proved = {'sha256': reference['sha256'], 'nbytes': reference['bytes']}
        require(_scanned(table, name, chunks) == proved, 'width stream differs from the proved record: '+name)
        result[name] = proved
    return result


def root_record_identities(workflow, table):
    """The fresh root's records, widths recorded on the proved bytes.

    Workflow.create stores the sequence-0 exterior state natively (record_blobs
    state and mesh, as JSON byte arrays of the root); a compact root (record_blobs
    state plus a compact v3 mesh reference) is read through its proved records.
    """
    store, budget, head = workflow._store, workflow._budget, workflow._head
    scope = getattr(store, 'scope', None)
    state = head['exterior_state']
    refs = dict(state['record_blobs'])
    if 'compact_mesh' in state:
        result = _proved_records(store, refs, budget=budget, scope=scope,
                                 source_producer=state['compact_mesh']['source_producer'], table=table)
        result['mesh'] = _mesh(workflow, scope, table)
    else:
        result = _native_records(store, head['key'], refs, budget=budget, table=table)
    return result


def _successor_records(workflow, table, proofs):
    """The successor's records, proved and their widths recorded: (result, scope)."""
    store, budget, head = workflow._store, workflow._budget, workflow._head
    scope = getattr(store, 'scope', None)
    state = head['exterior_state']
    refs = dict(state['record_blobs'])
    exchange = head['exterior_advance']['record_blobs']
    refs.update(exchange)
    for header, kind in (('differential_certification', 'certification'), ('differential_geometry', 'differential')):
        refs[kind] = head[header]['record_blob']
    result = _proved_records(store, refs, budget=budget, scope=scope,
                             source_producer=state['compact_mesh']['source_producer'], table=table, proofs=proofs)
    return result, scope


def successor_record_identities(workflow, table, proofs=None):
    """reopen_prepared_restart.endpoint_record_identities in one proved pass, widths recorded.

    Same inventory, refusals and canonical result; the records are opened once
    for both the identity proof and the width stream.
    """
    from atlas_tectonics._private.integration.geometry import partition_native_patch as PN
    from atlas_tectonics._private.integration.geometry import partition_workflow_patch as PW
    from atlas_tectonics._private.integration import reopen_prepared_restart as RO
    result, scope = _successor_records(workflow, table, proofs)
    partition = PN.compact_view(workflow.differential_partition)
    result['partition'] = PW.descriptor_stats(partition)
    result['mesh'] = _mesh(workflow, scope, table)
    return RO.canonical_record_identities(result, successor=True)


def producer_widths(workflow, store, number):
    """Unit A: the interval producer's width table, from the proofs its publications entered in this collector
    block on ``store``; a record with no proof is streamed. Returns the runner record's widths and width_proofs.
    The partition is not read here: it has no widths, and the producer holds no compact view of it."""
    proofs = active(store)
    table = WidthTable(number)
    _, scope = _successor_records(workflow, table, proofs)
    _mesh(workflow, scope, table)
    return {'widths': table.wire(), 'width_proofs': 0 if proofs is None else len(proofs)}

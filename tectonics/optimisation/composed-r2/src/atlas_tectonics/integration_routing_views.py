"""Operation-local routing projections; no issued record is modified.

The caller owns/charges decoded input and must treat returned views as read-only
and scoped to this context. Only selected descendants survive, never the full
record. Exact interning preserves canonical values; nested dictionary insertion
order follows the first representative (issued JSON is already key-sorted).
Diagnostic workspace and exception ownership belong to the enclosing operation.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import ExitStack
import json
import math
import re
import sys
import weakref

from .integration_volume_bounds import _Arena
from .integration_regional_inventory import _width
from .resources import WorkBudget, _GrowingLease


_ROW = frozenset(('voxel_index', 'source_chart_id', 'material_angular_velocity_rad_s',
    'plate_id', 'source_key', 'radial_band', 'chart', 'finite_stock_id',
    'constraints', 'components'))
_REQUIRED = _ROW - {'finite_stock_id'}
_PART = frozenset(('logical_cell_id', 'parent_cell_id', 'partition_path', 'constraints'))
_STRING_SPECIAL = re.compile(rb'["\\]')
_JSON_NUMBER = re.compile(rb'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?')


def _decoded_json_capacity(encoded):
    """Count a conservative decoded graph capacity without decoding a record.

    Issued JSON has already passed its canonical codec. This is an allocation
    counter, not a replacement validator. It walks bytes with constant-sized
    state, including escaped Unicode, and never builds a token list or graph.
    Strings allow four bytes per character plus an 80-byte header; containers
    include table/list growth and references separately from their children.
    Integers allow four bits per decimal digit and runtime-sized integer limbs.
    Counts also dominate the existing recursive _width convention. Repeated
    values/keys are counted separately, without assuming decoder interning.
    """
    if type(encoded) is not bytes:
        raise TypeError('issued canonical JSON bytes required')
    size, pos, capacity = len(encoded), 0, 0
    while pos < size:
        token = encoded[pos]
        if token == 34:  # string, including dictionary keys
            pos += 1
            characters = 0
            while True:
                special = _STRING_SPECIAL.search(encoded, pos)
                if special is None:
                    raise ValueError('unterminated issued JSON string')
                end = special.start()
                # A raw UTF-8 sequence has no more characters than bytes.
                characters += end-pos
                if encoded[end] == 34:
                    pos = end+1
                    break
                if end+1 >= size:
                    raise ValueError('unterminated issued JSON escape')
                if encoded[end+1] == 117:  # \uXXXX, possibly a surrogate pair
                    if end+6 > size:
                        raise ValueError('short issued JSON Unicode escape')
                    code = int(encoded[end+2:end+6], 16)
                    pos = end+6
                    if (0xd800 <= code <= 0xdbff and
                            encoded.startswith(b'\\u', pos) and pos+6 <= size and
                            0xdc00 <= int(encoded[pos+2:pos+6], 16) <= 0xdfff):
                        pos += 6
                else:
                    if encoded[end+1] not in b'"\\/bfnrt':
                        raise ValueError('invalid issued JSON escape')
                    pos = end+2
                characters += 1
            capacity += 80+4*characters
        elif token in b'{[':
            capacity += 192 if token == 123 else 128
            pos += 1
        elif token == 58:  # dictionary entry/table capacity
            capacity += 96
            pos += 1
        elif token == 44:  # list growth/reference capacity (also safe for maps)
            capacity += 16
            pos += 1
        elif token in b'}] \r\n\t':
            pos += 1
        elif token == 45 or 48 <= token <= 57:
            number = _JSON_NUMBER.match(encoded, pos)
            if number is None:
                raise ValueError('invalid issued JSON number')
            end = number.end()
            if any(encoded.find(mark, pos, end) >= 0 for mark in (b'.', b'e', b'E')):
                capacity += 64
            else:
                digits = end-pos-(token == 45)
                limbs = (4*digits+sys.int_info.bits_per_digit-1)//sys.int_info.bits_per_digit
                capacity += max(64, sys.getsizeof(0)+limbs*sys.int_info.sizeof_digit)
            pos = end
        else:
            for literal in (b'true', b'false', b'null'):
                if encoded.startswith(literal, pos):
                    capacity += 64
                    pos += len(literal)
                    break
            else:
                raise ValueError('invalid issued JSON token')
    return capacity


def _decode_workspace(encoded):
    # json.loads(bytes) first makes a Unicode input. Four bytes per input byte
    # covers its widest representation; the fixed allowance covers codec state.
    return 65536+4*len(encoded)


def _json_definition(value):
    """Avoid tuple/list or non-string-key collisions in canonical JSON keys."""
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise TypeError('constraint definitions require plain JSON string keys')
        for child in value.values():
            _json_definition(child)
    elif type(value) is list:
        for child in value:
            _json_definition(child)
    elif type(value) not in (str, int, float, bool, type(None)):
        raise TypeError('constraint definitions require plain JSON values')
    elif type(value) is float and not math.isfinite(value):
        raise ValueError('constraint definitions require finite JSON numbers')


class RoutingViews:
    """One explicit owner for compact views and optional exact-definition pool."""
    def __init__(self, budget, *, intern=False):
        if type(budget) is not WorkBudget or type(intern) is not bool:
            raise TypeError('explicit WorkBudget and boolean intern flag required')
        self._budget, self._intern = budget, intern
        self._stack, self._pool = ExitStack(), {}
        self._lease = _GrowingLease(budget)
        self._active = self._closed = False
        self._stats = dict(view_bytes=0, pool_bytes=0, unique_definitions=0,
                          projected_supports=0, base_bytes=4096)

    @property
    def stats(self):
        return dict(self._stats, closed=self._closed)

    def __enter__(self):
        if self._active or self._closed:
            raise RuntimeError('routing views cannot be re-entered')
        try:
            self._stack.enter_context(self._budget.reserve(4096, category='routing-view-owner'))
            self._stack.enter_context(self._lease)
            self._active = True
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        if not self._closed:
            self._active = False
            self._closed = True
            self._pool.clear()
            self._stack.close()

    def __exit__(self, *args):
        self.close()
        return False

    def project(self, record):
        if not self._active:
            raise RuntimeError('routing projection requires its active context')
        if type(record) is not dict or not _REQUIRED <= record.keys():
            raise ValueError('complete decoded support routing/cell metadata required')
        source, parts = record['constraints'], record['components']
        if type(source) is not dict or type(parts) is not list:
            raise TypeError('plain constraint dictionary and component list required')
        used = set()
        for part in parts:
            if type(part) is not dict or not _PART <= part.keys():
                raise ValueError('complete component routing/cell metadata required')
            for name, _sign in part['constraints']:
                if type(name) is not str or name not in source:
                    raise ValueError('component literal has no named definition')
                used.add(name)
        # Caller-owned input is not recharged. This covers canonical-key codec,
        # pending pool/index containers and projection construction only.
        scratch = 65536 + 4*sum(_width(source[name]) for name in used)
        scratch += 128*(len(source)+len(parts)+len(record)+1)
        with self._budget.reserve(scratch, category='routing-view-project'):
            definitions, pending, pool_bytes = {}, {}, 0
            for name, value in source.items():
                if name not in used:
                    continue
                if type(value) is not dict:
                    raise TypeError('plain constraint definition dictionaries required')
                _json_definition(value)
                if self._intern:
                    key = json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf8')
                    shared = self._pool.get(key, pending.get(key))
                    if shared is None:
                        pending[key] = shared = value
                        # Exact bytes key + definition graph + table/reference slots.
                        pool_bytes += 128 + len(key) + _width(value)
                    definitions[name] = shared
                else:
                    definitions[name] = value
            projected_parts = [{k: v for k, v in part.items() if k in _PART} for part in parts]
            view = {k: (definitions if k == 'constraints' else projected_parts if k == 'components' else v)
                    for k, v in record.items() if k in _ROW}
            slots = 16*(len(view)+len(projected_parts)+sum(len(p) for p in projected_parts))
            if self._intern:
                # Count definition references, not their already pool-owned values.
                shell = {k: v for k, v in view.items() if k != 'constraints'}
                view_bytes = 128 + _width(shell) + _width('constraints') + 128 + slots
                view_bytes += sum(_width(name)+16 for name in definitions)
            else:
                view_bytes = 128 + _width(view) + slots + 16*len(definitions)
            # Admission failure is atomic: no pool/stat mutation has happened.
            self._lease.add(view_bytes+pool_bytes, category='routing-view-retained')
            try:
                self._pool.update(pending)
            except BaseException:
                # Disable reuse, but let the enclosing owner retain charges
                # for partially updated objects reachable through a traceback.
                self._active = False
                raise
            self._stats['view_bytes'] += view_bytes
            self._stats['pool_bytes'] += pool_bytes
            self._stats['unique_definitions'] = len(self._pool)
            self._stats['projected_supports'] += 1
            return view


class _FailureOwner:
    """Keep arena charges until both an error and its complete payloads die.

    The finalizer owns only an ExitStack of resource callbacks, never the
    exception/traceback or this owner. Thus traceback cycles remain collectable.
    """
    def __init__(self, stack):
        self.release = weakref.finalize(self, stack.close)


class _OwnedPayload(dict):
    """Same JSON contract, with an out-of-band resource lifetime."""
    def __init__(self, value, owner):
        super().__init__(value)
        self._resource_owner = owner


class RoutingArena(_Arena):
    """An escaping traceback still owns this operation's decoded objects."""
    def __init__(self, budget):
        super().__init__(budget)
        self._failure_owner = _FailureOwner(self.stack)

    def __exit__(self, kind, error, tb):
        if error is None:
            self._failure_owner.release()
        else:
            # No new reservation on failure. Traceback frames can retain the
            # routing views, cells and receipts, not just the diagnostic rows.
            error._differential_ale_owner = self._failure_owner
            for name in ('physical_measure_failure', 'physical_stream_failure',
                         'component_moment_failure', 'component_volume_failure'):
                payload = getattr(error, name, None)
                if type(payload) is dict:
                    setattr(error, name, _OwnedPayload(payload, self._failure_owner))
        self._failure_owner = None
        return False


class SupportRoutingRows:
    """Small routing views; complete support records only for a failed query.

    Prepay the two largest structurally counted support graphs before decoding.
    A separate decoder allowance is also prepaid, because failure capture must
    never make a new admission after the original refusal. Projection reuses
    that same workspace; its complete input dies before numerical work starts.
    These are capacity reservations, not allocated byte buffers. At most two
    distinct operands belong to one failed physical query.
    Original issued bytes/identities and every numerical query are unchanged.
    """
    def __init__(self, supports, budget, arena):
        self._budget, self._arena = budget, arena
        # Admit the scanner and handle/index containers before scanning bytes.
        arena.stack.enter_context(budget.reserve(65536+256*len(supports),
            category='routing-diagnostic-metadata'))
        largest = second = workspace = 0
        for support in supports:
            # record() also inserts its issued identity outside the encoded body.
            size = 4096+_decoded_json_capacity(support._json)
            if size > largest:
                largest, second = size, largest
            elif size > second:
                second = size
            workspace = max(workspace, _decode_workspace(support._json))
        arena.stack.enter_context(budget.reserve(largest+second,
            category='routing-diagnostic-graphs'))
        arena.stack.enter_context(budget.reserve(workspace,
            category='routing-diagnostic-decoder'))
        self._views = arena.stack.enter_context(RoutingViews(budget, intern=True))
        self._measure_lease = arena.stack.enter_context(_GrowingLease(budget))
        self._measure_capacity = 0
        self._handles, self._diagnostics = {}, {}

    def project(self, support):
        # Full input dies in this helper before numerical integration starts;
        # the caller never keeps its frame-local reference alongside the view.
        if getattr(support, '_compact_ref', None) is not None:
            # Issued from a compact partition: retain DAG references and a handle.
            from partition_routing_patch import project_compact
            return project_compact(self, support)
        view = self._views.project(support.record())
        self._handles[support.support_id] = support
        return view

    def measure_record(self, measure):
        size = 4096+_decoded_json_capacity(measure._json)
        if size > self._measure_capacity:
            self._measure_lease.add(size-self._measure_capacity,
                category='routing-measure-decode')
            self._measure_capacity = size
        # Retained receipt rows are charged by their caller. Only one current
        # unretained row needs this high-water capacity. Decoder input is scoped
        # to this call on success; an escaping traceback retains its lease.
        decoder = ExitStack()
        try:
            decoder.enter_context(self._budget.reserve(_decode_workspace(measure._json),
                category='routing-measure-decoder'))
            value = measure.record()
        except BaseException:
            self._arena.stack.callback(decoder.close)
            raise
        else:
            decoder.close()
            return value

    def __contains__(self, key):
        return key in self._handles

    def __getitem__(self, key):
        compact = sys.modules.get('partition_routing_patch')
        if compact is not None and type(self._handles.get(key)) is compact.CompactSupport:
            return compact.diagnostic(self, key)
        if key not in self._diagnostics:
            if len(self._diagnostics) >= 2:
                raise RuntimeError('one failed physical query has more than two support operands')
            self._diagnostics[key] = self._handles[key].record()
        return self._diagnostics[key]
